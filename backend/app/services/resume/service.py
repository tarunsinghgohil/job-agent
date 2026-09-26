"""Resume library operations: upload, versioning, parsing, and tailoring."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.db.base import utcnow
from app.db.models.resumes import Resume, ResumeEvidence, ResumeVersion
from app.services import audit
from app.services.ai.rag import embed_resume_version
from app.services.resume import parser, storage

logger = logging.getLogger(__name__)


def get_owned_resume(db: Session, user_id: str, resume_id: str) -> Resume:
    resume = db.get(Resume, resume_id)
    if resume is None or resume.user_id != user_id or resume.deleted_at is not None:
        raise NotFoundError("That resume does not exist.")
    return resume


def get_owned_version(db: Session, user_id: str, version_id: str) -> ResumeVersion:
    version = db.get(ResumeVersion, version_id)
    if version is None:
        raise NotFoundError("That resume version does not exist.")
    get_owned_resume(db, user_id, version.resume_id)
    return version


def next_version_number(db: Session, resume_id: str) -> int:
    current = db.execute(
        select(func.max(ResumeVersion.version_number)).where(
            ResumeVersion.resume_id == resume_id
        )
    ).scalar()
    return int(current or 0) + 1


def set_default(db: Session, user_id: str, resume_id: str) -> Resume:
    """Exactly one resume is the default at any time."""
    target = get_owned_resume(db, user_id, resume_id)
    for other in db.execute(
        select(Resume).where(Resume.user_id == user_id, Resume.is_default.is_(True))
    ).scalars().all():
        other.is_default = False
    target.is_default = True
    return target


def add_version_from_upload(
    db: Session,
    user_id: str,
    resume: Resume,
    content: bytes,
    filename: str | None,
    content_type: str | None,
    *,
    ai_service: Any = None,
    label: str = "",
    actor: str = "user",
) -> ResumeVersion:
    """Validate, store, parse, index and embed one uploaded file.

    Parsing failures are recorded on the version rather than raised: the file
    is safely stored and the user can see why it could not be read.
    """
    stored = storage.validate_and_store(content, filename, content_type)

    duplicate = db.execute(
        select(ResumeVersion)
        .join(Resume, ResumeVersion.resume_id == Resume.id)
        .where(
            Resume.user_id == user_id,
            ResumeVersion.checksum_sha256 == stored.checksum_sha256,
        )
    ).scalars().first()
    if duplicate is not None:
        storage.delete_stored(stored.storage_path)
        raise ValidationError(
            "That exact file has already been uploaded as "
            f"version {duplicate.version_number}."
        )

    version = ResumeVersion(
        resume_id=resume.id,
        version_number=next_version_number(db, resume.id),
        label=label or stored.original_filename,
        origin="upload",
        storage_path=stored.storage_path,
        original_filename=stored.original_filename,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
    )
    db.add(version)
    db.flush()

    parsed = parser.parse(stored.storage_path, stored.extension)
    if parsed.ok:
        version.extracted_text = parsed.text
        version.sections = parsed.sections
        version.extracted_skills = parsed.skills
        version.parse_status = "parsed"
        version.parse_error = ""
    else:
        version.parse_status = "failed"
        version.parse_error = parsed.error or "The document could not be read."
        logger.info("Resume %s parsed with no text: %s", version.id, version.parse_error)

    resume.current_version_id = version.id

    if parsed.ok:
        embed_resume_version(db, ai_service, version)
        _index_evidence(db, user_id, version, parsed)

    audit.record(
        db,
        action="resume.version.create",
        user_id=user_id,
        actor=actor,
        entity_type="resume_version",
        entity_id=version.id,
        summary=(
            f"Uploaded {stored.original_filename} as {resume.name} "
            f"v{version.version_number} ({version.parse_status})"
        ),
        after={"skills_found": len(version.extracted_skills)},
        success=parsed.ok,
    )
    return version


def _index_evidence(
    db: Session, user_id: str, version: ResumeVersion, parsed: parser.ParsedResume
) -> None:
    """Record one evidence row per extracted skill.

    These are what generation is allowed to cite, which is how the
    'no invented skills' rule is enforced in practice.
    """
    text_lower = parsed.text.lower()
    for skill in parsed.skills:
        snippet = ""
        index = text_lower.find(skill.lower())
        if index >= 0:
            start = max(0, index - 120)
            snippet = parsed.text[start : index + 180].strip()

        db.add(
            ResumeEvidence(
                user_id=user_id,
                resume_version_id=version.id,
                kind="skill",
                claim=skill,
                supporting_text=snippet,
                confidence=1.0,
            )
        )


def delete_version(db: Session, user_id: str, version: ResumeVersion) -> None:
    resume = get_owned_resume(db, user_id, version.resume_id)
    if resume.current_version_id == version.id:
        remaining = [v for v in resume.versions if v.id != version.id]
        resume.current_version_id = remaining[0].id if remaining else None
    if version.storage_path:
        storage.delete_stored(version.storage_path)
    db.delete(version)


def base_text_for(db: Session, user_id: str, resume: Resume, version_id: str | None) -> str:
    """Pick the text to tailor from: an explicit version, else the current one."""
    version: ResumeVersion | None
    if version_id:
        version = get_owned_version(db, user_id, version_id)
    elif resume.current_version_id:
        version = db.get(ResumeVersion, resume.current_version_id)
    else:
        version = resume.versions[0] if resume.versions else None

    if version is None:
        raise ValidationError(
            "This resume has no uploaded version yet. Upload a PDF or DOCX first."
        )
    if not version.extracted_text.strip():
        raise ValidationError(
            "No text could be extracted from that resume version, so it cannot be tailored."
        )
    return version.extracted_text


def save_tailored_version(
    db: Session,
    user_id: str,
    resume: Resume,
    job_id: str,
    data: dict[str, Any],
    *,
    actor: str = "ai",
) -> ResumeVersion:
    """Persist a generated draft as a new, clearly-labelled version."""
    body_parts = [str(data.get("summary", "")).strip()]
    highlights = data.get("highlights") or []
    if highlights:
        body_parts.append("\n".join(f"- {h}" for h in highlights))
    skills_order = data.get("skills_order") or []
    if skills_order:
        body_parts.append("Skills: " + ", ".join(str(s) for s in skills_order))

    version = ResumeVersion(
        resume_id=resume.id,
        version_number=next_version_number(db, resume.id),
        label=f"Tailored for job {job_id[:8]}",
        origin="tailored",
        extracted_text="\n\n".join(p for p in body_parts if p),
        parse_status="generated",
        tailored_for_job_id=job_id,
        generation_notes={
            "changed_sections": data.get("changed_sections", []),
            "omitted": data.get("omitted", []),
            "unsupported_requests": data.get("unsupported_requests", []),
            "validation": data.get("validation", {}),
            "evidence_ids": [e.get("evidence_id") for e in data.get("evidence", [])],
        },
    )
    db.add(version)
    db.flush()

    audit.record(
        db,
        action="resume.tailor",
        user_id=user_id,
        actor=actor,
        entity_type="resume_version",
        entity_id=version.id,
        summary=f"Generated a tailored draft of {resume.name} for job {job_id}",
        after={"validation_ok": bool(data.get("validation", {}).get("ok", True))},
    )
    return version

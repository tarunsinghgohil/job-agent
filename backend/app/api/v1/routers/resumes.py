"""Resume library, uploads, versions, and tailoring."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import Context, CurrentProfile, DbSession, rate_limit_ai
from app.core.errors import NotFoundError, ValidationError
from app.db.base import utcnow
from app.db.models.resumes import Resume, ResumeVersion
from app.schemas.common import MessageResponse
from app.schemas.resumes import (
    ResumeIn,
    ResumeOut,
    ResumeVersionDetailOut,
    ResumeVersionOut,
    TailorRequest,
    TailorResult,
)
from app.services import audit
from app.services.ai.client import AIService
from app.services.ai.functions import tailor_resume
from app.services.jobs import get_owned_job
from app.services.resume import service as resume_service, storage

router = APIRouter(prefix="/resumes", tags=["resumes"])


def _version_out(version: ResumeVersion) -> ResumeVersionOut:
    return ResumeVersionOut(
        id=version.id,
        created_at=version.created_at,
        updated_at=version.updated_at,
        version_number=version.version_number,
        label=version.label,
        origin=version.origin,
        original_filename=version.original_filename,
        content_type=version.content_type,
        size_bytes=version.size_bytes,
        checksum_sha256=version.checksum_sha256,
        parse_status=version.parse_status,
        parse_error=version.parse_error,
        extracted_skills=version.extracted_skills or [],
        tailored_for_job_id=version.tailored_for_job_id,
        generation_notes=version.generation_notes or {},
        chunk_count=len(version.chunks),
    )


def _resume_out(resume: Resume) -> ResumeOut:
    versions = sorted(resume.versions, key=lambda v: v.version_number, reverse=True)
    return ResumeOut(
        id=resume.id,
        created_at=resume.created_at,
        updated_at=resume.updated_at,
        name=resume.name,
        description=resume.description,
        tags=resume.tags or [],
        role_focus=resume.role_focus or [],
        industry_focus=resume.industry_focus or [],
        skill_focus=resume.skill_focus or [],
        is_active=resume.is_active,
        is_default=resume.is_default,
        current_version_id=resume.current_version_id,
        version_count=len(versions),
        versions=[_version_out(v) for v in versions],
    )


@router.get("", response_model=list[ResumeOut])
def list_resumes(db: DbSession, ctx: Context) -> list[ResumeOut]:
    rows = db.execute(
        select(Resume)
        .where(Resume.user_id == ctx.user_id, Resume.deleted_at.is_(None))
        .order_by(Resume.is_default.desc(), Resume.name)
    ).scalars().all()
    return [_resume_out(r) for r in rows]


@router.post("", response_model=ResumeOut, status_code=201)
def create_resume(payload: ResumeIn, db: DbSession, ctx: Context) -> ResumeOut:
    existing_count = db.execute(
        select(Resume).where(Resume.user_id == ctx.user_id, Resume.deleted_at.is_(None))
    ).scalars().all()

    resume = Resume(user_id=ctx.user_id, **payload.model_dump())
    # The first resume created becomes the default automatically.
    resume.is_default = not existing_count
    db.add(resume)
    db.flush()

    audit.record(
        db, action="resume.create", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="resume", entity_id=resume.id, summary=f"Created resume: {resume.name}",
    )
    return _resume_out(resume)


@router.get("/{resume_id}", response_model=ResumeOut)
def get_resume(resume_id: str, db: DbSession, ctx: Context) -> ResumeOut:
    return _resume_out(resume_service.get_owned_resume(db, ctx.user_id, resume_id))


@router.put("/{resume_id}", response_model=ResumeOut)
def update_resume(
    resume_id: str, payload: ResumeIn, db: DbSession, ctx: Context
) -> ResumeOut:
    resume = resume_service.get_owned_resume(db, ctx.user_id, resume_id)
    for name, value in payload.model_dump().items():
        setattr(resume, name, value)
    db.flush()
    audit.record(
        db, action="resume.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="resume", entity_id=resume.id, summary=f"Updated resume: {resume.name}",
    )
    return _resume_out(resume)


@router.delete("/{resume_id}", response_model=MessageResponse)
def delete_resume(resume_id: str, db: DbSession, ctx: Context) -> MessageResponse:
    resume = resume_service.get_owned_resume(db, ctx.user_id, resume_id)
    resume.deleted_at = utcnow()
    resume.is_active = False
    resume.is_default = False
    audit.record(
        db, action="resume.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="resume", entity_id=resume.id, summary=f"Archived resume: {resume.name}",
    )
    return MessageResponse(message="Resume archived.")


@router.post("/{resume_id}/default", response_model=ResumeOut)
def make_default(resume_id: str, db: DbSession, ctx: Context) -> ResumeOut:
    resume = resume_service.set_default(db, ctx.user_id, resume_id)
    db.flush()
    audit.record(
        db, action="resume.set_default", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="resume", entity_id=resume.id, summary=f"Default resume is now {resume.name}",
    )
    return _resume_out(resume)


# --------------------------------------------------------------------------
# Versions
# --------------------------------------------------------------------------
@router.get("/{resume_id}/versions", response_model=list[ResumeVersionOut])
def list_versions(resume_id: str, db: DbSession, ctx: Context) -> list[ResumeVersionOut]:
    resume = resume_service.get_owned_resume(db, ctx.user_id, resume_id)
    return [
        _version_out(v)
        for v in sorted(resume.versions, key=lambda v: v.version_number, reverse=True)
    ]


@router.post("/{resume_id}/versions", response_model=ResumeVersionOut, status_code=201)
async def upload_version(
    resume_id: str,
    db: DbSession,
    ctx: Context,
    file: UploadFile = File(...),
    label: str = "",
) -> ResumeVersionOut:
    resume = resume_service.get_owned_resume(db, ctx.user_id, resume_id)

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise ValidationError(
            f"That file is larger than the {settings.max_upload_bytes // (1024 * 1024)} MB limit."
        )

    try:
        version = resume_service.add_version_from_upload(
            db,
            ctx.user_id,
            resume,
            content,
            file.filename,
            file.content_type,
            ai_service=AIService(db, ctx.user_id),
            label=label,
            actor=ctx.actor,
        )
    except storage.UploadRejected as exc:
        raise ValidationError(str(exc), code=exc.code) from exc

    db.flush()
    return _version_out(version)


@router.get("/versions/{version_id}", response_model=ResumeVersionDetailOut)
def get_version(version_id: str, db: DbSession, ctx: Context) -> ResumeVersionDetailOut:
    version = resume_service.get_owned_version(db, ctx.user_id, version_id)
    return ResumeVersionDetailOut(
        **_version_out(version).model_dump(),
        extracted_text=version.extracted_text,
        sections=version.sections or {},
    )


@router.get("/versions/{version_id}/download")
def download_version(version_id: str, db: DbSession, ctx: Context) -> FileResponse:
    version = resume_service.get_owned_version(db, ctx.user_id, version_id)
    if not version.storage_path:
        raise NotFoundError("That version has no stored file; it was generated, not uploaded.")
    try:
        path = storage.resolve_stored_path(version.storage_path)
    except storage.UploadRejected as exc:
        raise NotFoundError(str(exc)) from exc

    return FileResponse(
        path,
        media_type=version.content_type or "application/octet-stream",
        filename=version.original_filename or "resume",
    )


@router.delete("/versions/{version_id}", response_model=MessageResponse)
def delete_version(version_id: str, db: DbSession, ctx: Context) -> MessageResponse:
    version = resume_service.get_owned_version(db, ctx.user_id, version_id)
    resume_service.delete_version(db, ctx.user_id, version)
    audit.record(
        db, action="resume.version.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="resume_version", entity_id=version_id, summary="Deleted a resume version",
    )
    return MessageResponse(message="Version deleted.")


# --------------------------------------------------------------------------
# Tailoring
# --------------------------------------------------------------------------
@router.post("/{resume_id}/tailor", response_model=TailorResult)
def tailor(
    resume_id: str,
    payload: TailorRequest,
    db: DbSession,
    ctx: Context,
    profile: CurrentProfile,
    _: Annotated[None, Depends(rate_limit_ai)] = None,
) -> TailorResult:
    resume = resume_service.get_owned_resume(db, ctx.user_id, resume_id)
    job = get_owned_job(db, ctx.user_id, payload.job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")

    base_text = resume_service.base_text_for(db, ctx.user_id, resume, payload.base_version_id)

    ai = AIService(db, ctx.user_id)
    data = tailor_resume(
        db, ai, ctx.user_id, job, profile, base_text, resume_id=resume.id
    )

    saved_id: str | None = None
    if payload.save_as_version:
        version = resume_service.save_tailored_version(
            db, ctx.user_id, resume, job.id, data, actor=ctx.actor
        )
        saved_id = version.id

    db.flush()
    return TailorResult(
        job_id=job.id,
        resume_id=resume.id,
        summary=str(data.get("summary", "")),
        highlights=[str(h) for h in (data.get("highlights") or [])],
        skills_order=[str(s) for s in (data.get("skills_order") or [])],
        changed_sections=data.get("changed_sections") or [],
        omitted=[str(o) for o in (data.get("omitted") or [])],
        unsupported_requests=[str(u) for u in (data.get("unsupported_requests") or [])],
        evidence=data.get("evidence") or [],
        validation=data.get("validation") or {},
        saved_version_id=saved_id,
        original_text=base_text,
    )

"""Job persistence: ingest, skill extraction, scoring, and match storage.

Routers and the discovery agent both go through here, so a job scored by the
scheduler is scored exactly the same way as one entered by hand.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.enums import JobStatus, MatchDecision
from app.db.models.identity import CareerProfile
from app.db.models.jobs import Job, JobMatch, JobSkill
from app.db.models.preferences import JobPreference, MatchRule
from app.db.models.resumes import Resume
from app.services import audit
from app.services.matching import MatchResult, score_job
from app.services.normalize import (
    canonical_url,
    extract_application_email,
    normalize_company,
    parse_experience,
    slugify,
    text_hash,
)
from app.services.resume.parser import SKILL_VOCABULARY, extract_skills

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_rules(db: Session, user_id: str) -> list[MatchRule]:
    return list(
        db.execute(
            select(MatchRule)
            .where(MatchRule.user_id == user_id, MatchRule.enabled.is_(True))
            .order_by(MatchRule.priority)
        )
        .scalars()
        .all()
    )


def load_resumes(db: Session, user_id: str) -> list[Resume]:
    return list(
        db.execute(
            select(Resume).where(
                Resume.user_id == user_id,
                Resume.deleted_at.is_(None),
                Resume.is_active.is_(True),
            )
        )
        .scalars()
        .all()
    )


def load_preferences(db: Session, user_id: str) -> JobPreference:
    prefs = db.execute(
        select(JobPreference).where(JobPreference.user_id == user_id)
    ).scalar_one_or_none()
    if prefs is None:
        prefs = JobPreference(
            user_id=user_id, scoring_weights=JobPreference.default_weights()
        )
        db.add(prefs)
        db.flush()
    return prefs


def extract_and_store_skills(db: Session, job: Job) -> list[str]:
    """Deterministic skill extraction from the posting text."""
    blob = f"{job.title}\n{job.description}"
    names = extract_skills(blob)

    existing = {s.skill_slug for s in job.skills}
    required_section = (job.description or "").lower()

    for name in names:
        slug = slugify(name)
        if slug in existing:
            continue
        # A skill is "required" when it appears near requirement language.
        aliases = SKILL_VOCABULARY.get(name, (name,))
        is_required = any(
            marker in required_section
            for alias in aliases
            for marker in (f"must have {alias.lower()}", f"required: {alias.lower()}")
        )
        db.add(
            JobSkill(
                job_id=job.id,
                skill_slug=slug,
                skill_name=name,
                is_required=is_required,
                source="keyword",
                confidence=1.0,
            )
        )
        existing.add(slug)
    return names


def prepare_job_fields(job: Job) -> None:
    """Fill the derived columns the matcher and deduplicator rely on."""
    job.company_normalized = normalize_company(job.company)
    job.canonical_url = canonical_url(job.url or job.apply_url)
    job.description_hash = text_hash(job.description) if job.description else ""

    if job.experience_min_years is None and job.experience_max_years is None:
        lo, hi = parse_experience(job.description)
        job.experience_min_years = lo
        job.experience_max_years = hi

    if not job.application_email:
        job.application_email = extract_application_email(job.description)

    now = _now()
    if job.first_seen_at is None:
        job.first_seen_at = now
    job.last_seen_at = now


def score_and_store(
    db: Session,
    job: Job,
    preferences: JobPreference,
    *,
    rules: list[MatchRule] | None = None,
    resumes: list[Resume] | None = None,
    semantic_score: float | None = None,
    actor: str = "system",
) -> JobMatch:
    """Score a job and persist the result as the current match.

    Previous matches are retained with ``is_current=False`` so the history of
    how a job scored under older settings stays auditable.
    """
    if rules is None:
        rules = load_rules(db, job.user_id)
    if resumes is None:
        resumes = load_resumes(db, job.user_id)

    result: MatchResult = score_job(
        job, preferences, rules, resumes=resumes, semantic_score=semantic_score
    )

    for previous in db.execute(
        select(JobMatch).where(JobMatch.job_id == job.id, JobMatch.is_current.is_(True))
    ).scalars().all():
        previous.is_current = False

    match = JobMatch(
        job_id=job.id,
        user_id=job.user_id,
        score=result.score,
        decision=result.decision,
        deterministic_score=result.deterministic_score,
        semantic_score=result.semantic_score,
        breakdown=result.breakdown,
        hard_fail_reasons=result.hard_fail_reasons,
        matched_skills=result.matched_skills,
        missing_skills=result.missing_skills,
        positive_signals=result.positive_signals,
        rule_results=result.rule_results,
        explanation=result.explanation,
        recommended_resume_id=result.recommended_resume_id,
        recommendation_reason=result.recommendation_reason,
        engine_version=result.engine_version,
        is_current=True,
    )
    db.add(match)

    # Status follows the decision, but never downgrades a job the user has
    # already acted on.
    if job.status in (JobStatus.NEW, JobStatus.QUALIFIED, JobStatus.REJECTED):
        job.status = (
            JobStatus.QUALIFIED
            if result.decision in (MatchDecision.HIGH_PRIORITY, MatchDecision.REVIEW)
            else JobStatus.REJECTED
        )

    audit.job_event(
        db,
        job.id,
        "scored",
        message=f"{result.decision} at {result.score:.0f}/100",
        payload={
            "score": result.score,
            "decision": result.decision,
            "hard_fail_reasons": result.hard_fail_reasons,
        },
        actor=actor,
    )
    return match


def current_match(db: Session, job_id: str) -> JobMatch | None:
    return db.execute(
        select(JobMatch)
        .where(JobMatch.job_id == job_id, JobMatch.is_current.is_(True))
        .order_by(JobMatch.created_at.desc())
    ).scalars().first()


def create_job(
    db: Session,
    user_id: str,
    data: dict[str, Any],
    *,
    preferences: JobPreference | None = None,
    actor: str = "user",
    source_id: str | None = None,
) -> tuple[Job, JobMatch]:
    """Insert a job, extract its skills, and score it in one step."""
    job = Job(user_id=user_id, source_id=source_id, **data)
    prepare_job_fields(job)

    from app.services.dedupe import compute_dedupe_key

    job.dedupe_key = compute_dedupe_key(job, job.source_name)
    db.add(job)
    db.flush()

    extract_and_store_skills(db, job)
    audit.job_event(db, job.id, "created", message=f"Added from {job.source_name}", actor=actor)

    prefs = preferences or load_preferences(db, user_id)
    match = score_and_store(db, job, prefs, actor=actor)
    return job, match


def rescore_all(db: Session, user_id: str, *, actor: str = "system") -> dict[str, int]:
    """Re-run scoring for every non-archived job, e.g. after editing rules."""
    prefs = load_preferences(db, user_id)
    rules = load_rules(db, user_id)
    resumes = load_resumes(db, user_id)

    jobs = (
        db.execute(
            select(Job)
            .options(selectinload(Job.skills))
            .where(Job.user_id == user_id, Job.deleted_at.is_(None))
        )
        .scalars()
        .all()
    )

    tally = {"rescored": 0, "high_priority": 0, "review": 0, "rejected": 0}
    for job in jobs:
        match = score_and_store(
            db, job, prefs, rules=rules, resumes=resumes, actor=actor
        )
        tally["rescored"] += 1
        if match.decision == MatchDecision.HIGH_PRIORITY:
            tally["high_priority"] += 1
        elif match.decision == MatchDecision.REVIEW:
            tally["review"] += 1
        else:
            tally["rejected"] += 1
    return tally


def score_unscored(db: Session, user_id: str, *, actor: str = "system") -> int:
    """Score every job that has no current match.

    Discovery ingests jobs without scoring them, so that a slow or failing
    scorer can never block ingestion. This is the second half of that split.
    """
    prefs = load_preferences(db, user_id)
    rules = load_rules(db, user_id)
    resumes = load_resumes(db, user_id)

    scored_job_ids = select(JobMatch.job_id).where(
        JobMatch.user_id == user_id, JobMatch.is_current.is_(True)
    )
    pending = (
        db.execute(
            select(Job).where(
                Job.user_id == user_id,
                Job.deleted_at.is_(None),
                Job.id.not_in(scored_job_ids),
            )
        )
        .scalars()
        .all()
    )

    for job in pending:
        if not job.skills:
            extract_and_store_skills(db, job)
        score_and_store(db, job, prefs, rules=rules, resumes=resumes, actor=actor)
    return len(pending)


def get_owned_job(db: Session, user_id: str, job_id: str) -> Job | None:
    return db.execute(
        select(Job)
        .options(selectinload(Job.skills), selectinload(Job.events))
        .where(Job.id == job_id, Job.user_id == user_id, Job.deleted_at.is_(None))
    ).scalars().first()


def serialize_job(job: Job, match: JobMatch | None = None) -> dict[str, Any]:
    """Shape a job for the API, embedding its current match."""
    payload: dict[str, Any] = {
        c.name: getattr(job, c.name)
        for c in job.__table__.columns
        if c.name not in ("raw_payload", "embedding", "description")
    }
    payload["match"] = match
    return payload

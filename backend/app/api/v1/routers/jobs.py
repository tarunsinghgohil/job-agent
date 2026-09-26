"""Job discovery, listing, detail, scoring, and the AI assist endpoints."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.deps import (
    Context,
    CurrentPreferences,
    CurrentProfile,
    DbSession,
    rate_limit_ai,
)
from app.core.errors import NotFoundError, ValidationError
from app.db.models.jobs import Job, JobMatch
from app.schemas.common import MessageResponse, Page
from app.schemas.jobs import (
    DiscoverRequest,
    DiscoverResult,
    JobDetailOut,
    JobEventOut,
    JobIn,
    JobOut,
    JobPatch,
    JobSkillOut,
    MatchOut,
    MatchPreviewRequest,
    RescoreResult,
)
from app.services import audit
from app.services.ai.client import AIService
from app.services.ai.functions import (
    cover_letter as ai_cover_letter,
    resume_advice as ai_resume_advice,
    semantic_match as ai_semantic_match,
    summarize_job as ai_summarize_job,
)
from app.services.discovery import discover
from app.services.jobs import (
    create_job,
    current_match,
    get_owned_job,
    load_resumes,
    rescore_all,
    score_and_store,
    score_unscored,
)
from app.services.matching import score_job as pure_score_job

router = APIRouter(tags=["jobs"])


def _job_out(job: Job, match: JobMatch | None) -> JobOut:
    return JobOut(
        id=job.id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        title=job.title,
        company=job.company,
        location=job.location,
        is_remote=job.is_remote,
        url=job.url,
        apply_url=job.apply_url,
        application_email=job.application_email,
        salary_min_lpa=job.salary_min_lpa,
        salary_max_lpa=job.salary_max_lpa,
        salary_raw=job.salary_raw,
        currency=job.currency,
        employment_type=job.employment_type,
        industry=job.industry,
        experience_min_years=job.experience_min_years,
        experience_max_years=job.experience_max_years,
        source_name=job.source_name,
        source_id=job.source_id,
        status=job.status,
        posted_at=job.posted_at,
        first_seen_at=job.first_seen_at,
        last_seen_at=job.last_seen_at,
        seen_count=job.seen_count,
        duplicate_sources=job.duplicate_sources or [],
        match=MatchOut.model_validate(match) if match else None,
    )


@router.get("/jobs", response_model=Page[JobOut])
def list_jobs(
    db: DbSession,
    ctx: Context,
    status: str | None = None,
    decision: str | None = None,
    source_id: str | None = None,
    q: str | None = None,
    min_score: float | None = Query(default=None, ge=0, le=100),
    sort: str = Query(default="score", pattern="^(score|created_at|posted_at|company|title)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> Page[JobOut]:
    """Paginated job list, joined to each job's current match."""
    stmt = (
        select(Job, JobMatch)
        .outerjoin(
            JobMatch,
            (JobMatch.job_id == Job.id) & (JobMatch.is_current.is_(True)),
        )
        .where(Job.user_id == ctx.user_id, Job.deleted_at.is_(None))
    )

    if status:
        stmt = stmt.where(Job.status == status)
    if source_id:
        stmt = stmt.where(Job.source_id == source_id)
    if decision:
        stmt = stmt.where(JobMatch.decision == decision)
    if min_score is not None:
        stmt = stmt.where(JobMatch.score >= min_score)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Job.title.ilike(needle), Job.company.ilike(needle), Job.description.ilike(needle))
        )

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    sort_column = {
        "score": JobMatch.score,
        "created_at": Job.created_at,
        "posted_at": Job.posted_at,
        "company": Job.company,
        "title": Job.title,
    }[sort]
    stmt = stmt.order_by(
        sort_column.desc().nullslast() if order == "desc" else sort_column.asc().nullsfirst()
    )
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    rows = db.execute(stmt).all()
    return Page.build(
        [_job_out(job, match) for job, match in rows], total, page, page_size
    )


@router.post("/jobs", response_model=JobDetailOut, status_code=201)
def create_job_endpoint(
    payload: JobIn, db: DbSession, ctx: Context, prefs: CurrentPreferences
) -> JobDetailOut:
    """Manual ingest. Scores immediately so the user sees a decision at once."""
    job, match = create_job(
        db, ctx.user_id, payload.model_dump(), preferences=prefs, actor=ctx.actor
    )
    db.flush()
    audit.record(
        db, action="job.create", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job", entity_id=job.id,
        summary=f"Added job manually: {job.title} at {job.company}",
    )
    return _detail_out(job, match)


def _detail_out(job: Job, match: JobMatch | None) -> JobDetailOut:
    base = _job_out(job, match)
    return JobDetailOut(
        **base.model_dump(),
        description=job.description,
        skills=[JobSkillOut.model_validate(s) for s in job.skills],
        events=[JobEventOut.model_validate(e) for e in sorted(
            job.events, key=lambda e: e.created_at, reverse=True
        )[:100]],
    )


@router.get("/jobs/{job_id}", response_model=JobDetailOut)
def get_job(job_id: str, db: DbSession, ctx: Context) -> JobDetailOut:
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")
    return _detail_out(job, current_match(db, job.id))


@router.patch("/jobs/{job_id}", response_model=JobDetailOut)
def patch_job(
    job_id: str, payload: JobPatch, db: DbSession, ctx: Context, prefs: CurrentPreferences
) -> JobDetailOut:
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")

    changes = payload.model_dump(exclude_none=True)
    for name, value in changes.items():
        setattr(job, name, value)

    # Editing anything the matcher reads invalidates the stored score.
    scoring_fields = {
        "title", "company", "location", "is_remote", "description",
        "salary_min_lpa", "salary_max_lpa", "employment_type", "industry",
    }
    match = current_match(db, job.id)
    if scoring_fields & set(changes):
        match = score_and_store(db, job, prefs, actor=ctx.actor)

    db.flush()
    audit.record(
        db, action="job.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job", entity_id=job.id,
        summary=f"Edited job fields: {', '.join(sorted(changes))}", after=changes,
    )
    return _detail_out(job, match)


@router.delete("/jobs/{job_id}", response_model=MessageResponse)
def delete_job(job_id: str, db: DbSession, ctx: Context) -> MessageResponse:
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")
    from app.db.base import utcnow

    job.deleted_at = utcnow()
    audit.record(
        db, action="job.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job", entity_id=job.id, summary=f"Archived job: {job.title}",
    )
    return MessageResponse(message="Job archived.")


@router.post("/jobs/{job_id}/rescore", response_model=JobDetailOut)
def rescore_job(
    job_id: str, db: DbSession, ctx: Context, prefs: CurrentPreferences
) -> JobDetailOut:
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")
    match = score_and_store(db, job, prefs, actor=ctx.actor)
    db.flush()
    return _detail_out(job, match)


@router.post("/jobs/rescore-all", response_model=RescoreResult)
def rescore_everything(db: DbSession, ctx: Context) -> RescoreResult:
    tally = rescore_all(db, ctx.user_id, actor=ctx.actor)
    audit.record(
        db, action="job.rescore_all", user_id=ctx.user_id, actor=ctx.actor,
        summary=f"Re-scored {tally['rescored']} jobs", after=tally,
    )
    return RescoreResult(**tally)


@router.get("/jobs/{job_id}/events", response_model=list[JobEventOut])
def job_events(job_id: str, db: DbSession, ctx: Context) -> list[JobEventOut]:
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")
    return [
        JobEventOut.model_validate(e)
        for e in sorted(job.events, key=lambda e: e.created_at, reverse=True)
    ]


@router.post("/jobs/discover", response_model=DiscoverResult)
def run_discovery(payload: DiscoverRequest, db: DbSession, ctx: Context) -> DiscoverResult:
    """Pull from the configured sources, then score whatever is new."""
    result = discover(
        db,
        ctx.user_id,
        source_ids=payload.source_ids,
        saved_search_id=payload.saved_search_id,
        limit_per_source=payload.limit_per_source,
    )
    db.flush()
    scored = score_unscored(db, ctx.user_id, actor=ctx.actor)

    audit.record(
        db, action="job.discover", user_id=ctx.user_id, actor=ctx.actor,
        summary=(
            f"Discovery added {result.created} new jobs, updated {result.updated}, "
            f"scored {scored}"
        ),
        after={"created": result.created, "updated": result.updated, "errors": len(result.errors)},
        success=not result.errors,
    )
    return DiscoverResult(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        errors=result.errors,
        per_source=result.per_source,
    )


@router.post("/match/preview")
def preview_match(
    payload: MatchPreviewRequest, db: DbSession, ctx: Context, prefs: CurrentPreferences
) -> dict[str, Any]:
    """Score pasted text without saving it, for the 'will this pass?' check."""
    from app.services.jobs import load_rules

    fake = payload.model_dump()
    fake["source_name"] = "preview"
    result = pure_score_job(
        fake, prefs, load_rules(db, ctx.user_id), resumes=load_resumes(db, ctx.user_id)
    )
    return result.as_dict()


# --------------------------------------------------------------------------
# AI assists
# --------------------------------------------------------------------------
@router.post("/jobs/{job_id}/ai-review")
def ai_review(
    job_id: str,
    db: DbSession,
    ctx: Context,
    profile: CurrentProfile,
    prefs: CurrentPreferences,
    _: Annotated[None, Depends(rate_limit_ai)] = None,
) -> dict[str, Any]:
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")

    match = current_match(db, job.id) or score_and_store(db, job, prefs, actor=ctx.actor)
    ai = AIService(db, ctx.user_id)
    data = ai_semantic_match(
        db, ai, ctx.user_id, job, profile, match.score, match.decision
    )

    # The AI score is advisory. It is blended only when the user has opted in,
    # and it can never clear a deterministic hard failure.
    if prefs.semantic_scoring_enabled and not match.hard_fail_reasons:
        score_and_store(
            db, job, prefs, semantic_score=float(data.get("ai_score") or 0), actor="ai"
        )

    audit.record(
        db, action="job.ai_review", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job", entity_id=job.id,
        summary=f"AI review: {data.get('verdict')} ({data.get('ai_score')})",
    )
    return {
        "job_id": job.id,
        "local_score": match.score,
        "local_decision": match.decision,
        "hard_fail_reasons": match.hard_fail_reasons,
        **{k: v for k, v in data.items() if k != "_meta"},
    }


@router.post("/jobs/{job_id}/cover-letter")
def cover_letter(
    job_id: str,
    db: DbSession,
    ctx: Context,
    profile: CurrentProfile,
    _: Annotated[None, Depends(rate_limit_ai)] = None,
) -> dict[str, Any]:
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")

    ai = AIService(db, ctx.user_id)
    data = ai_cover_letter(db, ai, ctx.user_id, job, profile)
    audit.record(
        db, action="job.cover_letter", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job", entity_id=job.id, summary="Generated a cover letter",
    )
    return {
        "job_id": job.id,
        "cover_letter": data.get("letter", ""),
        "evidence": data.get("evidence", []),
    }


@router.post("/jobs/{job_id}/resume-advice")
def resume_advice(
    job_id: str,
    db: DbSession,
    ctx: Context,
    profile: CurrentProfile,
    _: Annotated[None, Depends(rate_limit_ai)] = None,
) -> dict[str, Any]:
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")

    resumes = load_resumes(db, ctx.user_id)
    ai = AIService(db, ctx.user_id)
    data = ai_resume_advice(
        db, ai, ctx.user_id, job, profile, [r.name for r in resumes]
    )
    return {"job_id": job.id, **{k: v for k, v in data.items() if k != "_meta"}}


@router.post("/jobs/{job_id}/summary")
def job_summary(
    job_id: str,
    db: DbSession,
    ctx: Context,
    _: Annotated[None, Depends(rate_limit_ai)] = None,
) -> dict[str, Any]:
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")
    ai = AIService(db, ctx.user_id)
    return {"job_id": job.id, **{k: v for k, v in ai_summarize_job(ai, job).items() if k != "_meta"}}

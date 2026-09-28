"""3x Job Hunt: configuration, runs, the shortlist board, and previews."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.deps import Context, DbSession
from app.core.errors import NotFoundError, ValidationError
from app.db.models.automation import AgentRun
from app.db.models.hunt import HuntConfig
from app.db.models.jobs import JobSource
from app.db.models.preferences import JobPreference
from app.schemas.common import Page
from app.schemas.hunt import (
    HuntAssessRequest,
    HuntBoard,
    HuntConfigIn,
    HuntConfigOut,
    HuntItem,
    HuntJobDetail,
    HuntProfileSuggestions,
    HuntQueryOut,
    HuntQueryPreview,
    HuntRunOut,
    HuntRunRequest,
)
from app.services import audit
from app.services.hunt.assess import assess_job
from app.services.hunt.defaults import HUNT_AGENT_KEY, clean_tier, load_config, seed_values
from app.services.hunt.pipeline import (
    assess_jobs,
    build_board,
    get_schedule,
    job_assessment,
    list_results,
    profile_suggestions,
    set_schedule,
)
from app.services.hunt.queries import board_query, generate_queries
from app.services.jobs import get_owned_job
from app.services.suggest import invalidate_user as invalidate_suggestions
from app.services.sources import get_adapter_class
from app.services.sources.base import UnknownAdapterError

router = APIRouter(prefix="/hunt", tags=["hunt"])

_CONFIG_FIELDS = (
    "experience_years", "target_roles", "skills", "role_keywords", "excluded_seniority",
    "location_tiers", "country", "country_places", "accept_worldwide_remote",
    "auto_queries", "custom_queries", "excluded_queries", "max_queries", "results_per_query",
    "max_age_days", "apply_first_threshold", "min_skill_overlap", "weights", "semantic_mode",
    "respect_policy_filters", "notify_new_matches",
)


def _config_out(db: Any, user_id: str, config: HuntConfig) -> HuntConfigOut:
    schedule = get_schedule(db, user_id)
    return HuntConfigOut(
        id=config.id,
        updated_at=config.updated_at,
        last_run_at=config.last_run_at,
        last_assessed_at=config.last_assessed_at,
        next_run_at=schedule["next_run_at"],
        schedule_enabled=schedule["schedule_enabled"],
        schedule_cron=schedule["schedule_cron"] or "0 2,8,14,20 * * *",
        **{name: getattr(config, name) for name in _CONFIG_FIELDS},
    )


def _validate_cron(cron: str) -> None:
    from apscheduler.triggers.cron import CronTrigger

    try:
        CronTrigger.from_crontab(cron)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"{cron!r} is not a valid cron expression.") from exc


def _config_values(payload: HuntConfigIn) -> dict[str, Any]:
    values = payload.model_dump(exclude={"schedule_enabled", "schedule_cron"})
    values["location_tiers"] = [clean_tier(t) for t in values["location_tiers"]]
    return values


def _transient_config(payload: HuntConfigIn) -> SimpleNamespace:
    """An unsaved config, for previews of edits the user has not saved yet."""
    return SimpleNamespace(**_config_values(payload))


@router.get("/config", response_model=HuntConfigOut)
def get_config(db: DbSession, ctx: Context) -> HuntConfigOut:
    return _config_out(db, ctx.user_id, load_config(db, ctx.user_id))


@router.put("/config", response_model=HuntConfigOut)
def update_config(payload: HuntConfigIn, db: DbSession, ctx: Context) -> HuntConfigOut:
    """Save the setup screen, apply the schedule, and re-rank every job."""
    if not payload.location_tiers:
        raise ValidationError("Add at least one location priority.")
    _validate_cron(payload.schedule_cron)

    config = load_config(db, ctx.user_id)
    for name, value in _config_values(payload).items():
        setattr(config, name, value)
    db.flush()

    set_schedule(db, ctx.user_id, enabled=payload.schedule_enabled, cron=payload.schedule_cron)
    tally = assess_jobs(db, ctx.user_id, config=config)
    invalidate_suggestions(ctx.user_id)

    audit.record(
        db, action="hunt.config.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="hunt_config", entity_id=config.id,
        summary=f"Updated Job Hunt setup; re-ranked {tally.get('assessed', 0)} jobs",
    )
    return _config_out(db, ctx.user_id, config)


@router.post("/config/reset", response_model=HuntConfigOut)
def reset_config(db: DbSession, ctx: Context) -> HuntConfigOut:
    """Restore the seed values (the schedule is left as it is)."""
    config = load_config(db, ctx.user_id)
    for name, value in seed_values().items():
        setattr(config, name, value)
    db.flush()
    assess_jobs(db, ctx.user_id, config=config)
    audit.record(
        db, action="hunt.config.reset", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="hunt_config", entity_id=config.id, summary="Reset Job Hunt setup to defaults",
    )
    return _config_out(db, ctx.user_id, config)


@router.get("/profile-suggestions", response_model=HuntProfileSuggestions)
def get_profile_suggestions(db: DbSession, ctx: Context) -> HuntProfileSuggestions:
    return HuntProfileSuggestions(**profile_suggestions(db, ctx.user_id))


@router.post("/queries/preview", response_model=HuntQueryPreview)
def preview_queries(
    db: DbSession, ctx: Context, payload: HuntConfigIn | None = None
) -> HuntQueryPreview:
    """The exact queries a run would send, for the saved or an unsaved config."""
    config = _transient_config(payload) if payload is not None else load_config(db, ctx.user_id)
    queries = generate_queries(config)

    search_sources = 0
    board_sources = 0
    for source in db.scalars(
        select(JobSource).where(
            JobSource.user_id == ctx.user_id,
            JobSource.enabled.is_(True),
            JobSource.deleted_at.is_(None),
        )
    ):
        try:
            cls = get_adapter_class(source.adapter_type)
        except UnknownAdapterError:
            continue
        if getattr(cls, "supports_search", False):
            search_sources += 1
        else:
            board_sources += 1

    return HuntQueryPreview(
        queries=[HuntQueryOut(**q.as_dict()) for q in queries],
        search_sources=search_sources,
        board_sources=board_sources,
        board_keywords=board_query(config, 1).keywords,
    )


@router.post("/run", response_model=HuntRunOut)
def run_now(payload: HuntRunRequest, db: DbSession, ctx: Context) -> HuntRunOut:
    """Run the whole hunt now. Recorded in the same history as scheduled runs."""
    from app.agents.registry import run_agent

    run = run_agent(
        db, ctx.user_id, HUNT_AGENT_KEY, trigger="manual", config={"discover": payload.discover}
    )
    db.flush()
    audit.record(
        db, action="hunt.run", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="agent_run", entity_id=run.id,
        summary=f"Ran the Job Hunt: {run.status}",
        success=run.status in ("success", "partial"),
    )
    return HuntRunOut.model_validate(run, from_attributes=True)


@router.post("/assess")
def reassess(db: DbSession, ctx: Context) -> dict[str, Any]:
    """Re-rank every stored job without searching (e.g. after editing jobs)."""
    return assess_jobs(db, ctx.user_id)


@router.get("/board", response_model=HuntBoard)
def get_board(
    db: DbSession,
    ctx: Context,
    q: str | None = None,
    fresh_within_hours: int | None = Query(default=None, ge=1, le=24 * 365),
    limit_per_section: int = Query(default=30, ge=1, le=200),
) -> HuntBoard:
    return HuntBoard(
        **build_board(
            db, ctx.user_id, q=q, fresh_within_hours=fresh_within_hours,
            limit_per_section=limit_per_section,
        )
    )


@router.get("/results", response_model=Page[HuntItem])
def get_results(
    db: DbSession,
    ctx: Context,
    category: str | None = Query(default=None, pattern="^(apply_first|review|not_match)$"),
    q: str | None = None,
    fresh_within_hours: int | None = Query(default=None, ge=1, le=24 * 365),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> Page[HuntItem]:
    items, total = list_results(
        db, ctx.user_id, category=category, q=q, fresh_within_hours=fresh_within_hours,
        page=page, page_size=page_size,
    )
    return Page.build([HuntItem(**i) for i in items], total, page, page_size)


@router.get("/jobs/{job_id}", response_model=HuntJobDetail)
def get_job_assessment(job_id: str, db: DbSession, ctx: Context) -> HuntJobDetail:
    """One job's hunt assessment plus the resume evidence that supports it."""
    job = get_owned_job(db, ctx.user_id, job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")
    data = job_assessment(db, ctx.user_id, job)
    return HuntJobDetail(
        assessment=HuntItem(**data["assessment"]) if data["assessment"] else None,
        evidence=data["evidence"],
        breakdown_max=data["breakdown_max"],
    )


@router.post("/preview")
def preview_assessment(payload: HuntAssessRequest, db: DbSession, ctx: Context) -> dict[str, Any]:
    """Assess a pasted job without saving it ("Try it" on the setup screen)."""
    from app.services.normalize import extract_application_email, parse_experience

    config = (
        _transient_config(payload.config) if payload.config is not None
        else load_config(db, ctx.user_id)
    )
    job = payload.model_dump(exclude={"config"})
    if job["experience_min_years"] is None and job["experience_max_years"] is None:
        job["experience_min_years"], job["experience_max_years"] = parse_experience(job["description"])
    job["application_email"] = extract_application_email(job["description"])
    policy = db.scalar(select(JobPreference).where(JobPreference.user_id == ctx.user_id))
    return assess_job(job, config, policy=policy).as_dict()


@router.get("/runs", response_model=list[HuntRunOut])
def list_runs(
    db: DbSession, ctx: Context, limit: int = Query(default=10, ge=1, le=100)
) -> list[HuntRunOut]:
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.user_id == ctx.user_id, AgentRun.agent_key == HUNT_AGENT_KEY)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )
    return [HuntRunOut.model_validate(r, from_attributes=True) for r in runs]


@router.get("/status")
def hunt_status(db: DbSession, ctx: Context) -> dict[str, Any]:
    """Readiness checklist shown above the board."""
    config = load_config(db, ctx.user_id)
    sources = db.scalar(
        select(func.count()).select_from(JobSource).where(
            JobSource.user_id == ctx.user_id,
            JobSource.enabled.is_(True),
            JobSource.deleted_at.is_(None),
        )
    ) or 0
    schedule = get_schedule(db, ctx.user_id)
    return {
        "has_profile": bool(config.target_roles and config.skills and config.experience_years),
        "sources_enabled": int(sources),
        "schedule_enabled": schedule["schedule_enabled"],
        "next_run_at": schedule["next_run_at"],
        "last_run_at": config.last_run_at,
    }

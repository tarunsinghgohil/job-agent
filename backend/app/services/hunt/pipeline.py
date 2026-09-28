"""Hunt persistence and orchestration.

``run_hunt`` is the whole 3x Job Hunt workflow in one call:

    generate queries -> discover (multi-query) -> normalize + dedupe (on
    ingest) -> score with the main engine -> hunt assessment for every job ->
    categorise -> alert on new apply-first matches -> record the run.

It owns no transaction. The API route or the scheduler commits.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import event, func, or_, select
from sqlalchemy.orm import Session

from app.db.models.enums import NotificationEventType
from app.db.models.hunt import HuntConfig, HuntResult
from app.db.models.identity import CareerProfile
from app.db.models.jobs import Job, JobSource
from app.db.models.preferences import JobPreference
from app.db.models.resumes import Resume, ResumeVersion
from app.services.hunt.assess import Assessment, assess_job
from app.services.hunt.defaults import HUNT_AGENT_KEY, breakdown_max, load_config
from app.services.hunt.queries import board_query, generate_queries
from app.services.hunt.semantic import compute_semantic_scores
from app.services.hunt.signals import humanize_age

logger = logging.getLogger(__name__)

CATEGORY_ORDER = {"apply_first": 0, "review": 1, "not_match": 2}
MAX_ALERT_ITEMS = 10


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Profile text (the "resume" side of semantic matching)
# ---------------------------------------------------------------------------
def build_profile_text(db: Session, user_id: str, config: HuntConfig) -> str:
    """Everything known about the candidate, as one document."""
    parts: list[str] = []
    parts.extend(str(r) for r in (config.target_roles or []))
    parts.append(" ".join(str(s) for s in (config.skills or [])))

    profile = db.scalar(select(CareerProfile).where(CareerProfile.user_id == user_id))
    if profile is not None:
        parts.extend([profile.headline or "", profile.summary or ""])
        for exp in profile.experiences:
            parts.append(f"{exp.title} {exp.description}")
            parts.extend(str(h) for h in (exp.highlights or []))
            parts.append(" ".join(str(t) for t in (exp.tech_stack or [])))
        for project in profile.projects:
            parts.append(f"{project.name} {project.description}")
            parts.extend(str(h) for h in (project.highlights or []))
            parts.append(" ".join(str(t) for t in (project.tech_stack or [])))
        parts.extend(ps.skill.name for ps in profile.profile_skills if ps.skill is not None)

    resume = db.scalar(
        select(Resume)
        .where(Resume.user_id == user_id, Resume.deleted_at.is_(None), Resume.is_active.is_(True))
        .order_by(Resume.is_default.desc(), Resume.updated_at.desc())
        .limit(1)
    )
    if resume is not None:
        version = None
        if resume.current_version_id:
            version = db.get(ResumeVersion, resume.current_version_id)
        if version is None:
            version = db.scalar(
                select(ResumeVersion)
                .where(ResumeVersion.resume_id == resume.id)
                .order_by(ResumeVersion.version_number.desc())
                .limit(1)
            )
        if version is not None and version.extracted_text:
            parts.append(version.extracted_text[:12000])

    return "\n".join(p for p in parts if p and p.strip())


def profile_suggestions(db: Session, user_id: str) -> dict[str, Any]:
    """Values from the career profile and preferences, for the "import" button."""
    profile = db.scalar(select(CareerProfile).where(CareerProfile.user_id == user_id))
    prefs = db.scalar(select(JobPreference).where(JobPreference.user_id == user_id))
    skills: list[str] = []
    roles: list[str] = []
    years: float | None = None
    if profile is not None:
        years = profile.total_experience_years or None
        skills = [ps.skill.name for ps in profile.profile_skills if ps.skill is not None]
        roles = list(profile.preferred_roles or [])
    if prefs is not None:
        for role in prefs.target_roles or []:
            if role not in roles:
                roles.append(role)
    return {"experience_years": years, "skills": skills, "target_roles": roles}


# ---------------------------------------------------------------------------
# Assessment persistence
# ---------------------------------------------------------------------------
def _live_jobs_query(user_id: str):
    return select(Job).where(
        Job.user_id == user_id,
        Job.deleted_at.is_(None),
        Job.status != "archived",
    )


def _apply(row: HuntResult, a: Assessment, now: datetime) -> None:
    row.category = a.category
    row.section = a.section[:160]
    row.tier_name = a.tier_name[:120]
    row.tier_rank = a.tier_rank
    row.score = a.score
    row.strength = a.strength
    row.work_mode = a.work_mode
    row.remote_region = a.remote_region[:40]
    row.seniority = a.seniority
    row.experience_fit = a.experience_fit
    row.skill_overlap = a.skill_overlap
    row.matched_skills = a.matched_skills
    row.missing_skills = a.missing_skills
    row.semantic_score = a.semantic_score
    row.freshness_at = a.freshness_at
    row.freshness_basis = a.freshness_basis
    row.apply_link_type = a.apply_link_type
    row.apply_link_label = a.apply_link_label[:80]
    row.best_apply_url = a.best_apply_url[:1000]
    row.public_contact_email = a.public_contact_email[:320]
    row.reasons = a.reasons
    row.highlights = a.highlights
    row.warnings = a.warnings
    row.breakdown = a.breakdown
    row.explanation = a.explanation
    row.assessed_at = now


def assess_jobs(
    db: Session,
    user_id: str,
    *,
    config: HuntConfig | None = None,
    only_missing: bool = False,
    ai: Any = None,
) -> dict[str, Any]:
    """(Re)assess jobs and upsert their HuntResult rows.

    ``only_missing`` assesses just the jobs that have no result yet, which is
    what the board does lazily for jobs added by other paths (manual entry,
    the standalone discovery agent).
    """
    config = config or load_config(db, user_id)
    policy = db.scalar(select(JobPreference).where(JobPreference.user_id == user_id))
    now = _utcnow()

    existing = {
        r.job_id: r
        for r in db.scalars(select(HuntResult).where(HuntResult.user_id == user_id))
    }
    jobs = list(db.scalars(_live_jobs_query(user_id)))
    targets = [j for j in jobs if j.id not in existing] if only_missing else jobs
    if not targets:
        return {"assessed": 0, "semantic_mode": config.semantic_mode, "warnings": []}

    warnings: list[str] = []
    profile_text = build_profile_text(db, user_id, config)
    mode = config.semantic_mode or "local"
    if mode == "embeddings" and ai is None:
        from app.services.ai.client import AIService

        ai = AIService(db, user_id)
    scores, mode_used, semantic_warning = compute_semantic_scores(mode, profile_text, targets, ai=ai)
    if semantic_warning:
        warnings.append(semantic_warning)

    tally: Counter[str] = Counter()
    for job in targets:
        assessment = assess_job(job, config, policy=policy, semantic_score=scores.get(job.id), now=now)
        row = existing.get(job.id)
        if row is None:
            row = HuntResult(user_id=user_id, job_id=job.id)
            db.add(row)
        _apply(row, assessment, now)
        tally[assessment.category] += 1

    config.last_assessed_at = now
    db.flush()
    return {
        "assessed": len(targets),
        "apply_first": tally["apply_first"],
        "review": tally["review"],
        "not_match": tally["not_match"],
        "semantic_mode": mode_used,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def notify_new_matches(db: Session, user_id: str, config: HuntConfig) -> int:
    """Send one alert listing apply-first jobs not yet alerted on.

    Rows are marked notified even when no channel is configured, so enabling
    a channel later does not replay the whole history as one giant message.
    """
    rows = list(
        db.execute(
            select(HuntResult, Job)
            .join(Job, Job.id == HuntResult.job_id)
            .where(
                HuntResult.user_id == user_id,
                HuntResult.category == "apply_first",
                HuntResult.notified_at.is_(None),
                Job.deleted_at.is_(None),
            )
            .order_by(HuntResult.tier_rank.asc(), HuntResult.score.desc())
        ).all()
    )
    if not rows:
        return 0

    now = _utcnow()
    for result, _ in rows:
        result.notified_at = now
    # Sessions here do not autoflush; make the marks visible to later queries
    # in the same transaction so a job is never alerted on twice.
    db.flush()
    if not config.notify_new_matches:
        return 0

    from app.services.notifications.service import dispatch

    lines = []
    for result, job in rows[:MAX_ALERT_ITEMS]:
        link = result.best_apply_url or job.url
        lines.append(
            f"- {job.title} at {job.company or 'unknown company'} | {result.section} | "
            f"{result.score:.0f}/100" + (f"\n  {link}" if link else "")
        )
    more = len(rows) - MAX_ALERT_ITEMS
    if more > 0:
        lines.append(f"...and {more} more on the Job Hunt board.")
    dispatch(
        db,
        user_id,
        NotificationEventType.HIGH_MATCH_JOB.value,
        subject=f"Job Hunt: {len(rows)} new apply-first match{'es' if len(rows) != 1 else ''}",
        body="New jobs worth applying to first:\n\n" + "\n".join(lines),
        payload={"job_ids": [job.id for _, job in rows[:MAX_ALERT_ITEMS]], "count": len(rows)},
        dedupe_key=f"hunt:{now.strftime('%Y-%m-%dT%H')}",
    )
    return len(rows)


# ---------------------------------------------------------------------------
# The full run
# ---------------------------------------------------------------------------
def run_hunt(
    db: Session,
    user_id: str,
    *,
    discover_jobs: bool = True,
    actor: str = "job-hunt",
) -> dict[str, Any]:
    """Run the complete 3x Job Hunt pipeline. Returns a JSON-safe summary."""
    from app.services.discovery import discover
    from app.services.jobs import score_unscored

    config = load_config(db, user_id)
    started = _utcnow()
    summary: dict[str, Any] = {"started_at": started.isoformat(), "discovered": discover_jobs}

    if discover_jobs:
        queries = generate_queries(config)
        per_query_limit = max(1, min(int(config.results_per_query or 25), 200))
        sources_enabled = db.scalar(
            select(func.count())
            .select_from(JobSource)
            .where(
                JobSource.user_id == user_id,
                JobSource.enabled.is_(True),
                JobSource.deleted_at.is_(None),
            )
        ) or 0
        result = discover(
            db,
            user_id,
            limit_per_source=per_query_limit,
            queries=[q.to_source_query(per_query_limit) for q in queries],
            board_query=board_query(config, per_query_limit),
        )
        db.flush()
        scored = score_unscored(db, user_id, actor=actor)
        summary.update(
            {
                "queries": [q.label for q in queries],
                "sources_enabled": int(sources_enabled),
                "created": result.created,
                "updated": result.updated,
                "skipped": result.skipped,
                "scored": scored,
                "source_errors": result.errors,
            }
        )

    assessed = assess_jobs(db, user_id, config=config)
    summary.update(assessed)
    summary["alerted"] = notify_new_matches(db, user_id, config)

    finished = _utcnow()
    summary["finished_at"] = finished.isoformat()
    # Counts the agent registry reads to label the run: failing sources make
    # it "partial" (the rest of the hunt still worked), never silently green.
    summary["items_processed"] = int(summary.get("assessed", 0))
    summary["items_succeeded"] = int(summary.get("assessed", 0))
    summary["items_failed"] = len(summary.get("source_errors", []) or [])
    summary["detail"] = (
        f"{summary.get('apply_first', 0)} apply-first, {summary.get('review', 0)} to review"
        + (f", {summary.get('created', 0)} new jobs" if discover_jobs else "")
    )
    config.last_run_at = finished
    config.last_run_summary = dict(summary)
    db.flush()
    return summary


# ---------------------------------------------------------------------------
# Board and listing
# ---------------------------------------------------------------------------
def serialize_item(result: HuntResult, job: Job, now: datetime | None = None) -> dict[str, Any]:
    now = now or _utcnow()
    fresh_at = _aware(result.freshness_at)
    age = None if fresh_at is None else max(0.0, (now - fresh_at).total_seconds() / 3600.0)
    if age is None:
        freshness_label = "Posting date unknown"
    elif result.freshness_basis == "posted":
        freshness_label = f"Posted {humanize_age(age)} ago"
    elif result.freshness_basis == "updated":
        freshness_label = f"Updated {humanize_age(age)} ago"
    else:
        freshness_label = f"Found {humanize_age(age)} ago"

    return {
        "job_id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "source_name": job.source_name,
        "duplicate_sources": job.duplicate_sources or [],
        "job_status": job.status,
        "url": job.url,
        "salary_min_lpa": job.salary_min_lpa,
        "salary_max_lpa": job.salary_max_lpa,
        "currency": job.currency,
        "experience_min_years": job.experience_min_years,
        "experience_max_years": job.experience_max_years,
        "posted_at": job.posted_at,
        "source_updated_at": job.source_updated_at,
        "first_seen_at": job.first_seen_at,
        "category": result.category,
        "section": result.section,
        "tier_name": result.tier_name,
        "tier_rank": result.tier_rank,
        "score": result.score,
        "strength": result.strength,
        "work_mode": result.work_mode,
        "remote_region": result.remote_region,
        "seniority": result.seniority,
        "experience_fit": result.experience_fit,
        "skill_overlap": result.skill_overlap,
        "matched_skills": result.matched_skills or [],
        "missing_skills": result.missing_skills or [],
        "semantic_score": result.semantic_score,
        "freshness_at": result.freshness_at,
        "freshness_basis": result.freshness_basis,
        "freshness_hours": None if age is None else round(age, 1),
        "freshness_label": freshness_label,
        "apply_link_type": result.apply_link_type,
        "apply_link_label": result.apply_link_label,
        "best_apply_url": result.best_apply_url,
        "public_contact_email": result.public_contact_email,
        "reasons": result.reasons or [],
        "highlights": result.highlights or [],
        "warnings": result.warnings or [],
        "breakdown": result.breakdown or {},
        "explanation": result.explanation,
        "assessed_at": result.assessed_at,
    }


def _filtered(user_id: str, *, q: str | None, fresh_within_hours: int | None):
    stmt = (
        select(HuntResult, Job)
        .join(Job, Job.id == HuntResult.job_id)
        .where(
            HuntResult.user_id == user_id,
            Job.deleted_at.is_(None),
            Job.status != "archived",
        )
    )
    if q and q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Job.title.ilike(needle), Job.company.ilike(needle), Job.location.ilike(needle)))
    if fresh_within_hours:
        cutoff = _utcnow() - timedelta(hours=int(fresh_within_hours))
        stmt = stmt.where(HuntResult.freshness_at >= cutoff)
    return stmt


def build_board(
    db: Session,
    user_id: str,
    *,
    q: str | None = None,
    fresh_within_hours: int | None = None,
    limit_per_section: int = 30,
) -> dict[str, Any]:
    """The shortlist: stats, ordered sections, and a not-a-match summary."""
    config = load_config(db, user_id)
    # Jobs that arrived by another path (manual entry, the plain discovery
    # agent) get assessed on first view so the board is never silently stale.
    assess_jobs(db, user_id, config=config, only_missing=True)

    now = _utcnow()
    rows = list(db.execute(_filtered(user_id, q=q, fresh_within_hours=fresh_within_hours)).all())

    tier_order = {str(t.get("name")): i for i, t in enumerate(config.location_tiers or [])}
    sections: dict[str, dict[str, Any]] = {}
    not_match_reasons: Counter[str] = Counter()
    not_match = 0
    fresh_today = 0
    by_tier: Counter[str] = Counter()
    by_mode: Counter[str] = Counter()

    for result, job in rows:
        fresh_at = _aware(result.freshness_at)
        is_fresh = fresh_at is not None and (now - fresh_at) <= timedelta(hours=24)
        if result.category == "not_match":
            not_match += 1
            for reason in (result.reasons or [])[:1]:
                # Group "X is outside your location priorities" style reasons.
                key = "Outside your location priorities" if "outside your location" in reason else reason
                if key.startswith("Different job family"):
                    key = "Different job family"
                elif key.startswith("Asks for"):
                    key = "Pitched below your experience"
                elif key.startswith("Posted") and "window" in key:
                    key = "Older than your freshness window"
                elif key.startswith("Remote, but only for"):
                    key = "Remote outside your country"
                not_match_reasons[key] += 1
            continue

        if is_fresh:
            fresh_today += 1
        by_tier[result.tier_name] += 1
        by_mode[result.work_mode] += 1
        section = sections.get(result.section)
        if section is None:
            section = {
                "key": result.section,
                "label": result.section,
                "kind": result.category,
                "tier_rank": result.tier_rank if result.tier_rank is not None else 999,
                "count": 0,
                "items": [],
            }
            sections[result.section] = section
        section["count"] += 1
        section["tier_rank"] = min(section["tier_rank"], result.tier_rank if result.tier_rank is not None else 999)
        section["items"].append((result, job))

    ordered = sorted(
        sections.values(), key=lambda s: (CATEGORY_ORDER.get(s["kind"], 9), s["tier_rank"])
    )
    for section in ordered:
        section["items"].sort(
            key=lambda pair: (
                pair[0].tier_rank if pair[0].tier_rank is not None else 999,
                -(pair[0].score or 0),
            )
        )
        section["items"] = [serialize_item(r, j, now) for r, j in section["items"][:limit_per_section]]
        section.pop("tier_rank", None)

    apply_first = sum(s["count"] for s in ordered if s["kind"] == "apply_first")
    review = sum(s["count"] for s in ordered if s["kind"] == "review")
    sources_enabled = db.scalar(
        select(func.count())
        .select_from(JobSource)
        .where(JobSource.user_id == user_id, JobSource.enabled.is_(True), JobSource.deleted_at.is_(None))
    ) or 0

    return {
        "stats": {
            "total": len(rows),
            "fresh_today": fresh_today,
            "apply_first": apply_first,
            "review": review,
            "not_match": not_match,
            "remote": by_mode.get("remote", 0),
            "by_tier": [
                {"name": name, "count": count}
                for name, count in sorted(by_tier.items(), key=lambda kv: tier_order.get(kv[0], 999))
            ],
        },
        "sections": ordered,
        "not_match": {
            "count": not_match,
            "top_reasons": [{"reason": r, "count": c} for r, c in not_match_reasons.most_common(6)],
        },
        "last_run_at": config.last_run_at,
        "last_run_summary": config.last_run_summary or {},
        "last_assessed_at": config.last_assessed_at,
        "sources_enabled": int(sources_enabled),
    }


def list_results(
    db: Session,
    user_id: str,
    *,
    category: str | None = None,
    q: str | None = None,
    fresh_within_hours: int | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[dict[str, Any]], int]:
    stmt = _filtered(user_id, q=q, fresh_within_hours=fresh_within_hours)
    if category:
        stmt = stmt.where(HuntResult.category == category)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(HuntResult.score.desc()).offset((page - 1) * page_size).limit(page_size)
    now = _utcnow()
    return ([serialize_item(r, j, now) for r, j in db.execute(stmt).all()], int(total))


def job_assessment(db: Session, user_id: str, job: Job) -> dict[str, Any]:
    """One job's assessment, recomputed live, plus supporting resume evidence."""
    from app.services.ai.rag import retrieve_evidence

    config = load_config(db, user_id)
    row = db.scalar(select(HuntResult).where(HuntResult.user_id == user_id, HuntResult.job_id == job.id))
    if row is None:
        assess_jobs(db, user_id, config=config, only_missing=True)
        row = db.scalar(
            select(HuntResult).where(HuntResult.user_id == user_id, HuntResult.job_id == job.id)
        )
    item = serialize_item(row, job) if row is not None else None

    query = " ".join(
        [job.title, " ".join((row.matched_skills if row else []) or []), (job.description or "")[:800]]
    )
    evidence = [e.as_dict() for e in retrieve_evidence(db, user_id, query, limit=3)]
    return {"assessment": item, "evidence": evidence, "breakdown_max": breakdown_max(config)}


# ---------------------------------------------------------------------------
# Schedule (stored on the job_hunt agent so Automations and Hunt agree)
# ---------------------------------------------------------------------------
def get_schedule(db: Session, user_id: str) -> dict[str, Any]:
    from app.agents.registry import ensure_agent_definition, get_agent

    entry = get_agent(HUNT_AGENT_KEY)
    if entry is None:
        return {"schedule_enabled": False, "schedule_cron": "", "next_run_at": None}
    agent = ensure_agent_definition(db, user_id, entry[0])
    next_run = None
    if agent.enabled and agent.schedule_cron:
        try:
            from apscheduler.triggers.cron import CronTrigger

            from app.core.config import settings

            next_run = CronTrigger.from_crontab(
                agent.schedule_cron, timezone=settings.timezone or "UTC"
            ).get_next_fire_time(None, _utcnow())
        except (ValueError, TypeError):
            next_run = None
    return {
        "schedule_enabled": bool(agent.enabled),
        "schedule_cron": agent.schedule_cron,
        "next_run_at": next_run,
    }


def set_schedule(db: Session, user_id: str, *, enabled: bool | None, cron: str | None) -> None:
    from app.agents.registry import ensure_agent_definition, get_agent, sync_schedule

    entry = get_agent(HUNT_AGENT_KEY)
    if entry is None:
        return
    agent = ensure_agent_definition(db, user_id, entry[0])
    changed = False
    if cron is not None and cron != agent.schedule_cron:
        agent.schedule_cron = cron
        changed = True
    if enabled is not None and enabled != agent.enabled:
        agent.enabled = enabled
        changed = True
    if not changed:
        return
    sync_schedule(db, user_id, agent)
    db.flush()

    # The scheduler reconciles from its own session, which cannot see this
    # transaction's changes until they are committed, so wait for the commit.
    def _reconcile(_session: Session) -> None:
        try:
            from app.services.scheduler import scheduler

            if scheduler.running:
                scheduler.reconcile()
        except Exception:  # noqa: BLE001 - a scheduler hiccup must not fail a settings save
            logger.warning("Could not reconcile the scheduler after a hunt schedule change.")

    event.listen(db, "after_commit", _reconcile, once=True)


__all__ = [
    "assess_jobs",
    "build_board",
    "build_profile_text",
    "get_schedule",
    "job_assessment",
    "list_results",
    "notify_new_matches",
    "profile_suggestions",
    "run_hunt",
    "serialize_item",
    "set_schedule",
]

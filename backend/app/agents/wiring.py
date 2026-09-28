"""Connects the agent registry to the real service implementations.

The registry declares every agent up front (so the control center always has a
full list) with placeholders for the ones whose services live elsewhere. This
module replaces those placeholders once all services are importable, which
also keeps the registry free of circular imports.

Import this module at application startup, after the services exist.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.registry import AgentSpec, get_agent, register_agent
from app.db.models.enums import MatchDecision
from app.db.models.jobs import Job, JobMatch

logger = logging.getLogger(__name__)


def _spec(key: str) -> AgentSpec:
    entry = get_agent(key)
    if entry is None:
        raise LookupError(f"Agent {key!r} is not declared in the registry.")
    return entry[0]


def run_discovery(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """Pull from every enabled source, then score whatever arrived."""
    from app.services.discovery import discover
    from app.services.jobs import score_unscored

    limit = int(config.get("limit_per_source", 50))
    result = discover(db, user_id, limit_per_source=limit)
    db.flush()
    scored = score_unscored(db, user_id, actor="discovery-agent")

    return {
        "items_processed": result.total_seen,
        "items_succeeded": result.created + result.updated,
        "items_failed": len(result.errors),
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
        "scored": scored,
        "errors": result.errors,
        "per_source": result.per_source,
    }


def run_matching(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """Re-score every job, e.g. after preferences or rules changed."""
    from app.services.jobs import rescore_all

    tally = rescore_all(db, user_id, actor="matching-agent")
    return {
        "items_processed": tally["rescored"],
        "items_succeeded": tally["rescored"],
        "items_failed": 0,
        **tally,
    }


def run_qualification(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """Score only jobs that have never been scored."""
    from app.services.jobs import score_unscored

    scored = score_unscored(db, user_id, actor="qualification-agent")
    return {"items_processed": scored, "items_succeeded": scored, "items_failed": 0}


def run_normalization(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """Backfill derived fields and extracted skills on existing jobs."""
    from app.services.jobs import extract_and_store_skills, prepare_job_fields

    jobs = db.execute(
        select(Job).where(Job.user_id == user_id, Job.deleted_at.is_(None))
    ).scalars().all()

    touched = 0
    for job in jobs:
        needs_fields = not job.company_normalized or not job.description_hash
        needs_skills = not job.skills
        if not (needs_fields or needs_skills):
            continue
        if needs_fields:
            prepare_job_fields(job)
        if needs_skills:
            extract_and_store_skills(db, job)
        touched += 1

    return {"items_processed": len(jobs), "items_succeeded": touched, "items_failed": 0}


def run_deduplication(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """Re-check stored jobs for duplicates that slipped through at ingest."""
    from app.services.dedupe import compute_dedupe_key

    jobs = db.execute(
        select(Job).where(Job.user_id == user_id, Job.deleted_at.is_(None))
    ).scalars().all()

    seen: dict[str, Job] = {}
    merged = 0
    for job in sorted(jobs, key=lambda j: j.created_at):
        key = job.dedupe_key or compute_dedupe_key(job, job.source_name)
        if not job.dedupe_key:
            job.dedupe_key = key

        primary = seen.get(key)
        if primary is None:
            seen[key] = job
            continue

        # Keep the earliest row as canonical and point the later one at it.
        if job.canonical_job_id != primary.id:
            job.canonical_job_id = primary.id
            primary.seen_count += 1
            sources = list(primary.duplicate_sources or [])
            if job.source_name and job.source_name not in sources:
                sources.append(job.source_name)
                primary.duplicate_sources = sources
            merged += 1

    return {"items_processed": len(jobs), "items_succeeded": merged, "items_failed": 0,
            "duplicates_linked": merged}


def run_application_preparation(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """Prepare every approved application that has not been prepared yet."""
    from app.db.models.applications import Application
    from app.db.models.enums import ApplicationStatus
    from app.db.models.identity import CareerProfile
    from app.services.ai.client import AIService
    from app.services.applications import prepare

    profile = db.execute(
        select(CareerProfile).where(CareerProfile.user_id == user_id)
    ).scalar_one_or_none()
    ai = AIService(db, user_id)

    pending = db.execute(
        select(Application).where(
            Application.user_id == user_id,
            Application.status == ApplicationStatus.APPROVED,
        )
    ).scalars().all()

    succeeded = 0
    failed = 0
    for application in pending:
        job = db.get(Job, application.job_id)
        if job is None:
            failed += 1
            continue
        try:
            prepare(db, application, job, profile=profile, ai_service=ai, actor="preparation-agent")
            succeeded += 1
        except Exception as exc:
            logger.info("Preparation failed for application %s: %s", application.id, exc)
            failed += 1

    return {"items_processed": len(pending), "items_succeeded": succeeded, "items_failed": failed}


def run_resume_recommendation(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """Refresh the recommended resume on every current match."""
    from app.services.jobs import load_resumes
    from app.services.matching import recommend_resume

    resumes = load_resumes(db, user_id)
    if not resumes:
        return {"items_processed": 0, "items_succeeded": 0, "items_failed": 0,
                "note": "No active resumes to recommend."}

    matches = db.execute(
        select(JobMatch, Job)
        .join(Job, JobMatch.job_id == Job.id)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.is_current.is_(True),
            JobMatch.decision != MatchDecision.REJECT,
        )
    ).all()

    updated = 0
    for match, job in matches:
        resume_id, reason = recommend_resume(job, resumes, None)
        if resume_id and match.recommended_resume_id != resume_id:
            match.recommended_resume_id = resume_id
            match.recommendation_reason = reason
            updated += 1

    return {"items_processed": len(matches), "items_succeeded": updated, "items_failed": 0}


def run_auto_apply(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """Send prepared email-lane applications, inside the user's daily cap.

    This is the only agent that acts on the outside world on the user's behalf,
    so it is deliberately narrow:

    * it will not act at all while ``approval_required`` is set, because an
      unapproved application is not one the user has agreed to send;
    * it only touches applications already ``approved`` or ``prepared``;
    * it only sends through the email lane, to an address the employer
      published -- every other lane raises a policy error by design;
    * it stops the moment the daily cap is reached.
    """
    from app.db.models.applications import Application
    from app.db.models.enums import ApplicationChannel, ApplicationStatus
    from app.db.models.identity import CareerProfile
    from app.services.applications import cap_status, submit
    from app.services.jobs import load_preferences
    from app.services.submission import can_auto_submit

    prefs = load_preferences(db, user_id)

    if not prefs.auto_submit_enabled:
        return {
            "items_processed": 0, "items_succeeded": 0, "items_failed": 0,
            "skipped_reason": "Auto-submit is switched off in preferences.",
        }
    if prefs.approval_required:
        return {
            "items_processed": 0, "items_succeeded": 0, "items_failed": 0,
            "skipped_reason": (
                "Approval is required before submission, so nothing is sent "
                "automatically. Turn that off to let this agent send."
            ),
        }

    cap = cap_status(db, user_id, prefs)
    remaining = cap["cap"] - cap["used_today"]
    if remaining <= 0:
        return {
            "items_processed": 0, "items_succeeded": 0, "items_failed": 0,
            "skipped_reason": f"The daily cap of {cap['cap']} is already used.",
        }

    profile = db.execute(
        select(CareerProfile).where(CareerProfile.user_id == user_id)
    ).scalar_one_or_none()

    candidates = db.execute(
        select(Application)
        .where(
            Application.user_id == user_id,
            Application.channel == ApplicationChannel.EMAIL,
            Application.status.in_([ApplicationStatus.APPROVED, ApplicationStatus.PREPARED]),
        )
        .order_by(Application.match_score.desc().nullslast())
    ).scalars().all()

    sent = 0
    failed = 0
    skipped: list[dict[str, str]] = []

    for application in candidates:
        if sent >= remaining:
            break
        job = db.get(Job, application.job_id)
        if job is None:
            failed += 1
            continue

        eligible, reason = can_auto_submit(job, application)
        if not eligible:
            skipped.append({"application_id": application.id, "reason": reason})
            continue

        try:
            submit(db, application, job, prefs, actor="auto-apply-agent", profile=profile)
            sent += 1
        except Exception as exc:
            logger.info("Auto-apply failed for application %s: %s", application.id, exc)
            failed += 1

    return {
        "items_processed": len(candidates),
        "items_succeeded": sent,
        "items_failed": failed,
        "sent": sent,
        "skipped": skipped[:20],
        "cap_remaining_after": max(0, remaining - sent),
    }


def run_learning(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """Summarise the funnel. Analytics suggest; they never mutate settings."""
    from app.services.analytics import build_analytics

    stats = build_analytics(db, user_id, days=int(config.get("days", 30)))
    return {
        "items_processed": stats.get("jobs_discovered", 0),
        "items_succeeded": stats.get("jobs_discovered", 0),
        "items_failed": 0,
        "analytics": {
            k: stats.get(k)
            for k in (
                "jobs_discovered", "jobs_qualified", "average_match_score",
                "applications_submitted", "interview_rate", "response_rate",
            )
        },
    }


def run_job_hunt(db: Session, user_id: str, config: dict) -> dict[str, Any]:
    """The 3x Job Hunt: multi-query discovery, then rank and categorise."""
    from app.services.hunt.pipeline import run_hunt

    return run_hunt(
        db, user_id, discover_jobs=bool(config.get("discover", True)), actor="job-hunt-agent"
    )


def _not_wired(name: str, reason: str):
    def _run(db: Session, user_id: str, config: dict) -> dict[str, Any]:
        raise NotImplementedError(reason)

    _run.__name__ = f"run_{name}"
    return _run


def wire_agents() -> None:
    """Replace registry placeholders with the real implementations."""
    wiring = {
        "discovery": run_discovery,
        "normalization": run_normalization,
        "deduplication": run_deduplication,
        "qualification": run_qualification,
        "matching": run_matching,
        "resume_recommendation": run_resume_recommendation,
        "application_preparation": run_application_preparation,
        "auto_apply": run_auto_apply,
        "learning": run_learning,
        "job_hunt": run_job_hunt,
        # These two run on demand from their own endpoints rather than on a
        # schedule, because both need a specific job or resume as input.
        "resume_tailoring": _not_wired(
            "resume_tailoring",
            "Resume tailoring runs per job from the Resumes screen, not on a schedule.",
        ),
        "answer": _not_wired(
            "answer",
            "Answer drafting runs per question from the Answer Bank, not on a schedule.",
        ),
    }

    for key, fn in wiring.items():
        try:
            register_agent(_spec(key), fn)
        except LookupError:
            logger.warning("Agent %r is not declared in the registry; skipping wiring.", key)

"""Dashboard and analytics aggregation (spec sections 3.1 and 26).

Analytics describe the funnel. They never change configuration on their own --
suggestions surface in the UI for the user to accept.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.applications import Application, FollowUp
from app.db.models.automation import AgentRun, AIUsage
from app.db.models.enums import ApplicationStatus, JobStatus, MatchDecision, SourceHealth
from app.db.models.jobs import Job, JobMatch, JobSkill, JobSource
from app.db.models.preferences import JobPreference
from app.db.models.resumes import Resume, ResumeVersion
from app.services import audit


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _start_of_today() -> datetime:
    return datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)


def _count(db: Session, stmt) -> int:
    return int(db.execute(stmt).scalar() or 0)


def build_dashboard(db: Session, user_id: str, prefs: JobPreference) -> dict[str, Any]:
    """Every overview widget in one query pass."""
    job_base = (Job.user_id == user_id, Job.deleted_at.is_(None))

    decision_counts = dict(
        db.execute(
            select(JobMatch.decision, func.count(JobMatch.id))
            .join(Job, JobMatch.job_id == Job.id)
            .where(JobMatch.user_id == user_id, JobMatch.is_current.is_(True), *job_base)
            .group_by(JobMatch.decision)
        ).all()
    )

    status_counts = dict(
        db.execute(
            select(Application.status, func.count(Application.id))
            .where(Application.user_id == user_id)
            .group_by(Application.status)
        ).all()
    )

    counts = {
        "total_jobs": _count(db, select(func.count(Job.id)).where(*job_base)),
        "new_jobs": _count(
            db, select(func.count(Job.id)).where(*job_base, Job.status == JobStatus.NEW)
        ),
        "high_match": int(decision_counts.get(MatchDecision.HIGH_PRIORITY, 0)),
        "review": int(decision_counts.get(MatchDecision.REVIEW, 0)),
        "rejected": int(decision_counts.get(MatchDecision.REJECT, 0)),
        "pending_approval": int(status_counts.get(ApplicationStatus.PENDING_REVIEW, 0)),
        "application_ready": int(status_counts.get(ApplicationStatus.PREPARED, 0))
        + int(status_counts.get(ApplicationStatus.APPROVED, 0)),
        "submitted": int(status_counts.get(ApplicationStatus.SUBMITTED, 0)),
        "interviews": int(status_counts.get(ApplicationStatus.INTERVIEW, 0)),
        "offers": int(status_counts.get(ApplicationStatus.OFFER, 0)),
        "followups_due": _count(
            db,
            select(func.count(FollowUp.id)).where(
                FollowUp.user_id == user_id,
                FollowUp.completed_at.is_(None),
                FollowUp.due_date <= date.today(),
            ),
        ),
    }

    last_run = db.execute(
        select(AgentRun)
        .where(AgentRun.user_id == user_id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    ).scalars().first()

    next_run_at = None
    try:
        from app.services.scheduler import scheduler

        next_run_at = scheduler.next_run_for(user_id, "discovery")
    except Exception:
        next_run_at = None

    sources = db.execute(
        select(JobSource).where(JobSource.user_id == user_id, JobSource.deleted_at.is_(None))
    ).scalars().all()

    today_start = _start_of_today()
    requests_today = _count(
        db,
        select(func.count(AIUsage.id)).where(
            AIUsage.user_id == user_id, AIUsage.created_at >= today_start
        ),
    )
    tokens_today = _count(
        db,
        select(func.coalesce(func.sum(AIUsage.total_tokens), 0)).where(
            AIUsage.user_id == user_id, AIUsage.created_at >= today_start
        ),
    )
    cost_today = float(
        db.execute(
            select(func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0.0)).where(
                AIUsage.user_id == user_id, AIUsage.created_at >= today_start
            )
        ).scalar()
        or 0.0
    )
    month_start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    cost_month = float(
        db.execute(
            select(func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0.0)).where(
                AIUsage.user_id == user_id, AIUsage.created_at >= month_start
            )
        ).scalar()
        or 0.0
    )
    budget = float(settings.ai_monthly_budget_usd or 0.0)

    submitted_today = _count(
        db,
        select(func.count(Application.id)).where(
            Application.user_id == user_id,
            Application.submitted_at.is_not(None),
            Application.submitted_at >= today_start,
        ),
    )
    cap = int(prefs.daily_application_cap or 0)

    top_jobs = db.execute(
        select(Job, JobMatch)
        .join(JobMatch, (JobMatch.job_id == Job.id) & (JobMatch.is_current.is_(True)))
        .where(*job_base, JobMatch.decision != MatchDecision.REJECT)
        .order_by(JobMatch.score.desc())
        .limit(5)
    ).all()

    return {
        "counts": counts,
        "daily_run": {
            "last_run_at": last_run.finished_at or last_run.created_at if last_run else None,
            "status": last_run.status if last_run else "",
            "next_run_at": next_run_at,
            "scheduler_enabled": settings.scheduler_enabled,
        },
        "integration_health": [
            {
                "id": s.id,
                "name": s.name,
                "adapter_type": s.adapter_type,
                "health": s.health or SourceHealth.UNKNOWN,
                "enabled": s.enabled,
                "last_success_at": s.last_success_at,
                "last_error": s.last_error,
            }
            for s in sources
        ],
        "ai_usage": {
            "requests_today": requests_today,
            "tokens_today": tokens_today,
            "estimated_cost_today_usd": round(cost_today, 4),
            "estimated_cost_month_usd": round(cost_month, 4),
            "budget_usd": budget,
            "budget_exhausted": bool(budget) and cost_month >= budget,
        },
        "recent_activity": [
            {
                "created_at": entry.created_at,
                "action": entry.action,
                "summary": entry.summary,
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "success": entry.success,
            }
            for entry in audit.recent(db, user_id, limit=15)
        ],
        "application_cap": {
            "used_today": submitted_today,
            "cap": cap,
            "remaining": max(0, cap - submitted_today) if cap else 0,
        },
        "top_jobs": [
            {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "score": match.score,
                "decision": match.decision,
            }
            for job, match in top_jobs
        ],
    }


def build_analytics(db: Session, user_id: str, days: int = 30) -> dict[str, Any]:
    """Funnel metrics over a trailing window."""
    since = _now() - timedelta(days=days)
    job_base = (Job.user_id == user_id, Job.deleted_at.is_(None), Job.created_at >= since)

    jobs_discovered = _count(db, select(func.count(Job.id)).where(*job_base))
    jobs_qualified = _count(
        db,
        select(func.count(JobMatch.id))
        .join(Job, JobMatch.job_id == Job.id)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.is_current.is_(True),
            JobMatch.decision != MatchDecision.REJECT,
            *job_base,
        ),
    )
    average_score = float(
        db.execute(
            select(func.coalesce(func.avg(JobMatch.score), 0.0))
            .join(Job, JobMatch.job_id == Job.id)
            .where(JobMatch.user_id == user_id, JobMatch.is_current.is_(True), *job_base)
        ).scalar()
        or 0.0
    )

    applications = db.execute(
        select(Application).where(
            Application.user_id == user_id, Application.created_at >= since
        )
    ).scalars().all()

    submitted = [a for a in applications if a.submitted_at is not None]
    interviewed = [
        a
        for a in applications
        if a.status in (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER)
    ]
    responded = [
        a
        for a in applications
        if a.status
        in (
            ApplicationStatus.INTERVIEW,
            ApplicationStatus.OFFER,
            ApplicationStatus.REJECTED,
            ApplicationStatus.CLOSED,
        )
        and a.submitted_at is not None
    ]

    per_week: Counter[str] = Counter()
    for application in submitted:
        moment = application.submitted_at
        if moment is None:
            continue
        iso = moment.isocalendar()
        per_week[f"{iso[0]}-W{iso[1]:02d}"] += 1

    skill_rows = db.execute(
        select(JobSkill.skill_name, func.count(JobSkill.id))
        .join(Job, JobSkill.job_id == Job.id)
        .where(*job_base)
        .group_by(JobSkill.skill_name)
        .order_by(func.count(JobSkill.id).desc())
        .limit(15)
    ).all()

    source_rows = db.execute(
        select(
            Job.source_name,
            func.count(Job.id),
            func.sum(
                case(
                    (JobMatch.decision != MatchDecision.REJECT, 1),
                    else_=0,
                ).cast(Integer)
            ),
        )
        .outerjoin(JobMatch, (JobMatch.job_id == Job.id) & (JobMatch.is_current.is_(True)))
        .where(*job_base)
        .group_by(Job.source_name)
    ).all()

    rejection_counter: Counter[str] = Counter()
    for match in db.execute(
        select(JobMatch)
        .join(Job, JobMatch.job_id == Job.id)
        .where(
            JobMatch.user_id == user_id,
            JobMatch.is_current.is_(True),
            JobMatch.decision == MatchDecision.REJECT,
            *job_base,
        )
    ).scalars().all():
        for reason in match.hard_fail_reasons or ["Scored below the review threshold"]:
            # Group by the leading clause so near-identical reasons collapse.
            rejection_counter[str(reason).split(":")[0].strip()[:80]] += 1

    resume_rows = db.execute(
        select(Resume.name, func.count(Application.id))
        .join(ResumeVersion, ResumeVersion.resume_id == Resume.id)
        .join(Application, Application.resume_version_id == ResumeVersion.id)
        .where(Resume.user_id == user_id)
        .group_by(Resume.name)
    ).all()

    response_times = [
        (a.closed_at - a.submitted_at).days
        for a in responded
        if a.closed_at and a.submitted_at
    ]

    return {
        "days": days,
        "jobs_discovered": jobs_discovered,
        "jobs_qualified": jobs_qualified,
        "average_match_score": round(average_score, 1),
        "applications_submitted": len(submitted),
        "applications_per_week": [
            {"week": week, "count": count} for week, count in sorted(per_week.items())
        ],
        "interview_rate": round(len(interviewed) / len(submitted) * 100, 1) if submitted else 0.0,
        "response_rate": round(len(responded) / len(submitted) * 100, 1) if submitted else 0.0,
        "top_skills_requested": [
            {"skill": name, "count": int(count)} for name, count in skill_rows
        ],
        "source_conversion": [
            {
                "source": name or "unknown",
                "jobs": int(total or 0),
                "qualified": int(qualified or 0),
                "rate": round((int(qualified or 0) / int(total)) * 100, 1) if total else 0.0,
            }
            for name, total, qualified in source_rows
        ],
        "rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in rejection_counter.most_common(10)
        ],
        "resume_performance": [
            {"resume": name, "applications": int(count)} for name, count in resume_rows
        ],
        "average_days_to_response": (
            round(sum(response_times) / len(response_times), 1) if response_times else None
        ),
    }

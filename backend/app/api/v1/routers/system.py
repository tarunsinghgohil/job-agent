"""Dashboard, analytics, AI status, audit log, settings, and data export."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import Context, CurrentPreferences, DbSession
from app.core.errors import NotFoundError
from app.db.models.applications import AnswerBankEntry, Application
from app.db.models.identity import CareerProfile
from app.db.models.jobs import Job, JobMatch, JobSource
from app.db.models.ops import AuditLog, SystemSetting
from app.db.models.preferences import JobPreference, MatchRule
from app.db.models.resumes import Resume
from app.schemas.common import Page
from app.schemas.ops import (
    AIStatusOut,
    AIUsageOut,
    AnalyticsOut,
    AuditLogOut,
    DashboardOut,
    SystemSettingIn,
    SystemSettingOut,
)
from app.services import audit
from app.services.ai.client import AIService
from app.services.analytics import build_analytics, build_dashboard

router = APIRouter(tags=["system"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: DbSession, ctx: Context, prefs: CurrentPreferences) -> DashboardOut:
    return DashboardOut(**build_dashboard(db, ctx.user_id, prefs))


@router.get("/analytics", response_model=AnalyticsOut)
def analytics(
    db: DbSession, ctx: Context, days: int = Query(default=30, ge=1, le=365)
) -> AnalyticsOut:
    return AnalyticsOut(**build_analytics(db, ctx.user_id, days=days))


@router.get("/ai/status", response_model=AIStatusOut)
def ai_status(db: DbSession, ctx: Context) -> AIStatusOut:
    ai = AIService(db, ctx.user_id)
    budget = ai.budget_status()
    return AIStatusOut(
        enabled=ai.enabled,
        model=settings.openai_model if ai.enabled else None,
        embedding_model=settings.openai_embedding_model if ai.enabled else None,
        budget_usd=budget["budget_usd"],
        spent_this_month_usd=budget["spent_this_month_usd"],
        remaining_usd=budget["remaining_usd"],
        exhausted=budget["exhausted"],
    )


@router.get("/ai/usage")
def ai_usage(
    db: DbSession, ctx: Context, days: int = Query(default=30, ge=1, le=365)
) -> dict[str, Any]:
    ai = AIService(db, ctx.user_id)
    summary = ai.usage_summary(days=days)

    from app.db.models.automation import AIUsage

    by_function = db.execute(
        select(
            AIUsage.function,
            func.count(AIUsage.id),
            func.coalesce(func.sum(AIUsage.total_tokens), 0),
            func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0.0),
        )
        .where(AIUsage.user_id == ctx.user_id)
        .group_by(AIUsage.function)
        .order_by(func.coalesce(func.sum(AIUsage.estimated_cost_usd), 0.0).desc())
    ).all()

    return {
        **summary,
        **ai.budget_status(),
        "by_function": [
            {
                "function": name,
                "requests": int(count),
                "tokens": int(tokens),
                "estimated_cost_usd": round(float(cost), 4),
            }
            for name, count, tokens, cost in by_function
        ],
    }


@router.get("/audit", response_model=Page[AuditLogOut])
def audit_log(
    db: DbSession,
    ctx: Context,
    action: str | None = None,
    entity_type: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Page[AuditLogOut]:
    stmt = select(AuditLog).where(AuditLog.user_id == ctx.user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    return Page.build(
        [AuditLogOut.model_validate(r) for r in rows], total, page, page_size
    )


@router.get("/system/settings", response_model=list[SystemSettingOut])
def list_settings(db: DbSession, ctx: Context) -> list[SystemSettingOut]:
    rows = db.execute(
        select(SystemSetting).where(SystemSetting.user_id == ctx.user_id).order_by(SystemSetting.key)
    ).scalars().all()
    return [SystemSettingOut.model_validate(r) for r in rows]


@router.put("/system/settings/{key}", response_model=SystemSettingOut)
def put_setting(
    key: str, payload: SystemSettingIn, db: DbSession, ctx: Context
) -> SystemSettingOut:
    row = db.execute(
        select(SystemSetting).where(
            SystemSetting.user_id == ctx.user_id, SystemSetting.key == key
        )
    ).scalar_one_or_none()
    if row is None:
        row = SystemSetting(user_id=ctx.user_id, key=key)
        db.add(row)

    row.value = payload.value
    row.description = payload.description or row.description
    db.flush()

    audit.record(
        db, action="system.setting.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="system_setting", entity_id=row.id, summary=f"Set {key}",
    )
    return SystemSettingOut.model_validate(row)


@router.get("/system/export")
def export_data(db: DbSession, ctx: Context) -> dict[str, Any]:
    """Full JSON export of the user's own data (spec section 28).

    Credentials are deliberately excluded: an export is not a way to extract
    secrets in plaintext.
    """

    def rows_of(model: Any, *filters: Any) -> list[dict[str, Any]]:
        stmt = select(model).where(*filters)
        return [
            {
                c.name: getattr(row, c.name)
                for c in model.__table__.columns
                if c.name not in ("embedding", "ciphertext", "password_hash")
            }
            for row in db.execute(stmt).scalars().all()
        ]

    profile = db.execute(
        select(CareerProfile).where(CareerProfile.user_id == ctx.user_id)
    ).scalar_one_or_none()

    export = {
        "exported_at": func.now(),
        "user": {"id": ctx.user_id, "email": ctx.user.email, "full_name": ctx.user.full_name},
        "profile": (
            {
                c.name: getattr(profile, c.name)
                for c in CareerProfile.__table__.columns
            }
            if profile
            else None
        ),
        "preferences": rows_of(JobPreference, JobPreference.user_id == ctx.user_id),
        "rules": rows_of(MatchRule, MatchRule.user_id == ctx.user_id),
        "sources": rows_of(JobSource, JobSource.user_id == ctx.user_id),
        "jobs": rows_of(Job, Job.user_id == ctx.user_id),
        "matches": rows_of(JobMatch, JobMatch.user_id == ctx.user_id),
        "applications": rows_of(Application, Application.user_id == ctx.user_id),
        "answers": rows_of(AnswerBankEntry, AnswerBankEntry.user_id == ctx.user_id),
        "resumes": rows_of(Resume, Resume.user_id == ctx.user_id),
        "note": "Credentials are excluded from exports by design.",
    }

    audit.record(
        db, action="system.export", user_id=ctx.user_id, actor=ctx.actor,
        summary="Exported all account data",
    )
    return export

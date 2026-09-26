"""Notifications, integrations, automation, dashboard, and analytics schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, TimestampedModel


# --------------------------------------------------------------------------
# Notifications
# --------------------------------------------------------------------------
class NotificationChannelIn(BaseModel):
    enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)
    credential: str | None = None  # write-only; stored encrypted


class NotificationChannelOut(TimestampedModel):
    id: str
    channel_type: str
    display_name: str = ""
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    has_credential: bool = False
    requires_credential: bool = False
    config_schema: list[dict[str, Any]] = Field(default_factory=list)
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    last_error: str = ""


class NotificationPreferencesIn(BaseModel):
    event_routing: dict[str, list[str]] = Field(default_factory=dict)
    quiet_hours_start: str = ""
    quiet_hours_end: str = ""
    timezone: str = "Asia/Kolkata"
    daily_digest_enabled: bool = True
    daily_digest_time: str = "09:00"
    weekly_summary_enabled: bool = True
    instant_alerts_enabled: bool = True
    failures_only: bool = False


class NotificationPreferencesOut(NotificationPreferencesIn, TimestampedModel):
    id: str


class NotificationEventOut(ORMModel):
    id: str
    event_type: str
    channel_type: str
    subject: str
    body: str
    status: str
    error: str
    sent_at: datetime | None = None
    attempts: int
    created_at: datetime


# --------------------------------------------------------------------------
# Integrations / secrets
# --------------------------------------------------------------------------
class IntegrationOut(BaseModel):
    key: str
    label: str
    provider: str = ""
    connected: bool = False
    masked_value: str = ""
    source: str = "none"  # "database" | "environment" | "none"
    last_tested_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_error: str = ""
    rotated_at: datetime | None = None


class IntegrationIn(BaseModel):
    value: str = Field(min_length=1)
    label: str = ""


# --------------------------------------------------------------------------
# Automation
# --------------------------------------------------------------------------
class AgentIn(BaseModel):
    enabled: bool | None = None
    schedule_cron: str | None = None
    config: dict[str, Any] | None = None
    max_retries: int | None = Field(default=None, ge=0, le=10)


class AgentOut(TimestampedModel):
    id: str
    key: str
    name: str
    description: str
    enabled: bool
    schedule_cron: str
    config: dict[str, Any] = Field(default_factory=dict)
    max_retries: int
    last_run_at: datetime | None = None
    last_status: str = ""
    next_run_at: datetime | None = None


class AgentRunStepOut(ORMModel):
    id: str
    sequence: int
    name: str
    status: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None


class AgentRunOut(ORMModel):
    id: str
    agent_key: str
    trigger: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    items_processed: int
    items_succeeded: int
    items_failed: int
    retry_count: int
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_at: datetime


class AgentRunDetailOut(AgentRunOut):
    steps: list[AgentRunStepOut] = Field(default_factory=list)


class ScheduleIn(BaseModel):
    cron: str | None = None
    enabled: bool | None = None
    timezone: str | None = None
    description: str | None = None


class ScheduleOut(TimestampedModel):
    id: str
    key: str
    description: str
    cron: str
    timezone: str
    enabled: bool
    agent_key: str
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_status: str = ""


# --------------------------------------------------------------------------
# Dashboard and analytics
# --------------------------------------------------------------------------
class DashboardCounts(BaseModel):
    new_jobs: int = 0
    high_match: int = 0
    review: int = 0
    rejected: int = 0
    application_ready: int = 0
    pending_approval: int = 0
    submitted: int = 0
    interviews: int = 0
    offers: int = 0
    followups_due: int = 0
    total_jobs: int = 0


class IntegrationHealthOut(BaseModel):
    id: str
    name: str
    adapter_type: str
    health: str
    enabled: bool
    last_success_at: datetime | None = None
    last_error: str = ""


class AIUsageOut(BaseModel):
    requests_today: int = 0
    tokens_today: int = 0
    estimated_cost_today_usd: float = 0.0
    estimated_cost_month_usd: float = 0.0
    budget_usd: float = 0.0
    budget_exhausted: bool = False


class ActivityOut(BaseModel):
    created_at: datetime
    action: str
    summary: str
    entity_type: str = ""
    entity_id: str = ""
    success: bool = True


class DailyRunOut(BaseModel):
    last_run_at: datetime | None = None
    status: str = ""
    next_run_at: datetime | None = None
    scheduler_enabled: bool = False


class ApplicationCapOut(BaseModel):
    used_today: int = 0
    cap: int = 0
    remaining: int = 0


class DashboardOut(BaseModel):
    counts: DashboardCounts
    daily_run: DailyRunOut
    integration_health: list[IntegrationHealthOut] = Field(default_factory=list)
    ai_usage: AIUsageOut
    recent_activity: list[ActivityOut] = Field(default_factory=list)
    application_cap: ApplicationCapOut
    top_jobs: list[dict[str, Any]] = Field(default_factory=list)


class AnalyticsOut(BaseModel):
    days: int
    jobs_discovered: int = 0
    jobs_qualified: int = 0
    average_match_score: float = 0.0
    applications_submitted: int = 0
    applications_per_week: list[dict[str, Any]] = Field(default_factory=list)
    interview_rate: float = 0.0
    response_rate: float = 0.0
    top_skills_requested: list[dict[str, Any]] = Field(default_factory=list)
    source_conversion: list[dict[str, Any]] = Field(default_factory=list)
    rejection_reasons: list[dict[str, Any]] = Field(default_factory=list)
    resume_performance: list[dict[str, Any]] = Field(default_factory=list)
    average_days_to_response: float | None = None


class AuditLogOut(ORMModel):
    id: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    summary: str
    ip_address: str
    success: bool
    created_at: datetime


class SystemSettingIn(BaseModel):
    value: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class SystemSettingOut(TimestampedModel):
    id: str
    key: str
    value: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class AIStatusOut(BaseModel):
    enabled: bool
    model: str | None = None
    embedding_model: str | None = None
    budget_usd: float = 0.0
    spent_this_month_usd: float = 0.0
    remaining_usd: float | None = None
    exhausted: bool = False


class HealthOut(BaseModel):
    status: str
    version: str
    environment: str

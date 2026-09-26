"""Job source, job, and match schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, TimestampedModel


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
class AdapterDescriptor(BaseModel):
    adapter_type: str
    display_name: str
    requires_credential: bool
    config_schema: list[dict[str, Any]] = Field(default_factory=list)


class JobSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    adapter_type: str
    base_url: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    schedule_cron: str = ""
    query_templates: list[str] = Field(default_factory=list)
    rate_limit_per_hour: int = Field(default=60, ge=1, le=100000)
    source_rules: dict[str, Any] = Field(default_factory=dict)
    # Write-only: stored encrypted, never returned.
    credential: str | None = None


class JobSourceOut(TimestampedModel):
    id: str
    name: str
    adapter_type: str
    base_url: str
    config: dict[str, Any]
    enabled: bool
    priority: int
    schedule_cron: str
    query_templates: list[str]
    rate_limit_per_hour: int
    source_rules: dict[str, Any]
    health: str
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: str
    consecutive_failures: int
    has_credential: bool = False


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
class JobIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(default="", max_length=200)
    location: str = ""
    is_remote: bool = False
    url: str = ""
    apply_url: str = ""
    application_email: str = ""
    description: str = ""
    salary_min_lpa: float | None = Field(default=None, ge=0, le=1000)
    salary_max_lpa: float | None = Field(default=None, ge=0, le=1000)
    salary_raw: str = ""
    currency: str = "INR"
    employment_type: str = "full_time"
    industry: str = ""
    experience_min_years: float | None = Field(default=None, ge=0, le=60)
    experience_max_years: float | None = Field(default=None, ge=0, le=60)
    posted_at: datetime | None = None
    source_name: str = "manual"


class JobPatch(BaseModel):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    is_remote: bool | None = None
    url: str | None = None
    description: str | None = None
    salary_min_lpa: float | None = None
    salary_max_lpa: float | None = None
    employment_type: str | None = None
    industry: str | None = None
    status: str | None = None


class JobSkillOut(ORMModel):
    skill_name: str
    skill_slug: str
    is_required: bool
    source: str
    confidence: float


class MatchOut(ORMModel):
    id: str
    score: float
    decision: str
    deterministic_score: float
    semantic_score: float | None = None
    breakdown: dict[str, float] = Field(default_factory=dict)
    hard_fail_reasons: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    positive_signals: list[str] = Field(default_factory=list)
    rule_results: list[dict[str, Any]] = Field(default_factory=list)
    explanation: str = ""
    recommended_resume_id: str | None = None
    recommendation_reason: str = ""
    engine_version: str = ""
    created_at: datetime


class JobEventOut(ORMModel):
    id: str
    event_type: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    actor: str
    created_at: datetime


class JobOut(TimestampedModel):
    id: str
    title: str
    company: str
    location: str
    is_remote: bool
    url: str
    apply_url: str
    application_email: str = ""
    salary_min_lpa: float | None = None
    salary_max_lpa: float | None = None
    salary_raw: str = ""
    currency: str = "INR"
    employment_type: str
    industry: str
    experience_min_years: float | None = None
    experience_max_years: float | None = None
    source_name: str
    source_id: str | None = None
    status: str
    posted_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    seen_count: int = 1
    duplicate_sources: list[str] = Field(default_factory=list)
    match: MatchOut | None = None


class JobDetailOut(JobOut):
    description: str = ""
    skills: list[JobSkillOut] = Field(default_factory=list)
    events: list[JobEventOut] = Field(default_factory=list)


class DiscoverRequest(BaseModel):
    source_ids: list[str] | None = None
    saved_search_id: str | None = None
    limit_per_source: int = Field(default=50, ge=1, le=200)


class DiscoverResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[dict[str, Any]] = Field(default_factory=list)
    per_source: dict[str, Any] = Field(default_factory=dict)


class MatchPreviewRequest(BaseModel):
    """Score arbitrary text without persisting anything."""

    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    industry: str = ""
    employment_type: str = "full_time"
    is_remote: bool = False
    salary_min_lpa: float | None = None
    salary_max_lpa: float | None = None


class RescoreResult(BaseModel):
    rescored: int
    high_priority: int
    review: int
    rejected: int

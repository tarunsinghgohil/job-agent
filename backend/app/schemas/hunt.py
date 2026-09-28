"""3x Job Hunt request and response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

WorkMode = Literal["remote", "hybrid", "onsite"]


class LocationTier(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    group: str = Field(default="", max_length=120)
    work_modes: list[WorkMode] = Field(default_factory=lambda: ["remote", "hybrid", "onsite"])
    places: list[str] = Field(default_factory=list)
    kind: Literal["apply_first", "review"] = "apply_first"

    @field_validator("work_modes")
    @classmethod
    def _at_least_one_mode(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("choose at least one work mode")
        return list(dict.fromkeys(value))


class HuntConfigIn(BaseModel):
    experience_years: float | None = Field(default=None, ge=0, le=60)
    target_roles: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    role_keywords: list[str] = Field(default_factory=list)
    excluded_seniority: list[Literal["intern", "junior", "mid", "senior", "lead"]] = Field(
        default_factory=list
    )

    location_tiers: list[LocationTier] = Field(default_factory=list, max_length=20)
    country: str = Field(default="India", min_length=1, max_length=80)
    country_places: list[str] = Field(default_factory=list)
    accept_worldwide_remote: bool = True

    auto_queries: bool = True
    custom_queries: list[str] = Field(default_factory=list, max_length=50)
    excluded_queries: list[str] = Field(default_factory=list)
    max_queries: int = Field(default=20, ge=1, le=60)
    results_per_query: int = Field(default=25, ge=1, le=200)

    max_age_days: int = Field(default=30, ge=0, le=365)
    apply_first_threshold: int = Field(default=65, ge=0, le=100)
    min_skill_overlap: float = Field(default=0.4, ge=0, le=1)
    weights: dict[str, float] = Field(default_factory=dict)
    semantic_mode: Literal["off", "local", "embeddings"] = "local"
    respect_policy_filters: bool = True

    notify_new_matches: bool = True
    schedule_enabled: bool = False
    schedule_cron: str = Field(default="0 2,8,14,20 * * *", max_length=100)

    @field_validator("target_roles", "skills", "role_keywords", "country_places",
                     "custom_queries", "excluded_queries")
    @classmethod
    def _clean_strings(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value:
            text = str(item).strip()[:200]
            if text and text.lower() not in (o.lower() for o in out):
                out.append(text)
        return out

    @field_validator("weights")
    @classmethod
    def _check_weights(cls, value: dict[str, float]) -> dict[str, float]:
        allowed = {"location", "role", "skills", "experience", "freshness", "semantic", "apply_link"}
        for key, weight in value.items():
            if key not in allowed:
                raise ValueError(f"unknown weight {key!r}")
            if weight < 0 or weight > 100:
                raise ValueError(f"weight for {key!r} must be between 0 and 100")
        return value


class HuntConfigOut(HuntConfigIn):
    id: str
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_assessed_at: datetime | None = None
    updated_at: datetime | None = None


class HuntQueryOut(BaseModel):
    label: str
    keywords: str
    location: str = ""
    remote: bool = False
    origin: str = "generated"
    tier: str = ""


class HuntQueryPreview(BaseModel):
    queries: list[HuntQueryOut]
    search_sources: int = 0
    board_sources: int = 0
    board_keywords: list[str] = Field(default_factory=list)


class HuntRunRequest(BaseModel):
    discover: bool = True


class HuntItem(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    source_name: str
    duplicate_sources: list[str] = Field(default_factory=list)
    job_status: str
    url: str = ""
    salary_min_lpa: float | None = None
    salary_max_lpa: float | None = None
    currency: str = "INR"
    experience_min_years: float | None = None
    experience_max_years: float | None = None
    posted_at: datetime | None = None
    source_updated_at: datetime | None = None
    first_seen_at: datetime | None = None
    category: str
    section: str
    tier_name: str = ""
    tier_rank: int | None = None
    score: float
    strength: str
    work_mode: str
    remote_region: str = ""
    seniority: str
    experience_fit: str
    skill_overlap: float | None = None
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    semantic_score: float | None = None
    freshness_at: datetime | None = None
    freshness_basis: str
    freshness_hours: float | None = None
    freshness_label: str
    apply_link_type: str
    apply_link_label: str = ""
    best_apply_url: str = ""
    public_contact_email: str = ""
    reasons: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    breakdown: dict[str, float] = Field(default_factory=dict)
    explanation: str = ""
    assessed_at: datetime | None = None


class HuntSection(BaseModel):
    key: str
    label: str
    kind: str
    count: int
    items: list[HuntItem]


class HuntTierCount(BaseModel):
    name: str
    count: int


class HuntStats(BaseModel):
    total: int
    fresh_today: int
    apply_first: int
    review: int
    not_match: int
    remote: int
    by_tier: list[HuntTierCount] = Field(default_factory=list)


class HuntReasonCount(BaseModel):
    reason: str
    count: int


class HuntNotMatchSummary(BaseModel):
    count: int
    top_reasons: list[HuntReasonCount] = Field(default_factory=list)


class HuntBoard(BaseModel):
    stats: HuntStats
    sections: list[HuntSection]
    not_match: HuntNotMatchSummary
    last_run_at: datetime | None = None
    last_run_summary: dict[str, Any] = Field(default_factory=dict)
    last_assessed_at: datetime | None = None
    sources_enabled: int = 0


class HuntAssessRequest(BaseModel):
    """A job typed or pasted into the "Try it" box; nothing is saved."""

    title: str = Field(min_length=1, max_length=300)
    company: str = ""
    location: str = ""
    is_remote: bool = False
    description: str = ""
    experience_min_years: float | None = Field(default=None, ge=0, le=60)
    experience_max_years: float | None = Field(default=None, ge=0, le=60)
    apply_url: str = ""
    posted_at: datetime | None = None
    config: HuntConfigIn | None = None


class HuntJobDetail(BaseModel):
    assessment: HuntItem | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    # The most points each breakdown factor can contribute.
    breakdown_max: dict[str, float] = Field(default_factory=dict)


class HuntProfileSuggestions(BaseModel):
    experience_years: float | None = None
    skills: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)


class HuntRunOut(BaseModel):
    id: str
    trigger: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str = ""

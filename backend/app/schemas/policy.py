"""Preferences, matching rules, and saved searches."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.db.models.enums import RuleField, RuleOperator
from app.schemas.common import ORMModel, TimestampedModel


class PreferencesIn(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    remote_only: bool = False

    min_salary_lpa: float | None = Field(default=None, ge=0, le=1000)
    target_salary_lpa: float | None = Field(default=None, ge=0, le=1000)
    currency: str = "INR"

    experience_min_years: float | None = Field(default=None, ge=0, le=60)
    experience_max_years: float | None = Field(default=None, ge=0, le=60)
    notice_period_days: int = Field(default=0, ge=0, le=365)

    employment_types: list[str] = Field(default_factory=list)
    company_types: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    preferred_companies: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)

    must_have_keywords: list[str] = Field(default_factory=list)
    nice_to_have_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)

    review_threshold: int = Field(default=70, ge=0, le=100)
    high_priority_threshold: int = Field(default=85, ge=0, le=100)
    scoring_weights: dict[str, float] = Field(default_factory=dict)

    daily_application_cap: int = Field(default=8, ge=0, le=200)
    approval_required: bool = True
    auto_submit_enabled: bool = False
    discovery_schedule_cron: str = "0 8 * * *"
    timezone: str = "Asia/Kolkata"

    semantic_scoring_enabled: bool = False
    semantic_weight: float = Field(default=0.2, ge=0, le=1)

    @model_validator(mode="after")
    def _check_ranges(self) -> "PreferencesIn":
        if (
            self.experience_min_years is not None
            and self.experience_max_years is not None
            and self.experience_min_years > self.experience_max_years
        ):
            raise ValueError("experience_min_years cannot exceed experience_max_years")
        if (
            self.min_salary_lpa is not None
            and self.target_salary_lpa is not None
            and self.min_salary_lpa > self.target_salary_lpa
        ):
            raise ValueError("min_salary_lpa cannot exceed target_salary_lpa")
        if self.review_threshold > self.high_priority_threshold:
            raise ValueError("review_threshold cannot exceed high_priority_threshold")
        return self

    @field_validator("scoring_weights")
    @classmethod
    def _check_weights(cls, value: dict[str, float]) -> dict[str, float]:
        for key, weight in value.items():
            if weight < 0 or weight > 100:
                raise ValueError(f"weight for {key!r} must be between 0 and 100")
        return value


class PreferencesOut(PreferencesIn, TimestampedModel):
    id: str


class MatchRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    field: RuleField
    operator: RuleOperator
    value: Any = None
    weight: float = Field(default=0.0, ge=0, le=100)
    is_hard: bool = False
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    explanation: str = ""
    case_sensitive: bool = False

    @model_validator(mode="after")
    def _normalize_value(self) -> "MatchRuleIn":
        # Values are persisted as {"value": ...} so the column stays JSON-typed
        # whether the rule holds a scalar or a list.
        if not isinstance(self.value, dict) or "value" not in self.value:
            object.__setattr__(self, "value", {"value": self.value})
        return self


class MatchRuleOut(TimestampedModel):
    id: str
    name: str
    field: str
    operator: str
    value: Any = None
    weight: float
    is_hard: bool
    enabled: bool
    priority: int
    explanation: str
    case_sensitive: bool


class RuleTestRequest(BaseModel):
    job_id: str


class RuleTestResult(BaseModel):
    rule_id: str
    passed: bool
    detail: str
    is_hard: bool
    awarded: float


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    keywords: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_only: bool = False
    min_salary_lpa: float | None = Field(default=None, ge=0)
    employment_types: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    enabled: bool = True
    schedule_cron: str = ""


class SavedSearchOut(SavedSearchIn, TimestampedModel):
    id: str
    last_run_at: str | None = None

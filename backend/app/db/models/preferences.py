"""Job-search policy: preferences, the dynamic rule set, and saved searches.

Nothing in this module is hard-coded business logic. Every value is user data
edited from the dashboard, which is what keeps preferences out of source code.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDPrimaryKeyMixin


class JobPreference(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Single row per user holding the deterministic search policy."""

    __tablename__ = "job_preferences"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )

    target_roles: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    preferred_locations: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    remote_ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remote_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    min_salary_lpa: Mapped[float | None] = mapped_column(Float)
    target_salary_lpa: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)

    experience_min_years: Mapped[float | None] = mapped_column(Float)
    experience_max_years: Mapped[float | None] = mapped_column(Float)
    notice_period_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    employment_types: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    company_types: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    industries: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    preferred_companies: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    excluded_companies: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)

    must_have_keywords: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    nice_to_have_keywords: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    excluded_keywords: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)

    # Thresholds and scoring weights, all dashboard-editable.
    review_threshold: Mapped[int] = mapped_column(Integer, default=70, nullable=False)
    high_priority_threshold: Mapped[int] = mapped_column(Integer, default=85, nullable=False)
    scoring_weights: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)

    daily_application_cap: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_submit_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    discovery_schedule_cron: Mapped[str] = mapped_column(
        String(100), default="0 8 * * *", nullable=False
    )
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)

    # Semantic/LLM scoring is opt-in because it costs money per job.
    semantic_scoring_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    semantic_weight: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)

    @staticmethod
    def default_weights() -> dict[str, float]:
        """Weights sum to 100 so a perfect job scores 100 before penalties."""
        return {
            "must_have_skills": 25.0,
            "role_fit": 18.0,
            "preferred_skills": 15.0,
            "experience_fit": 10.0,
            "location_fit": 10.0,
            "salary_fit": 10.0,
            "industry_fit": 6.0,
            "company_preference": 3.0,
            "remote_fit": 3.0,
        }


class MatchRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single user-authored matching rule evaluated by the rules engine."""

    __tablename__ = "match_rules"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    operator: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_hard: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SavedSearch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "saved_searches"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_search_name"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    keywords: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    locations: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    remote_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    min_salary_lpa: Mapped[float | None] = mapped_column(Float)
    employment_types: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    source_ids: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schedule_cron: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    last_run_at: Mapped[str | None] = mapped_column(String(40))

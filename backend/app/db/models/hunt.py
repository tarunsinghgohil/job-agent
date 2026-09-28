"""3x Job Hunt: the user's hunt configuration and per-job hunt assessments.

The hunt is a layer on top of discovery and matching. ``HuntConfig`` holds
everything the user types into the Job Hunt setup screen (experience, roles,
skills, ordered location priorities, query and ranking settings), and
``HuntResult`` stores how each job was categorised against it, so the
shortlist board is a cheap query instead of a re-computation.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDPrimaryKeyMixin


class HuntConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per user. Every value is edited from the Job Hunt setup screen."""

    __tablename__ = "hunt_configs"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )

    # --- candidate ----------------------------------------------------------
    experience_years: Mapped[float | None] = mapped_column(Float)
    target_roles: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    skills: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    # Words that make a title part of the candidate's job family.
    role_keywords: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    # Seniority levels that are never a match (intern, junior, mid, senior, lead).
    excluded_seniority: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)

    # --- locations ----------------------------------------------------------
    # Ordered list of {name, group, work_modes, places, kind}; order = priority.
    location_tiers: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    country: Mapped[str] = mapped_column(String(80), default="India", nullable=False)
    # Cities and states that mean "inside the country" for location matching.
    country_places: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    accept_worldwide_remote: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- search queries -----------------------------------------------------
    auto_queries: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    custom_queries: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    excluded_queries: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    max_queries: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    results_per_query: Mapped[int] = mapped_column(Integer, default=25, nullable=False)

    # --- ranking ------------------------------------------------------------
    max_age_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    apply_first_threshold: Mapped[int] = mapped_column(Integer, default=65, nullable=False)
    min_skill_overlap: Mapped[float] = mapped_column(Float, default=0.4, nullable=False)
    weights: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    # off | local | embeddings
    semantic_mode: Mapped[str] = mapped_column(String(20), default="local", nullable=False)
    respect_policy_filters: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- output -------------------------------------------------------------
    notify_new_matches: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_summary: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    last_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HuntResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """How one job landed on the shortlist, with the reasons shown in the UI."""

    __tablename__ = "hunt_results"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_hunt_result_job"),
        Index("ix_hunt_results_user_category", "user_id", "category"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # apply_first | review | not_match
    category: Mapped[str] = mapped_column(String(20), default="not_match", nullable=False)
    section: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    tier_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    tier_rank: Mapped[int | None] = mapped_column(Integer)

    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    strength: Mapped[str] = mapped_column(String(20), default="weak", nullable=False)

    work_mode: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    remote_region: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    seniority: Mapped[str] = mapped_column(String(20), default="mid", nullable=False)
    experience_fit: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)

    skill_overlap: Mapped[float | None] = mapped_column(Float)
    matched_skills: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    missing_skills: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    semantic_score: Mapped[float | None] = mapped_column(Float)

    # The timestamp freshness was judged on, and which one it was
    # (posted | updated | first_seen). Age is computed live from it.
    freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    freshness_basis: Mapped[str] = mapped_column(String(20), default="first_seen", nullable=False)

    apply_link_type: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    apply_link_label: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    best_apply_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    public_contact_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)

    reasons: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    highlights: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    warnings: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)

    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set once a job has been included in a "new apply-first matches" alert.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

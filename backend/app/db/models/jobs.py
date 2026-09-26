"""Job sources, discovered jobs, match results, and the job audit timeline."""
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    Base,
    JSONColumn,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    Vector,
)
from app.db.models.resumes import EMBEDDING_DIM


class JobSource(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A configured provider. Adding one is configuration, never a code change."""

    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_job_source_name"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    config: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)

    # Points at encrypted_secrets.id; the credential itself is never stored here.
    credential_ref: Mapped[str | None] = mapped_column(String(32))

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    schedule_cron: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    query_templates: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    rate_limit_per_hour: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    source_rules: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)

    health: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    jobs: Mapped[list["Job"]] = relationship(back_populates="source")


class Job(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_job_dedupe_key"),
        Index("ix_jobs_user_status", "user_id", "status"),
        Index("ix_jobs_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_sources.id", ondelete="SET NULL"), index=True
    )
    source_name: Mapped[str] = mapped_column(String(120), default="manual", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), default="", index=True, nullable=False)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    company: Mapped[str] = mapped_column(String(200), default="", index=True, nullable=False)
    company_normalized: Mapped[str] = mapped_column(String(200), default="", index=True, nullable=False)
    location: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1000), default="", index=True, nullable=False)
    apply_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    # Set when the posting publishes an address to apply to. This is the only
    # channel the agent is allowed to submit through automatically.
    application_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)

    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    description_hash: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)

    salary_min_lpa: Mapped[float | None] = mapped_column(Float)
    salary_max_lpa: Mapped[float | None] = mapped_column(Float)
    salary_raw: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)

    employment_type: Mapped[str] = mapped_column(String(50), default="full_time", nullable=False)
    industry: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    experience_min_years: Mapped[float | None] = mapped_column(Float)
    experience_max_years: Mapped[float | None] = mapped_column(Float)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(String(30), default="new", index=True, nullable=False)

    # Deduplication bookkeeping.
    dedupe_key: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    canonical_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    duplicate_sources: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)

    raw_payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBEDDING_DIM))

    source: Mapped[JobSource | None] = relationship(back_populates="jobs")
    skills: Mapped[list["JobSkill"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    matches: Mapped[list["JobMatch"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobMatch.created_at.desc()"
    )
    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobEvent.created_at.desc()"
    )


class JobSkill(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "job_skills"
    __table_args__ = (UniqueConstraint("job_id", "skill_slug", name="uq_job_skill"),)

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="keyword", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    job: Mapped[Job] = relationship(back_populates="skills")


class JobMatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The explainable result of scoring one job against the user's policy."""

    __tablename__ = "job_matches"
    __table_args__ = (Index("ix_job_matches_user_decision", "user_id", "decision"),)

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    decision: Mapped[str] = mapped_column(String(30), default="REJECT", nullable=False)
    deterministic_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    semantic_score: Mapped[float | None] = mapped_column(Float)

    breakdown: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    hard_fail_reasons: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    matched_skills: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    missing_skills: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    positive_signals: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    rule_results: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)

    recommended_resume_id: Mapped[str | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="SET NULL")
    )
    recommendation_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    engine_version: Mapped[str] = mapped_column(String(20), default="1", nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    job: Mapped[Job] = relationship(back_populates="matches")


class JobEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only per-job audit timeline."""

    __tablename__ = "job_events"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    actor: Mapped[str] = mapped_column(String(60), default="system", nullable=False)

    job: Mapped[Job] = relationship(back_populates="events")

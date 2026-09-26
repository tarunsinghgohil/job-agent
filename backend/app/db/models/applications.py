"""Application queue, tracker, generated assets, answers, and follow-ups."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDPrimaryKeyMixin


class Application(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_user_status", "user_id", "status"),
        Index("ix_applications_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    resume_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="SET NULL")
    )

    status: Mapped[str] = mapped_column(
        String(30), default="pending_review", index=True, nullable=False
    )
    channel: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float)

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    next_action: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    next_action_due: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    outcome_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    recruiter_id: Mapped[str | None] = mapped_column(
        ForeignKey("recruiters.id", ondelete="SET NULL")
    )

    history: Mapped[list["ApplicationStatusHistory"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ApplicationStatusHistory.created_at",
    )
    answers: Mapped[list["ApplicationAnswer"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    assets: Mapped[list["ApplicationAsset"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    followups: Mapped[list["FollowUp"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    interviews: Mapped[list["Interview"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationStatusHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "application_status_history"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(30), default="", nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    actor: Mapped[str] = mapped_column(String(60), default="system", nullable=False)

    application: Mapped[Application] = relationship(back_populates="history")


class ApplicationAnswer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The answers actually submitted, snapshotted at submission time."""

    __tablename__ = "application_answers"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    state: Mapped[str] = mapped_column(String(30), default="needs_review", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    resolved_from: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    answer_bank_id: Mapped[str | None] = mapped_column(String(32))
    evidence_ids: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)

    application: Mapped[Application] = relationship(back_populates="answers")


class ApplicationAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Generated artifacts: tailored resume, cover letter, pitch."""

    __tablename__ = "application_assets"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    model_used: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    evidence_ids: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    validation: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)

    application: Mapped[Application] = relationship(back_populates="assets")


class FollowUp(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "followups"
    __table_args__ = (Index("ix_followups_due", "user_id", "due_date", "completed_at"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(50), default="check_in", nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application] = relationship(back_populates="followups")


class Recruiter(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recruiters"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    company: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    linkedin_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Interview(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "interviews"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    round_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mode: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    interviewers: Mapped[list] = mapped_column(JSONColumn, default=list, nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    feedback: Mapped[str] = mapped_column(Text, default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    application: Mapped[Application] = relationship(back_populates="interviews")


class Offer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "offers"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    base_lpa: Mapped[float | None] = mapped_column(Float)
    total_lpa: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    joining_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), default="received", nullable=False)
    details: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class AnswerBankEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Reusable application answers, optionally scoped to a job or company."""

    __tablename__ = "answer_bank"
    __table_args__ = (Index("ix_answer_bank_user_key", "user_id", "normalized_key"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(80), default="general", nullable=False)
    variables: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="user", nullable=False)
    state: Mapped[str] = mapped_column(String(30), default="verified", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Overrides: when set, this entry only applies to that job or company.
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    company_normalized: Mapped[str] = mapped_column(String(200), default="", index=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

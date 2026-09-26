"""Agent registry, run history, schedules, and AI usage accounting."""
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

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDPrimaryKeyMixin


class AgentDefinition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per agent in the control center, e.g. 'discovery'."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_agent_key"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    schedule_cron: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    config: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", order_by="AgentRun.created_at.desc()"
    )


class AgentRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_user_created", "user_id", "created_at"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    agent_key: Mapped[str] = mapped_column(String(60), default="", index=True, nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    items_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_succeeded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    summary: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    agent: Mapped[AgentDefinition | None] = relationship(back_populates="runs")
    steps: Mapped[list["AgentRunStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentRunStep.sequence"
    )


class AgentRunStep(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_run_steps"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    run: Mapped[AgentRun] = relationship(back_populates="steps")


class Schedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Declarative schedule rows. The scheduler reconciles jobs against these,
    which is what prevents duplicate scheduled tasks after a restart."""

    __tablename__ = "schedules"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_schedule_key"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    cron: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    agent_key: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)


class AIUsage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One row per AI call, for cost control and latency observability."""

    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_user_created", "user_id", "created_at"),)

    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    function: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="openai", nullable=False)
    model: Mapped[str] = mapped_column(String(80), default="", nullable=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)


class AICache(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Response cache keyed by prompt hash, so repeat analysis is free."""

    __tablename__ = "ai_cache"

    request_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    function: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    response: Mapped[str] = mapped_column(Text, default="", nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

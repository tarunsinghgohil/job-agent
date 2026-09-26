"""Notifications, encrypted credentials, audit trail, and system settings."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONColumn, TimestampMixin, UUIDPrimaryKeyMixin


class NotificationChannel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notification_channels"
    __table_args__ = (UniqueConstraint("user_id", "channel_type", name="uq_notification_channel"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Non-secret routing config only (chat id, address). Tokens live in secrets.
    config: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(32))

    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class NotificationPreference(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-user delivery policy: which events go where, and when to stay quiet."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    # {event_type: [channel_type, ...]}
    event_routing: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    quiet_hours_start: Mapped[str] = mapped_column(String(5), default="", nullable=False)
    quiet_hours_end: Mapped[str] = mapped_column(String(5), default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    daily_digest_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    daily_digest_time: Mapped[str] = mapped_column(String(5), default="09:00", nullable=False)
    weekly_summary_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    instant_alerts_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failures_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class NotificationEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notification_events"
    __table_args__ = (Index("ix_notification_events_user_created", "user_id", "created_at"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    channel_type: Mapped[str] = mapped_column(String(30), default="", nullable=False)
    subject: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(120), default="", index=True, nullable=False)


class EncryptedSecret(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Provider credentials. `ciphertext` is Fernet output, never plaintext."""

    __tablename__ = "encrypted_secrets"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_secret_key"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    hint: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(60), default="", nullable=False)

    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only record of every consequential action."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    actor: Mapped[str] = mapped_column(String(80), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONColumn)
    after: Mapped[dict | None] = mapped_column(JSONColumn)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SystemSetting(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Feature flags and operational toggles editable from the dashboard."""

    __tablename__ = "system_settings"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_system_setting_key"),)

    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict] = mapped_column(JSONColumn, default=dict, nullable=False)
    description: Mapped[str] = mapped_column(String(300), default="", nullable=False)

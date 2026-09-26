"""Notification channels, routing preferences, and delivery history."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.deps import Context, DbSession
from app.core.errors import NotFoundError, ValidationError
from app.db.models.enums import NotificationChannelType
from app.db.models.ops import NotificationChannel, NotificationEvent, NotificationPreference
from app.schemas.common import MessageResponse, TestResult
from app.schemas.ops import (
    NotificationChannelIn,
    NotificationChannelOut,
    NotificationEventOut,
    NotificationPreferencesIn,
    NotificationPreferencesOut,
)
from app.services import audit, secrets
from app.services.notifications.base import list_channels
from app.services.notifications.service import test_channel

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Which stored credential backs each channel type.
_CHANNEL_SECRET_KEY = {
    NotificationChannelType.EMAIL: "smtp_password",
    NotificationChannelType.TELEGRAM: "telegram_bot_token",
    NotificationChannelType.SLACK: "slack_webhook_url",
    NotificationChannelType.WHATSAPP: "whatsapp_api_key",
}


def _descriptors() -> dict[str, dict[str, Any]]:
    return {d["channel_type"]: d for d in list_channels()}


def _serialize(channel: NotificationChannel, descriptor: dict[str, Any]) -> NotificationChannelOut:
    return NotificationChannelOut(
        id=channel.id,
        created_at=channel.created_at,
        updated_at=channel.updated_at,
        channel_type=channel.channel_type,
        display_name=descriptor.get("display_name", channel.channel_type),
        enabled=channel.enabled,
        config=channel.config or {},
        has_credential=bool(channel.credential_ref),
        requires_credential=bool(descriptor.get("requires_credential", False)),
        config_schema=descriptor.get("config_schema", []),
        last_test_at=channel.last_test_at,
        last_test_ok=channel.last_test_ok,
        last_error=channel.last_error,
    )


def _get_or_create(db: Any, user_id: str, channel_type: str) -> NotificationChannel:
    channel = db.execute(
        select(NotificationChannel).where(
            NotificationChannel.user_id == user_id,
            NotificationChannel.channel_type == channel_type,
        )
    ).scalar_one_or_none()
    if channel is None:
        channel = NotificationChannel(user_id=user_id, channel_type=channel_type)
        db.add(channel)
        db.flush()
    return channel


@router.get("/channels", response_model=list[NotificationChannelOut])
def list_notification_channels(db: DbSession, ctx: Context) -> list[NotificationChannelOut]:
    descriptors = _descriptors()
    out: list[NotificationChannelOut] = []
    for channel_type, descriptor in descriptors.items():
        channel = _get_or_create(db, ctx.user_id, channel_type)
        out.append(_serialize(channel, descriptor))
    return out


@router.put("/channels/{channel_type}", response_model=NotificationChannelOut)
def update_channel(
    channel_type: str, payload: NotificationChannelIn, db: DbSession, ctx: Context
) -> NotificationChannelOut:
    descriptors = _descriptors()
    if channel_type not in descriptors:
        raise NotFoundError(f"There is no {channel_type!r} notification channel.")

    channel = _get_or_create(db, ctx.user_id, channel_type)
    channel.enabled = payload.enabled
    channel.config = payload.config

    if payload.credential is not None:
        secret_key = _CHANNEL_SECRET_KEY.get(channel_type, f"channel:{channel_type}")
        if payload.credential.strip():
            row = secrets.put(
                db, ctx.user_id, secret_key, payload.credential,
                label=f"{descriptors[channel_type]['display_name']} credential",
                provider=channel_type,
            )
            channel.credential_ref = row.id
        else:
            secrets.delete(db, ctx.user_id, secret_key)
            channel.credential_ref = None

    db.flush()
    audit.record(
        db, action="notification.channel.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="notification_channel", entity_id=channel.id,
        summary=f"{'Enabled' if channel.enabled else 'Disabled'} the {channel_type} channel",
    )
    return _serialize(channel, descriptors[channel_type])


@router.post("/channels/{channel_type}/test", response_model=TestResult)
def test_notification_channel(
    channel_type: str, db: DbSession, ctx: Context
) -> TestResult:
    if channel_type not in _descriptors():
        raise NotFoundError(f"There is no {channel_type!r} notification channel.")

    result = test_channel(db, ctx.user_id, channel_type)
    db.flush()
    audit.record(
        db, action="notification.channel.test", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="notification_channel", entity_id=channel_type,
        summary=f"Tested {channel_type}: {'ok' if result.ok else 'failed'}",
        success=result.ok,
    )
    return TestResult(ok=result.ok, message=result.message, details=result.details)


@router.get("/preferences", response_model=NotificationPreferencesOut)
def get_preferences(db: DbSession, ctx: Context) -> NotificationPreferencesOut:
    prefs = db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == ctx.user_id)
    ).scalar_one_or_none()
    if prefs is None:
        prefs = NotificationPreference(user_id=ctx.user_id, event_routing={})
        db.add(prefs)
        db.flush()
    return NotificationPreferencesOut.model_validate(prefs)


@router.put("/preferences", response_model=NotificationPreferencesOut)
def update_preferences(
    payload: NotificationPreferencesIn, db: DbSession, ctx: Context
) -> NotificationPreferencesOut:
    prefs = db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == ctx.user_id)
    ).scalar_one_or_none()
    if prefs is None:
        prefs = NotificationPreference(user_id=ctx.user_id)
        db.add(prefs)

    for name, value in payload.model_dump().items():
        setattr(prefs, name, value)
    db.flush()

    audit.record(
        db, action="notification.preferences.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="notification_preferences", entity_id=prefs.id,
        summary="Updated notification preferences",
    )
    return NotificationPreferencesOut.model_validate(prefs)


@router.get("/events", response_model=list[NotificationEventOut])
def list_events(
    db: DbSession,
    ctx: Context,
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = None,
) -> list[NotificationEventOut]:
    stmt = select(NotificationEvent).where(NotificationEvent.user_id == ctx.user_id)
    if status:
        stmt = stmt.where(NotificationEvent.status == status)
    rows = db.execute(
        stmt.order_by(NotificationEvent.created_at.desc()).limit(limit)
    ).scalars().all()
    return [NotificationEventOut.model_validate(r) for r in rows]

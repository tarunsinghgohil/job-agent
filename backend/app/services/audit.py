"""Audit trail (spec section 10 of the non-negotiables: every important
automated action must be auditable).

Writes are append-only and must never break the operation being audited: a
failure to record an audit row is logged, not raised.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.jobs import JobEvent
from app.db.models.ops import AuditLog

logger = logging.getLogger(__name__)

# Keys whose values must never reach the audit table.
_REDACT_KEYS = {
    "password", "new_password", "current_password", "token", "access_token",
    "refresh_token", "api_key", "apikey", "secret", "credential", "ciphertext",
    "authorization", "cookie", "webhook_url", "bot_token", "value",
}
_MAX_VALUE_CHARS = 2000


def redact(data: Any) -> Any:
    """Recursively strip secret-looking values before persisting."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            if str(key).lower() in _REDACT_KEYS:
                out[key] = "***redacted***"
            else:
                out[key] = redact(value)
        return out
    if isinstance(data, (list, tuple)):
        return [redact(v) for v in data][:100]
    if isinstance(data, str) and len(data) > _MAX_VALUE_CHARS:
        return data[:_MAX_VALUE_CHARS] + "…"
    return data


def record(
    db: Session,
    *,
    action: str,
    user_id: str | None = None,
    actor: str = "system",
    entity_type: str = "",
    entity_id: str = "",
    summary: str = "",
    before: Any = None,
    after: Any = None,
    ip_address: str = "",
    user_agent: str = "",
    success: bool = True,
) -> AuditLog | None:
    """Append one audit row. Returns None if the write could not be staged."""
    try:
        entry = AuditLog(
            user_id=user_id,
            actor=actor or "system",
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id or ""),
            summary=summary[:4000],
            before=redact(before) if before is not None else None,
            after=redact(after) if after is not None else None,
            ip_address=ip_address[:64],
            user_agent=user_agent[:400],
            success=success,
        )
        db.add(entry)
        return entry
    except Exception as exc:  # auditing must never break the caller
        logger.error("Failed to record audit entry for action=%s: %s", action, exc)
        return None


def job_event(
    db: Session,
    job_id: str,
    event_type: str,
    *,
    message: str = "",
    payload: dict | None = None,
    actor: str = "system",
) -> JobEvent | None:
    """Append to a job's own timeline, shown on the job detail page."""
    try:
        event = JobEvent(
            job_id=job_id,
            event_type=event_type,
            message=message[:4000],
            payload=redact(payload or {}),
            actor=actor,
        )
        db.add(event)
        return event
    except Exception as exc:
        logger.error("Failed to record job event %s for job %s: %s", event_type, job_id, exc)
        return None


def recent(db: Session, user_id: str, limit: int = 20) -> list[AuditLog]:
    return list(
        db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def diff_model(before: Any, after: Any, fields: list[str]) -> tuple[dict, dict]:
    """Build a minimal before/after pair covering only the fields that changed."""
    b: dict[str, Any] = {}
    a: dict[str, Any] = {}
    for name in fields:
        old = getattr(before, name, None) if before is not None else None
        new = getattr(after, name, None) if after is not None else None
        if old != new:
            b[name] = old
            a[name] = new
    return (b, a)

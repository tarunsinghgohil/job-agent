"""Notification dispatch, channel testing, and digest rendering.

Delivery policy lives here rather than in the adapters so that every channel
obeys the same rules: routing, quiet hours, and de-duplication. Two hard rules
shape the code below:

  * ``dispatch`` never raises. It is called from schedulers, agents and request
    handlers whose real work has already succeeded; a broken Telegram token must
    not roll back an application submission.
  * nothing here commits. The caller owns the transaction, so dispatch only
    flushes -- that keeps a notification consistent with the change that
    triggered it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret
from app.db.models.applications import Application, FollowUp, Interview
from app.db.models.enums import (
    ApplicationStatus,
    MatchDecision,
    NotificationEventType,
    NotificationStatus,
)
from app.db.models.jobs import Job, JobMatch
from app.db.models.ops import (
    EncryptedSecret,
    NotificationChannel,
    NotificationEvent,
    NotificationPreference,
)
from app.services.notifications.base import (
    DeliveryResult,
    NotificationMessage,
    UnknownChannelError,
    get_channel_adapter,
)

logger = logging.getLogger(__name__)

# Events that describe something already broken. They ignore quiet hours and
# survive a "failures only" preference, because silencing them would hide the
# exact situation the user asked to be told about.
FAILURE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        NotificationEventType.INTEGRATION_FAILED.value,
        NotificationEventType.SCHEDULED_RUN_FAILED.value,
        NotificationEventType.QUOTA_WARNING.value,
    }
)

DEDUPE_WINDOW_HOURS = 24
MAX_ERROR_CHARS = 2000
MAX_SUBJECT_CHARS = 300

_SETTINGS_CREDENTIAL_ATTRS: dict[str, str] = {
    "email": "smtp_password",
    "telegram": "telegram_bot_token",
    "slack": "slack_webhook_url",
    "whatsapp": "whatsapp_api_key",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_failure_event(event_type: str) -> bool:
    return event_type in FAILURE_EVENT_TYPES or "fail" in (event_type or "").lower()


def resolve_zone(name: str) -> ZoneInfo | timezone:
    for candidate in (name, settings.timezone):
        if candidate:
            try:
                return ZoneInfo(candidate)
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return timezone.utc


def _parse_hhmm(value: str) -> int | None:
    """Return minutes-since-midnight, or None when the value is unusable."""
    raw = (value or "").strip()
    if not raw or ":" not in raw:
        return None
    hours, _, minutes = raw.partition(":")
    try:
        hour, minute = int(hours), int(minutes)
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def in_quiet_hours(pref: NotificationPreference | None, now: datetime | None = None) -> bool:
    """True when local time falls inside the user's quiet window.

    Handles the common overnight window (22:00 -> 07:00), where the start is
    numerically greater than the end and the interval wraps past midnight.
    """
    if pref is None:
        return False
    start = _parse_hhmm(pref.quiet_hours_start)
    end = _parse_hhmm(pref.quiet_hours_end)
    if start is None or end is None or start == end:
        return False

    moment = now or _utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(resolve_zone(pref.timezone))
    current = local.hour * 60 + local.minute

    if start < end:
        return start <= current < end
    return current >= start or current < end


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; treat those as the UTC they were stored as."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def resolve_credential(db: Session, channel: NotificationChannel) -> str | None:
    """Decrypt this channel's stored secret, falling back to environment settings.

    Failure is logged without the ciphertext or the key material, because an
    unreadable secret usually means APP_SECRET_KEY rotated and the message would
    otherwise end up in the log.
    """
    ref = (channel.credential_ref or "").strip()
    if ref:
        secret = db.scalar(
            select(EncryptedSecret).where(
                EncryptedSecret.user_id == channel.user_id,
                or_(EncryptedSecret.id == ref, EncryptedSecret.key == ref),
            )
        )
        if secret is not None:
            try:
                return decrypt_secret(secret.ciphertext)
            except Exception:  # noqa: BLE001 - never surface secret material
                logger.error(
                    "Could not decrypt the %s credential for user %s; falling back to settings.",
                    channel.channel_type,
                    channel.user_id,
                )
    attr = _SETTINGS_CREDENTIAL_ATTRS.get(channel.channel_type, "")
    fallback = getattr(settings, attr, "") if attr else ""
    return fallback or None


def _recently_dispatched(db: Session, user_id: str, dedupe_key: str) -> bool:
    cutoff = _utcnow() - timedelta(hours=DEDUPE_WINDOW_HOURS)
    existing = db.scalar(
        select(NotificationEvent.id)
        .where(
            NotificationEvent.user_id == user_id,
            NotificationEvent.dedupe_key == dedupe_key,
            NotificationEvent.created_at >= cutoff,
        )
        .limit(1)
    )
    return existing is not None


def _target_channels(
    db: Session,
    user_id: str,
    pref: NotificationPreference | None,
    event_type: str,
    failure: bool,
) -> list[NotificationChannel]:
    enabled = list(
        db.scalars(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user_id,
                NotificationChannel.enabled.is_(True),
            )
        )
    )
    if not enabled:
        return []

    routing = (pref.event_routing or {}) if pref is not None else {}
    wanted = routing.get(event_type)
    if isinstance(wanted, str):
        wanted = [wanted]
    if wanted:
        rank = {name: index for index, name in enumerate(wanted)}
        return sorted(
            (c for c in enabled if c.channel_type in rank),
            key=lambda c: rank[c.channel_type],
        )

    if pref is not None and pref.failures_only and not failure:
        return []
    return enabled


def _record(
    db: Session,
    *,
    user_id: str,
    message: NotificationMessage,
    channel_type: str,
    dedupe_key: str,
) -> NotificationEvent:
    event = NotificationEvent(
        user_id=user_id,
        event_type=message.event_type,
        channel_type=channel_type,
        subject=(message.subject or "")[:MAX_SUBJECT_CHARS],
        body=message.body or "",
        status=NotificationStatus.PENDING.value,
        payload=dict(message.payload or {}),
        dedupe_key=(dedupe_key or "")[:120],
        attempts=0,
    )
    db.add(event)
    return event


def _deliver(
    db: Session,
    channel: NotificationChannel,
    message: NotificationMessage,
    event: NotificationEvent,
) -> None:
    try:
        adapter = get_channel_adapter(
            channel.channel_type, dict(channel.config or {}), resolve_credential(db, channel)
        )
        result = adapter.send(message)
    except UnknownChannelError as exc:
        result = DeliveryResult(ok=False, message=str(exc))
    except Exception as exc:  # noqa: BLE001 - an adapter bug must not break the caller
        logger.exception("Notification adapter %s raised during send.", channel.channel_type)
        result = DeliveryResult(
            ok=False, message=f"{channel.channel_type} adapter error: {type(exc).__name__}: {exc}"
        )

    event.attempts = 1
    if result.ok:
        event.status = NotificationStatus.SENT.value
        event.sent_at = _utcnow()
        event.error = ""
        channel.last_error = ""
    else:
        event.status = NotificationStatus.FAILED.value
        event.error = (result.message or "delivery failed")[:MAX_ERROR_CHARS]
        channel.last_error = event.error[:500]


def dispatch(
    db: Session,
    user_id: str,
    event_type: str,
    subject: str,
    body: str,
    *,
    payload: dict | None = None,
    dedupe_key: str = "",
    url: str | None = None,
) -> list[NotificationEvent]:
    """Fan one event out to the channels the user routed it to.

    Returns the persisted :class:`NotificationEvent` rows (one per channel),
    which is empty when nothing was eligible to send.
    """
    try:
        if dedupe_key and _recently_dispatched(db, user_id, dedupe_key):
            logger.debug("Skipping duplicate notification %s for user %s", dedupe_key, user_id)
            return []

        pref = db.scalar(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        failure = is_failure_event(event_type)
        channels = _target_channels(db, user_id, pref, event_type, failure)
        if not channels:
            return []

        quiet = not failure and in_quiet_hours(pref, _utcnow())
        message = NotificationMessage(
            subject=subject,
            body=body,
            event_type=event_type,
            payload=dict(payload or {}),
            url=url,
        )

        events: list[NotificationEvent] = []
        for channel in channels:
            event = _record(
                db,
                user_id=user_id,
                message=message,
                channel_type=channel.channel_type,
                dedupe_key=dedupe_key,
            )
            if quiet:
                event.status = NotificationStatus.SUPPRESSED.value
                event.error = "Suppressed by quiet hours."
            else:
                _deliver(db, channel, message, event)
            events.append(event)

        db.flush()
        return events
    except Exception:  # noqa: BLE001 - notification failure is never the caller's problem
        logger.exception(
            "Notification dispatch failed for user %s, event %s.", user_id, event_type
        )
        return []


def test_channel(db: Session, user_id: str, channel_type: str) -> DeliveryResult:
    """Send a probe through one channel and record the outcome on the row."""
    try:
        channel = db.scalar(
            select(NotificationChannel).where(
                NotificationChannel.user_id == user_id,
                NotificationChannel.channel_type == channel_type,
            )
        )
        if channel is None:
            return DeliveryResult(
                ok=False,
                message=f"No {channel_type} channel is configured for this account.",
                details={"configured": False},
            )

        adapter = get_channel_adapter(
            channel_type, dict(channel.config or {}), resolve_credential(db, channel)
        )
        result = adapter.test()
    except UnknownChannelError as exc:
        return DeliveryResult(ok=False, message=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Channel test for %s raised.", channel_type)
        return DeliveryResult(ok=False, message=f"{type(exc).__name__}: {exc}")

    channel.last_test_at = _utcnow()
    channel.last_test_ok = result.ok
    channel.last_error = "" if result.ok else (result.message or "")[:500]
    db.flush()
    return result


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------
def _plural(count: int, singular: str, plural: str = "") -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def render_daily_digest(db: Session, user_id: str) -> NotificationMessage | None:
    """Summarise the last 24 hours, or None when there is nothing worth sending."""
    pref = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    if pref is not None and not pref.daily_digest_enabled:
        return None

    since = _utcnow() - timedelta(hours=24)
    today = _utcnow().astimezone(resolve_zone(pref.timezone if pref else settings.timezone)).date()

    new_jobs = list(
        db.scalars(
            select(Job)
            .where(Job.user_id == user_id, Job.created_at >= since, Job.deleted_at.is_(None))
            .order_by(Job.created_at.desc())
        )
    )
    top_matches = list(
        db.execute(
            select(JobMatch, Job)
            .join(Job, Job.id == JobMatch.job_id)
            .where(
                JobMatch.user_id == user_id,
                JobMatch.is_current.is_(True),
                JobMatch.created_at >= since,
                JobMatch.decision != MatchDecision.REJECT.value,
            )
            .order_by(JobMatch.score.desc())
            .limit(5)
        ).all()
    )
    awaiting_review = list(
        db.scalars(
            select(Application).where(
                Application.user_id == user_id,
                Application.status == ApplicationStatus.PENDING_REVIEW.value,
            )
        )
    )
    due = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.user_id == user_id,
                FollowUp.completed_at.is_(None),
                FollowUp.due_date <= today,
            )
        )
    )

    if not (new_jobs or top_matches or awaiting_review or due):
        return None

    lines = [
        f"Daily digest for {today.isoformat()}",
        "",
        f"- {_plural(len(new_jobs), 'new job')} discovered in the last 24 hours",
        f"- {_plural(len(top_matches), 'qualified match', 'qualified matches')} scored",
        f"- {_plural(len(awaiting_review), 'application')} awaiting your approval",
        f"- {_plural(len(due), 'follow-up')} due",
    ]
    if top_matches:
        lines += ["", "Top matches:"]
        lines += [
            f"  {match.score:.0f}  {job.title} - {job.company or 'unknown company'}"
            f"{' (' + job.location + ')' if job.location else ''}"
            for match, job in top_matches
        ]

    return NotificationMessage(
        subject=f"Job Agent daily digest - {len(new_jobs)} new, {len(top_matches)} qualified",
        body="\n".join(lines),
        event_type=NotificationEventType.DAILY_DIGEST.value,
        payload={
            "new_jobs": len(new_jobs),
            "qualified": len(top_matches),
            "awaiting_review": len(awaiting_review),
            "followups_due": len(due),
            "date": today.isoformat(),
        },
    )


def render_weekly_summary(db: Session, user_id: str) -> NotificationMessage | None:
    """Seven-day performance recap, or None when the week was empty."""
    pref = db.scalar(select(NotificationPreference).where(NotificationPreference.user_id == user_id))
    if pref is not None and not pref.weekly_summary_enabled:
        return None

    since = _utcnow() - timedelta(days=7)
    zone = resolve_zone(pref.timezone if pref else settings.timezone)
    today = _utcnow().astimezone(zone).date()

    jobs_found = len(
        list(
            db.scalars(
                select(Job.id).where(
                    Job.user_id == user_id, Job.created_at >= since, Job.deleted_at.is_(None)
                )
            )
        )
    )
    applications = list(
        db.scalars(select(Application).where(Application.user_id == user_id, Application.created_at >= since))
    )
    submitted = [a for a in applications if a.submitted_at is not None]
    interviews = list(
        db.scalars(
            select(Interview)
            .join(Application, Application.id == Interview.application_id)
            .where(Application.user_id == user_id, Interview.created_at >= since)
        )
    )
    upcoming = list(
        db.scalars(
            select(FollowUp).where(
                FollowUp.user_id == user_id,
                FollowUp.completed_at.is_(None),
                FollowUp.due_date <= today + timedelta(days=7),
            )
        )
    )

    if not (jobs_found or applications or interviews or upcoming):
        return None

    body = "\n".join(
        [
            f"Week ending {today.isoformat()}",
            "",
            f"- {_plural(jobs_found, 'job')} discovered",
            f"- {_plural(len(applications), 'application')} created",
            f"- {_plural(len(submitted), 'application')} submitted",
            f"- {_plural(len(interviews), 'interview')} added",
            f"- {_plural(len(upcoming), 'follow-up')} due in the next week",
        ]
    )
    return NotificationMessage(
        subject=f"Job Agent weekly summary - {len(submitted)} submitted, {len(interviews)} interviews",
        body=body,
        event_type=NotificationEventType.WEEKLY_SUMMARY.value,
        payload={
            "jobs_found": jobs_found,
            "applications_created": len(applications),
            "applications_submitted": len(submitted),
            "interviews": len(interviews),
            "followups_upcoming": len(upcoming),
            "week_ending": today.isoformat(),
        },
    )


__all__ = [
    "dispatch",
    "test_channel",
    "render_daily_digest",
    "render_weekly_summary",
    "in_quiet_hours",
    "is_failure_event",
    "resolve_credential",
    "resolve_zone",
    "FAILURE_EVENT_TYPES",
]

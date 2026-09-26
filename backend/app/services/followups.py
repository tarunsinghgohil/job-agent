"""Follow-up reminders for submitted applications.

A follow-up is the cheapest lever in a job search and the easiest to forget, so
one is created automatically at submission time and the reminder is de-duplicated
per follow-up: the user gets told once, not on every scheduler tick.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.applications import Application, FollowUp
from app.db.models.enums import NotificationEventType, NotificationStatus
from app.db.models.jobs import Job
from app.services.notifications.service import dispatch, resolve_zone

logger = logging.getLogger(__name__)

DEFAULT_FOLLOWUP_DAYS = 7
DEFAULT_FOLLOWUP_KIND = "check_in"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local_today() -> date:
    """Due dates are wall-clock dates, so 'today' must be the user's date, not UTC's.

    In IST a follow-up due today would otherwise stay invisible until 05:30.
    """
    return _utcnow().astimezone(resolve_zone(settings.timezone)).date()


def due_followups(
    db: Session,
    user_id: str,
    *,
    before: date | None = None,
    include_completed: bool = False,
) -> list[FollowUp]:
    """Follow-ups due on or before ``before`` (default: today), oldest first."""
    cutoff = before or _local_today()
    stmt = select(FollowUp).where(FollowUp.user_id == user_id, FollowUp.due_date <= cutoff)
    if not include_completed:
        stmt = stmt.where(FollowUp.completed_at.is_(None))
    return list(db.scalars(stmt.order_by(FollowUp.due_date, FollowUp.created_at)))


def create_followup(
    db: Session,
    user_id: str,
    application_id: str,
    due_date: date,
    kind: str = DEFAULT_FOLLOWUP_KIND,
    note: str = "",
) -> FollowUp:
    followup = FollowUp(
        user_id=user_id,
        application_id=application_id,
        due_date=due_date,
        kind=kind or DEFAULT_FOLLOWUP_KIND,
        note=note or "",
    )
    db.add(followup)
    db.flush()
    return followup


def complete_followup(db: Session, followup_id: str) -> FollowUp:
    followup = db.get(FollowUp, followup_id)
    if followup is None:
        raise LookupError(f"Follow-up {followup_id} does not exist.")
    if followup.completed_at is None:
        followup.completed_at = _utcnow()
        db.flush()
    return followup


def _context(db: Session, followup: FollowUp) -> tuple[str, str, str]:
    """Job title, company and apply URL for the follow-up's application."""
    row = db.execute(
        select(Job.title, Job.company, Job.url)
        .join(Application, Application.job_id == Job.id)
        .where(Application.id == followup.application_id)
    ).first()
    if row is None:
        return "an application", "", ""
    title, company, url = row
    return title or "an application", company or "", url or ""


def notify_due_followups(db: Session, user_id: str) -> int:
    """Alert on every un-notified due follow-up. Returns how many were delivered."""
    sent = 0
    for followup in due_followups(db, user_id):
        if followup.notified_at is not None:
            continue

        title, company, url = _context(db, followup)
        target = f"{title} at {company}" if company else title
        events = dispatch(
            db,
            user_id,
            NotificationEventType.FOLLOWUP_DUE.value,
            subject=f"Follow-up due: {target}",
            body=(
                f"Your {followup.kind.replace('_', ' ')} follow-up for {target} "
                f"was due on {followup.due_date.isoformat()}."
                + (f"\n\nNote: {followup.note}" if followup.note else "")
            ),
            payload={
                "followup_id": followup.id,
                "application_id": followup.application_id,
                "kind": followup.kind,
                "due_date": followup.due_date.isoformat(),
            },
            dedupe_key=f"followup:{followup.id}",
            url=url or None,
        )
        if not events:
            continue

        # Suppressed counts as handled: quiet hours already recorded the event and
        # re-alerting later would double-notify for the same follow-up.
        followup.notified_at = _utcnow()
        if any(event.status == NotificationStatus.SENT.value for event in events):
            sent += 1

    db.flush()
    return sent


def schedule_default_followup(db: Session, application: Application) -> FollowUp | None:
    """Queue the standard post-submission check-in, once per application."""
    existing = db.scalar(
        select(FollowUp).where(
            FollowUp.application_id == application.id,
            FollowUp.kind == DEFAULT_FOLLOWUP_KIND,
            FollowUp.completed_at.is_(None),
        )
    )
    if existing is not None:
        return None

    submitted = application.submitted_at or _utcnow()
    if submitted.tzinfo is None:
        submitted = submitted.replace(tzinfo=timezone.utc)
    due = submitted.date() + timedelta(days=DEFAULT_FOLLOWUP_DAYS)

    return create_followup(
        db,
        application.user_id,
        application.id,
        due,
        kind=DEFAULT_FOLLOWUP_KIND,
        note=f"Check in {DEFAULT_FOLLOWUP_DAYS} days after submission.",
    )


__all__ = [
    "due_followups",
    "create_followup",
    "complete_followup",
    "notify_due_followups",
    "schedule_default_followup",
    "DEFAULT_FOLLOWUP_DAYS",
]

"""Application lifecycle: queue, preparation, policy-checked submission.

Two product rules are enforced here and nowhere else:

* **LinkedIn stays a manual lane.** There is no automated LinkedIn submission
  path. Marking a LinkedIn application submitted requires the user to state
  explicitly that they submitted it themselves.
* **The daily application cap is a hard limit**, not a suggestion.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, PolicyError, ValidationError
from app.db.models.applications import (
    Application,
    ApplicationAnswer,
    ApplicationAsset,
    ApplicationStatusHistory,
)
from app.db.models.enums import (
    ApplicationChannel,
    ApplicationStatus,
    AssetType,
    TERMINAL_APPLICATION_STATUSES,
)
from app.db.models.jobs import Job
from app.db.models.preferences import JobPreference
from app.services import audit

logger = logging.getLogger(__name__)

# Allowed status transitions. Anything absent is rejected, so the tracker can
# never end up in a state the UI does not know how to render.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ApplicationStatus.PENDING_REVIEW: {
        ApplicationStatus.APPROVED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.APPROVED: {
        ApplicationStatus.PREPARED,
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.FAILED,
    },
    ApplicationStatus.PREPARED: {
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.FAILED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.REJECTED,
    },
    ApplicationStatus.SUBMITTED: {
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
        ApplicationStatus.CLOSED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.OFFER,
    },
    ApplicationStatus.INTERVIEW: {
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
        ApplicationStatus.CLOSED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.OFFER: {
        ApplicationStatus.CLOSED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.WITHDRAWN,
    },
    ApplicationStatus.FAILED: {
        ApplicationStatus.APPROVED,
        ApplicationStatus.WITHDRAWN,
        ApplicationStatus.CLOSED,
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def submissions_today(db: Session, user_id: str) -> int:
    start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    return int(
        db.execute(
            select(func.count(Application.id)).where(
                Application.user_id == user_id,
                Application.submitted_at.is_not(None),
                Application.submitted_at >= start,
            )
        ).scalar_one()
    )


def cap_status(db: Session, user_id: str, prefs: JobPreference) -> dict[str, int]:
    used = submissions_today(db, user_id)
    cap = int(prefs.daily_application_cap or 0)
    return {"used_today": used, "cap": cap, "remaining": max(0, cap - used) if cap else 0}


def get_owned(db: Session, user_id: str, application_id: str) -> Application:
    application = db.get(Application, application_id)
    if application is None or application.user_id != user_id:
        raise NotFoundError("That application does not exist.")
    return application


def transition(
    db: Session,
    application: Application,
    to_status: str,
    *,
    reason: str = "",
    actor: str = "system",
) -> Application:
    """Move an application to a new status, recording the change."""
    from_status = application.status
    if from_status == to_status:
        return application

    allowed = ALLOWED_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise ConflictError(
            f"An application cannot move from {from_status} to {to_status}.",
            details={"allowed": sorted(allowed)},
        )

    application.status = to_status
    if to_status == ApplicationStatus.APPROVED:
        application.approved_at = _now()
        application.approved_by = actor
    elif to_status == ApplicationStatus.SUBMITTED:
        application.submitted_at = _now()
    elif to_status in TERMINAL_APPLICATION_STATUSES:
        application.closed_at = _now()
        if to_status == ApplicationStatus.REJECTED and reason:
            application.outcome_reason = reason

    db.add(
        ApplicationStatusHistory(
            application_id=application.id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            actor=actor,
        )
    )
    audit.record(
        db,
        action="application.status",
        user_id=application.user_id,
        actor=actor,
        entity_type="application",
        entity_id=application.id,
        summary=f"{from_status} -> {to_status}" + (f": {reason}" if reason else ""),
    )
    return application


def create(
    db: Session,
    user_id: str,
    job: Job,
    prefs: JobPreference,
    *,
    resume_version_id: str | None = None,
    channel: str = ApplicationChannel.MANUAL,
    notes: str = "",
    match_score: float | None = None,
    actor: str = "user",
) -> Application:
    """Queue an application for a job, refusing duplicates."""
    existing = db.execute(
        select(Application).where(
            Application.user_id == user_id,
            Application.job_id == job.id,
            Application.status.not_in(
                [ApplicationStatus.WITHDRAWN, ApplicationStatus.REJECTED]
            ),
        )
    ).scalars().first()
    if existing is not None:
        raise ConflictError(
            f"An application for this job already exists with status {existing.status}.",
            details={"application_id": existing.id},
        )

    # With approval turned off the item still lands in the queue, just already
    # approved. Submission remains a separate, explicit act.
    initial = (
        ApplicationStatus.PENDING_REVIEW
        if prefs.approval_required
        else ApplicationStatus.APPROVED
    )

    application = Application(
        user_id=user_id,
        job_id=job.id,
        resume_version_id=resume_version_id,
        status=initial,
        channel=channel,
        match_score=match_score,
        notes=notes,
    )
    if initial == ApplicationStatus.APPROVED:
        application.approved_at = _now()
        application.approved_by = actor

    db.add(application)
    db.flush()

    db.add(
        ApplicationStatusHistory(
            application_id=application.id,
            from_status="",
            to_status=initial,
            reason="Queued",
            actor=actor,
        )
    )
    audit.job_event(
        db, job.id, "application_queued",
        message=f"Application queued ({initial})", actor=actor,
    )
    audit.record(
        db, action="application.create", user_id=user_id, actor=actor,
        entity_type="application", entity_id=application.id,
        summary=f"Queued an application for {job.title} at {job.company}",
    )
    return application


def prepare(
    db: Session,
    application: Application,
    job: Job,
    *,
    profile: Any = None,
    ai_service: Any = None,
    actor: str = "system",
) -> dict[str, Any]:
    """Generate assets and resolve answers ahead of submission."""
    from app.services.answers import resolve_answer

    warnings: list[str] = []
    generated: list[str] = []

    if application.status == ApplicationStatus.PENDING_REVIEW:
        raise ConflictError("Approve the application before preparing it.")

    # Cover letter, only when AI is available. Preparation must still work
    # without it, so a missing key is a warning rather than a failure.
    if ai_service is not None and getattr(ai_service, "enabled", False):
        try:
            from app.services.ai.functions import cover_letter

            data = cover_letter(db, ai_service, application.user_id, job, profile)
            for asset in application.assets:
                if asset.asset_type == AssetType.COVER_LETTER:
                    asset.is_current = False
            db.add(
                ApplicationAsset(
                    application_id=application.id,
                    asset_type=AssetType.COVER_LETTER,
                    content=str(data.get("letter", "")),
                    version=len([a for a in application.assets if a.asset_type == AssetType.COVER_LETTER]) + 1,
                    is_current=True,
                    generated_by="ai",
                    model_used=str((data.get("_meta") or {}).get("model", "")),
                    evidence_ids=[str(e) for e in (data.get("evidence_used") or [])],
                )
            )
            generated.append(AssetType.COVER_LETTER)
        except Exception as exc:
            logger.info("Cover letter generation failed for %s: %s", application.id, exc)
            warnings.append(f"The cover letter could not be generated: {exc}")
    else:
        warnings.append("AI is not configured, so no cover letter was generated.")

    # Resolve every stored question against this specific job.
    resolved = 0
    needs_review = 0
    existing_questions = {a.question for a in application.answers}

    from app.db.models.applications import AnswerBankEntry

    bank = db.execute(
        select(AnswerBankEntry).where(
            AnswerBankEntry.user_id == application.user_id,
            AnswerBankEntry.enabled.is_(True),
        )
    ).scalars().all()

    for entry in bank:
        if entry.question in existing_questions:
            continue
        outcome = resolve_answer(
            db,
            application.user_id,
            entry.question,
            job=job,
            profile=profile,
            ai_service=ai_service,
            allow_ai=False,
        )
        if not outcome.answer:
            continue
        db.add(
            ApplicationAnswer(
                application_id=application.id,
                question=outcome.question,
                answer=outcome.answer,
                state=str(outcome.state),
                confidence=outcome.confidence,
                resolved_from=outcome.resolved_from,
                answer_bank_id=outcome.answer_bank_id,
                evidence_ids=outcome.evidence_ids,
            )
        )
        resolved += 1
        if str(outcome.state) != "verified":
            needs_review += 1

    if application.status == ApplicationStatus.APPROVED:
        transition(db, application, ApplicationStatus.PREPARED, reason="Assets generated", actor=actor)

    audit.record(
        db, action="application.prepare", user_id=application.user_id, actor=actor,
        entity_type="application", entity_id=application.id,
        summary=f"Prepared: {len(generated)} assets, {resolved} answers resolved",
        after={"warnings": warnings},
    )
    return {
        "application_id": application.id,
        "assets_generated": generated,
        "answers_resolved": resolved,
        "answers_needing_review": needs_review,
        "warnings": warnings,
    }


def check_submission_policy(
    db: Session, application: Application, job: Job, prefs: JobPreference, *, confirmed: bool
) -> None:
    """Refuse submissions the product policy does not allow.

    Raises PolicyError with an explanation the UI shows verbatim.
    """
    # A cap of zero is a deliberate "pause submissions today", not "no cap
    # configured" -- so this must not be skipped just because 0 is falsy.
    status = cap_status(db, application.user_id, prefs)
    if status["used_today"] >= status["cap"]:
        raise PolicyError(
            f"The daily application cap of {status['cap']} has been reached. "
            "Raise the cap in Preferences or submit tomorrow.",
            code="daily_cap_reached",
        )

    if application.status == ApplicationStatus.PENDING_REVIEW:
        raise PolicyError(
            "This application still needs approval before it can be submitted.",
            code="approval_required",
        )

    channel = (application.channel or "").lower()
    source = (job.source_name or "").lower()

    # LinkedIn is an approval/manual lane only. There is no automated path,
    # and there will not be one without an officially authorized integration.
    if channel == ApplicationChannel.LINKEDIN or "linkedin" in source:
        if not confirmed:
            raise PolicyError(
                "LinkedIn applications are a manual lane. Apply on LinkedIn yourself, "
                "then confirm here to record it. This product does not automate "
                "LinkedIn submission.",
                code="linkedin_manual_only",
            )

    # Email is the one lane the agent may send through itself, because the
    # employer published that address to receive applications. It still needs a
    # published address; without one there is nothing legitimate to send to.
    if channel == ApplicationChannel.EMAIL and not confirmed:
        if not (job.application_email or "").strip():
            raise PolicyError(
                "This posting did not publish an application email address. Apply "
                "through the posting's own link, then confirm here to record it.",
                code="no_application_email",
            )

    if channel == ApplicationChannel.ATS and not confirmed:
        raise PolicyError(
            "No authorized automated integration is configured for this employer's "
            "system. Submit through their portal, then confirm here to record it.",
            code="no_authorized_integration",
        )

    if channel == ApplicationChannel.COMPANY_PORTAL and not confirmed:
        raise PolicyError(
            "Company portals are filled in by hand. Automating them would mean "
            "driving their forms headlessly, which this product does not do. "
            "Apply on the portal, then confirm here to record it.",
            code="portal_manual_only",
        )


def submit(
    db: Session,
    application: Application,
    job: Job,
    prefs: JobPreference,
    *,
    confirmed: bool = False,
    reference: str = "",
    actor: str = "user",
    profile: Any = None,
) -> Application:
    """Submit, or record a submission the user made themselves.

    For the email lane the agent actually sends. For every other lane
    ``confirmed`` means "I submitted this myself", and this only records it.
    """
    check_submission_policy(db, application, job, prefs, confirmed=confirmed)

    sent_automatically = False
    if application.channel == ApplicationChannel.EMAIL and not confirmed:
        from app.services.submission import submit_by_email

        result = submit_by_email(db, application, job, profile=profile, actor=actor)
        if not result.ok:
            # A failed send must not look like a successful application.
            application.failure_reason = result.message[:2000]
            transition(
                db,
                application,
                ApplicationStatus.FAILED,
                reason=result.message,
                actor=actor,
            )
            # Committing here is deliberate, and the one place this service
            # manages the transaction itself. A delivery attempt genuinely
            # happened, so the FAILED status and its audit rows have to
            # survive. Raising instead would unwind them: the request-scoped
            # session rolls back on any exception leaving a route, which would
            # erase the very record that explains what went wrong.
            db.commit()
            raise PolicyError(result.message, code="submission_failed", status_code=502)
        sent_automatically = True
        reference = reference or result.reference

    how = "Emailed by the agent" if sent_automatically else f"Submitted via {application.channel}"
    transition(
        db,
        application,
        ApplicationStatus.SUBMITTED,
        reason=how + (f" ({reference})" if reference else ""),
        actor=actor,
    )
    if reference:
        application.notes = f"{application.notes}\nReference: {reference}".strip()

    job.status = "applied"
    audit.job_event(
        db, job.id, "application_submitted",
        message=f"Submitted via {application.channel}", actor=actor,
    )

    from app.services.followups import schedule_default_followup

    try:
        schedule_default_followup(db, application)
    except Exception as exc:
        logger.info("Could not schedule a follow-up for %s: %s", application.id, exc)

    return application

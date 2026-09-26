"""Application submission.

There is exactly one lane the agent may submit through on its own: **email**,
and only to an address the employer itself published in the posting. That is a
channel explicitly offered for receiving applications, so using it is ordinary
automation rather than circumvention.

Every other lane stays manual by design (spec section 0, rules 6 and 7):

* LinkedIn has no automated path here and will not get one without an
  officially authorized integration.
* Portal / ATS forms are not driven headlessly, because doing so means working
  around bot protection and risks the user's account.

For those, the product prepares everything and the user submits, then records
the outcome. That distinction is enforced in ``check_submission_policy``.
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.applications import Application, ApplicationAsset
from app.db.models.enums import ApplicationChannel, AssetType
from app.db.models.jobs import Job
from app.db.models.resumes import ResumeVersion
from app.services import audit, secrets
from app.services.resume import storage

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 20


@dataclass(slots=True)
class SubmissionResult:
    ok: bool
    message: str = ""
    channel: str = ""
    reference: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutgoingApplication:
    to_address: str
    subject: str
    body: str
    attachment_path: str | None = None
    attachment_name: str = ""


def _smtp_settings(db: Session, user_id: str) -> dict[str, Any]:
    """Resolve SMTP settings, preferring a stored credential over the env."""
    password = secrets.resolve(db, user_id, "smtp_password") or settings.smtp_password
    return {
        "host": (settings.smtp_host or "").strip(),
        "port": int(settings.smtp_port or 587),
        "username": (settings.smtp_user or "").strip(),
        "from_address": (settings.smtp_from or settings.smtp_user or "").strip(),
        "password": password or "",
    }


def smtp_problems(config: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if not config["host"]:
        problems.append("SMTP_HOST is not set.")
    if not config["from_address"]:
        problems.append("SMTP_FROM (or SMTP_USER) is not set.")
    if config["username"] and not config["password"]:
        problems.append("No SMTP password is stored for that username.")
    return problems


def current_asset(application: Application, asset_type: str) -> ApplicationAsset | None:
    for asset in application.assets:
        if asset.asset_type == asset_type and asset.is_current:
            return asset
    return None


def build_email(
    db: Session,
    application: Application,
    job: Job,
    profile: Any = None,
) -> OutgoingApplication:
    """Compose the application email from what was already prepared.

    The cover letter generated during preparation is the body. Nothing new is
    written at submission time, so what the user reviewed is what is sent.
    """
    letter_asset = current_asset(application, AssetType.COVER_LETTER)
    candidate_name = getattr(profile, "full_name", "") or ""

    if letter_asset and letter_asset.content.strip():
        body = letter_asset.content.strip()
    else:
        # A plain, factual fallback. It claims nothing beyond the application.
        body = (
            f"Hello,\n\nI would like to apply for the {job.title} role"
            f"{f' at {job.company}' if job.company else ''}. "
            "My resume is attached.\n\n"
            f"{'Best regards,' if candidate_name else 'Best regards'}\n{candidate_name}".strip()
        )

    subject = f"Application: {job.title}"
    if candidate_name:
        subject = f"{subject} — {candidate_name}"

    attachment_path: str | None = None
    attachment_name = ""
    if application.resume_version_id:
        version = db.get(ResumeVersion, application.resume_version_id)
        if version and version.storage_path:
            try:
                resolved = storage.resolve_stored_path(version.storage_path)
                attachment_path = str(resolved)
                attachment_name = version.original_filename or resolved.name
            except storage.UploadRejected as exc:
                logger.warning(
                    "Resume file for application %s is unavailable: %s", application.id, exc
                )

    return OutgoingApplication(
        to_address=job.application_email,
        subject=subject,
        body=body,
        attachment_path=attachment_path,
        attachment_name=attachment_name,
    )


def _deliver(config: dict[str, Any], outgoing: OutgoingApplication) -> SubmissionResult:
    mail = EmailMessage()
    mail["Subject"] = outgoing.subject
    mail["From"] = config["from_address"]
    mail["To"] = outgoing.to_address
    mail.set_content(outgoing.body)

    if outgoing.attachment_path:
        try:
            data = Path(outgoing.attachment_path).read_bytes()
            subtype = "pdf" if outgoing.attachment_name.lower().endswith(".pdf") else (
                "vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            mail.add_attachment(
                data,
                maintype="application",
                subtype=subtype,
                filename=outgoing.attachment_name or "resume.pdf",
            )
        except OSError as exc:
            return SubmissionResult(
                ok=False,
                message=f"The resume file could not be read: {exc}",
                channel=ApplicationChannel.EMAIL,
            )

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=SMTP_TIMEOUT_SECONDS) as client:
            client.ehlo()
            try:
                client.starttls()
                client.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass
            if config["username"]:
                client.login(config["username"], config["password"])
            client.send_message(mail)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, never raised
        return SubmissionResult(
            ok=False,
            message=f"Sending failed: {type(exc).__name__}: {exc}",
            channel=ApplicationChannel.EMAIL,
        )

    return SubmissionResult(
        ok=True,
        message=f"Application emailed to {outgoing.to_address}.",
        channel=ApplicationChannel.EMAIL,
        reference=outgoing.to_address,
        details={"attached": bool(outgoing.attachment_path)},
    )


def can_auto_submit(job: Job, application: Application) -> tuple[bool, str]:
    """Whether this application is eligible for the automated email lane."""
    if application.channel != ApplicationChannel.EMAIL:
        return (False, f"The {application.channel} channel is manual by design.")
    if not job.application_email:
        return (
            False,
            "This posting did not publish an application email address, so there is "
            "nothing to send to.",
        )
    return (True, "")


def submit_by_email(
    db: Session,
    application: Application,
    job: Job,
    *,
    profile: Any = None,
    actor: str = "system",
) -> SubmissionResult:
    """Send the prepared application to the employer's published address."""
    eligible, reason = can_auto_submit(job, application)
    if not eligible:
        return SubmissionResult(ok=False, message=reason, channel=application.channel)

    config = _smtp_settings(db, application.user_id)
    problems = smtp_problems(config)
    if problems:
        return SubmissionResult(
            ok=False,
            message="Email is not configured: " + " ".join(problems),
            channel=ApplicationChannel.EMAIL,
        )

    outgoing = build_email(db, application, job, profile)
    result = _deliver(config, outgoing)

    audit.record(
        db,
        action="application.submit.email",
        user_id=application.user_id,
        actor=actor,
        entity_type="application",
        entity_id=application.id,
        summary=(
            f"Emailed application for {job.title} to {outgoing.to_address}"
            if result.ok
            else f"Email submission failed: {result.message}"
        ),
        success=result.ok,
    )
    audit.job_event(
        db,
        job.id,
        "application_emailed" if result.ok else "application_email_failed",
        message=result.message,
        actor=actor,
    )
    return result

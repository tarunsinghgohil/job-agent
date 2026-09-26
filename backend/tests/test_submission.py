"""Submission policy and the email auto-apply lane.

The rules being protected here are product policy, not implementation detail:
email may be sent automatically, everything else stays manual, and nothing goes
out past the daily cap or without approval.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.errors import PolicyError
from app.db.models.applications import Application
from app.db.models.enums import ApplicationChannel, ApplicationStatus
from app.db.models.jobs import Job
from app.db.models.preferences import JobPreference
from app.services.applications import check_submission_policy, submit
from app.services.normalize import extract_application_email
from app.services.submission import build_email, can_auto_submit


# --------------------------------------------------------------------------
# Address extraction
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Send your resume to careers@acme.com", "careers@acme.com"),
        ("Email your CV to jobs@acme.io today", "jobs@acme.io"),
        ("Apply: hiring@startup.dev", "hiring@startup.dev"),
        ("Questions? support@acme.com", ""),
        ("Contact privacy@acme.com about data", ""),
        ("Reach out to talent@acme.com", "talent@acme.com"),
        ("No address here at all", ""),
        ("", ""),
    ],
)
def test_extract_application_email(text, expected):
    assert extract_application_email(text) == expected


def test_a_recruiting_mailbox_is_trusted_without_context():
    """'careers@' is unambiguous even on a line with no apply wording."""
    assert extract_application_email("careers@acme.com") == "careers@acme.com"


def test_a_plain_address_without_context_is_ignored():
    """Being conservative matters: this address is what a bot would email."""
    assert extract_application_email("Our CEO is jane.doe@acme.com") == ""


def test_support_mailbox_is_never_treated_as_an_application_address():
    assert extract_application_email("Send your resume to support@acme.com") == ""


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------
def _job(**kwargs) -> Job:
    defaults = {
        "user_id": "u1",
        "title": "Frontend Developer",
        "company": "Acme",
        "application_email": "careers@acme.com",
        "source_name": "remotive",
    }
    defaults.update(kwargs)
    return Job(**defaults)


def _application(**kwargs) -> Application:
    defaults = {
        "user_id": "u1",
        "job_id": "j1",
        "status": ApplicationStatus.APPROVED,
        "channel": ApplicationChannel.EMAIL,
    }
    defaults.update(kwargs)
    return Application(**defaults)


def test_email_lane_with_published_address_is_eligible():
    ok, reason = can_auto_submit(_job(), _application())
    assert ok is True
    assert reason == ""


def test_email_lane_without_an_address_is_not_eligible():
    ok, reason = can_auto_submit(_job(application_email=""), _application())
    assert ok is False
    assert "did not publish" in reason


@pytest.mark.parametrize(
    "channel",
    [
        ApplicationChannel.LINKEDIN,
        ApplicationChannel.ATS,
        ApplicationChannel.COMPANY_PORTAL,
        ApplicationChannel.MANUAL,
    ],
)
def test_no_other_channel_is_ever_auto_submittable(channel):
    ok, reason = can_auto_submit(_job(), _application(channel=channel))
    assert ok is False
    assert "manual" in reason.lower()


# --------------------------------------------------------------------------
# Policy gate
# --------------------------------------------------------------------------
def _prefs(**kwargs) -> JobPreference:
    defaults = {"user_id": "u1", "daily_application_cap": 8, "approval_required": False}
    defaults.update(kwargs)
    return JobPreference(**defaults)


def test_linkedin_requires_explicit_manual_confirmation(db):
    with pytest.raises(PolicyError) as exc:
        check_submission_policy(
            db,
            _application(channel=ApplicationChannel.LINKEDIN),
            _job(),
            _prefs(),
            confirmed=False,
        )
    assert exc.value.code == "linkedin_manual_only"


def test_company_portal_requires_manual_confirmation(db):
    with pytest.raises(PolicyError) as exc:
        check_submission_policy(
            db,
            _application(channel=ApplicationChannel.COMPANY_PORTAL),
            _job(),
            _prefs(),
            confirmed=False,
        )
    assert exc.value.code == "portal_manual_only"


def test_email_without_a_published_address_is_refused(db):
    with pytest.raises(PolicyError) as exc:
        check_submission_policy(
            db, _application(), _job(application_email=""), _prefs(), confirmed=False
        )
    assert exc.value.code == "no_application_email"


def test_email_with_a_published_address_passes_the_gate(db):
    check_submission_policy(db, _application(), _job(), _prefs(), confirmed=False)


def test_unapproved_application_cannot_be_submitted(db):
    with pytest.raises(PolicyError) as exc:
        check_submission_policy(
            db,
            _application(status=ApplicationStatus.PENDING_REVIEW),
            _job(),
            _prefs(),
            confirmed=False,
        )
    assert exc.value.code == "approval_required"


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------
def test_email_body_uses_the_prepared_cover_letter(db, engine):
    from sqlalchemy.orm import sessionmaker

    from app.db.models.applications import ApplicationAsset
    from app.db.models.enums import AssetType

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        application = _application()
        session.add(application)
        session.flush()
        session.add(
            ApplicationAsset(
                application_id=application.id,
                asset_type=AssetType.COVER_LETTER,
                content="I am a strong fit because of X and Y.",
                is_current=True,
            )
        )
        session.flush()
        session.refresh(application)

        outgoing = build_email(session, application, _job(), None)
        assert outgoing.body == "I am a strong fit because of X and Y."
        assert outgoing.to_address == "careers@acme.com"
        assert "Frontend Developer" in outgoing.subject
    finally:
        session.close()


def test_email_falls_back_to_a_plain_body_with_no_cover_letter(db, engine):
    from sqlalchemy.orm import sessionmaker

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        application = _application()
        session.add(application)
        session.flush()
        session.refresh(application)

        outgoing = build_email(session, application, _job(), None)
        # The fallback must not assert anything about the candidate.
        assert "Frontend Developer" in outgoing.body
        assert "resume is attached" in outgoing.body
    finally:
        session.close()


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------
def test_failed_send_marks_the_application_failed_not_submitted(db, engine):
    """A bounced send must never look like a delivered application."""
    from sqlalchemy.orm import sessionmaker

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        job = _job()
        session.add(job)
        session.flush()
        application = _application(job_id=job.id)
        session.add(application)
        session.flush()

        with patch("app.services.submission._deliver") as deliver:
            from app.services.submission import SubmissionResult

            deliver.return_value = SubmissionResult(ok=False, message="SMTP refused the recipient.")
            with patch("app.services.submission._smtp_settings") as smtp_config:
                smtp_config.return_value = {
                    "host": "smtp.test", "port": 587, "username": "u",
                    "from_address": "me@test", "password": "p",
                }
                with pytest.raises(PolicyError) as exc:
                    submit(session, application, job, _prefs(), confirmed=False)

        assert exc.value.code == "submission_failed"
        assert application.status == ApplicationStatus.FAILED
        assert application.submitted_at is None
        assert "SMTP refused" in application.failure_reason
    finally:
        session.close()


def test_successful_send_marks_submitted(db, engine):
    from sqlalchemy.orm import sessionmaker

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        job = _job()
        session.add(job)
        session.flush()
        application = _application(job_id=job.id)
        session.add(application)
        session.flush()

        with patch("app.services.submission._deliver") as deliver:
            from app.services.submission import SubmissionResult

            deliver.return_value = SubmissionResult(
                ok=True, message="sent", reference="careers@acme.com"
            )
            with patch("app.services.submission._smtp_settings") as smtp_config:
                smtp_config.return_value = {
                    "host": "smtp.test", "port": 587, "username": "u",
                    "from_address": "me@test", "password": "p",
                }
                submit(session, application, job, _prefs(), confirmed=False)

        assert application.status == ApplicationStatus.SUBMITTED
        assert application.submitted_at is not None
    finally:
        session.close()


def test_unconfigured_smtp_fails_loudly_rather_than_silently(db, engine):
    from sqlalchemy.orm import sessionmaker

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        job = _job()
        session.add(job)
        session.flush()
        application = _application(job_id=job.id)
        session.add(application)
        session.flush()

        # No SMTP host configured at all.
        with patch("app.services.submission._smtp_settings") as smtp_config:
            smtp_config.return_value = {
                "host": "", "port": 587, "username": "", "from_address": "", "password": "",
            }
            with pytest.raises(PolicyError) as exc:
                submit(session, application, job, _prefs(), confirmed=False)

        assert "not configured" in str(exc.value).lower()
        assert application.status == ApplicationStatus.FAILED
    finally:
        session.close()


# --------------------------------------------------------------------------
# Auto-apply agent gating
# --------------------------------------------------------------------------
def test_auto_apply_refuses_while_approval_is_required(db, engine):
    from sqlalchemy.orm import sessionmaker

    from app.agents.wiring import run_auto_apply

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        session.add(
            JobPreference(
                user_id="u1", auto_submit_enabled=True, approval_required=True,
                daily_application_cap=8,
            )
        )
        session.flush()
        result = run_auto_apply(session, "u1", {})
        assert result["items_succeeded"] == 0
        assert "approval" in result["skipped_reason"].lower()
    finally:
        session.close()


def test_auto_apply_refuses_while_auto_submit_is_off(db, engine):
    from sqlalchemy.orm import sessionmaker

    from app.agents.wiring import run_auto_apply

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        session.add(
            JobPreference(
                user_id="u2", auto_submit_enabled=False, approval_required=False,
                daily_application_cap=8,
            )
        )
        session.flush()
        result = run_auto_apply(session, "u2", {})
        assert result["items_succeeded"] == 0
        assert "switched off" in result["skipped_reason"].lower()
    finally:
        session.close()


def test_auto_apply_respects_an_exhausted_daily_cap(db, engine):
    from sqlalchemy.orm import sessionmaker

    from app.agents.wiring import run_auto_apply

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        session.add(
            JobPreference(
                user_id="u3", auto_submit_enabled=True, approval_required=False,
                daily_application_cap=0,
            )
        )
        session.flush()
        result = run_auto_apply(session, "u3", {})
        assert result["items_succeeded"] == 0
        assert "cap" in result["skipped_reason"].lower()
    finally:
        session.close()


def test_auto_apply_agent_is_created_disabled(db, engine):
    """The one agent that emails employers must not be on by default."""
    from sqlalchemy.orm import sessionmaker

    from app.agents.registry import ensure_agent_definitions

    maker = sessionmaker(bind=engine, future=True)
    session = maker()
    try:
        definitions = {d.key: d for d in ensure_agent_definitions(session, "u4")}
        assert definitions["auto_apply"].enabled is False
        assert definitions["discovery"].enabled is True
    finally:
        session.close()

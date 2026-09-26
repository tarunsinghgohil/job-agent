"""Tests for notification dispatch policy, follow-ups, and scheduler reconciliation.

Everything runs against an in-memory SQLite database with in-memory notification
adapters: no SMTP connection, no HTTP request, and no wall-clock dependence -- the
clock is injected so quiet-hour windows can be tested deterministically.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base
from app.db.models.applications import Application, FollowUp
from app.db.models.automation import Schedule
from app.db.models.enums import NotificationEventType, NotificationStatus
from app.db.models.identity import User
from app.db.models.jobs import Job
from app.db.models.ops import NotificationChannel, NotificationEvent, NotificationPreference
from app.services import scheduler as scheduler_module
from app.services.followups import notify_due_followups
from app.services.notifications import service as notifications
from app.services.notifications.base import (
    DeliveryResult,
    NotificationAdapter,
    NotificationMessage,
    get_channel_adapter,
    list_channels,
    register_channel,
)

IST_OFFSET_HOURS = 5.5


class MemoryChannel(NotificationAdapter):
    """Records deliveries instead of performing them."""

    channel_type = "memory"
    display_name = "In-memory test channel"
    requires_credential = False
    config_schema = []

    sent: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> DeliveryResult:
        MemoryChannel.sent.append(message)
        return DeliveryResult(ok=True, message="recorded")

    def test(self) -> DeliveryResult:
        return DeliveryResult(ok=True, message="recorded")


class ExplodingChannel(NotificationAdapter):
    """Simulates an adapter bug: raises instead of returning a failure result."""

    channel_type = "exploding"
    display_name = "Exploding test channel"
    requires_credential = False
    config_schema = []

    def send(self, message: NotificationMessage) -> DeliveryResult:
        raise RuntimeError("channel exploded")

    def test(self) -> DeliveryResult:
        raise RuntimeError("channel exploded")


register_channel(MemoryChannel)
register_channel(ExplodingChannel)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, future=True)()
    MemoryChannel.sent.clear()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def user(db) -> User:
    person = User(email="owner@example.com", password_hash="hashed", full_name="Owner")
    db.add(person)
    db.flush()
    return person


def add_channel(db, user_id: str, channel_type: str = "memory", **config) -> NotificationChannel:
    channel = NotificationChannel(
        user_id=user_id, channel_type=channel_type, enabled=True, config=config
    )
    db.add(channel)
    db.flush()
    return channel


def add_preference(db, user_id: str, **kwargs) -> NotificationPreference:
    pref = NotificationPreference(user_id=user_id, **kwargs)
    db.add(pref)
    db.flush()
    return pref


def freeze(monkeypatch, moment: datetime) -> None:
    monkeypatch.setattr(notifications, "_utcnow", lambda: moment)


def ist(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """A UTC instant that corresponds to the given Asia/Kolkata wall clock."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc) - timedelta(
        hours=IST_OFFSET_HOURS
    )


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("start", "end", "local_hour", "expected"),
    [
        ("22:00", "07:00", 23, True),
        ("22:00", "07:00", 3, True),
        ("22:00", "07:00", 6, True),
        ("22:00", "07:00", 7, False),
        ("22:00", "07:00", 12, False),
        ("22:00", "07:00", 21, False),
        ("09:00", "17:00", 12, True),
        ("09:00", "17:00", 8, False),
        ("", "", 3, False),
    ],
)
def test_quiet_hours_window(db, user, start, end, local_hour, expected):
    pref = add_preference(db, user.id, quiet_hours_start=start, quiet_hours_end=end)
    assert notifications.in_quiet_hours(pref, ist(2026, 5, 10, local_hour)) is expected


def test_quiet_hours_suppresses_instead_of_sending(db, user, monkeypatch):
    add_preference(db, user.id, quiet_hours_start="22:00", quiet_hours_end="07:00")
    add_channel(db, user.id)
    freeze(monkeypatch, ist(2026, 5, 10, 23, 30))

    events = notifications.dispatch(
        db, user.id, NotificationEventType.HIGH_MATCH_JOB.value, "New match", "A job scored 94."
    )

    assert [e.status for e in events] == [NotificationStatus.SUPPRESSED.value]
    assert MemoryChannel.sent == []


def test_failure_event_ignores_quiet_hours(db, user, monkeypatch):
    add_preference(db, user.id, quiet_hours_start="22:00", quiet_hours_end="07:00")
    add_channel(db, user.id)
    freeze(monkeypatch, ist(2026, 5, 10, 2, 15))

    events = notifications.dispatch(
        db,
        user.id,
        NotificationEventType.INTEGRATION_FAILED.value,
        "Source down",
        "Remotive returned 500.",
    )

    assert [e.status for e in events] == [NotificationStatus.SENT.value]
    assert len(MemoryChannel.sent) == 1


# ---------------------------------------------------------------------------
# Routing and de-duplication
# ---------------------------------------------------------------------------
def test_routing_falls_back_to_every_enabled_channel(db, user):
    add_preference(db, user.id, event_routing={})
    add_channel(db, user.id, "memory")
    add_channel(db, user.id, "exploding")

    events = notifications.dispatch(
        db, user.id, NotificationEventType.DAILY_DIGEST.value, "Digest", "Body"
    )

    assert {e.channel_type for e in events} == {"memory", "exploding"}


def test_explicit_routing_limits_channels(db, user):
    add_preference(
        db,
        user.id,
        event_routing={NotificationEventType.DAILY_DIGEST.value: ["memory"]},
    )
    add_channel(db, user.id, "memory")
    add_channel(db, user.id, "exploding")

    events = notifications.dispatch(
        db, user.id, NotificationEventType.DAILY_DIGEST.value, "Digest", "Body"
    )

    assert [e.channel_type for e in events] == ["memory"]


def test_failures_only_mutes_routine_events_but_not_failures(db, user):
    add_preference(db, user.id, event_routing={}, failures_only=True)
    add_channel(db, user.id)

    routine = notifications.dispatch(
        db, user.id, NotificationEventType.DAILY_DIGEST.value, "Digest", "Body"
    )
    failure = notifications.dispatch(
        db, user.id, NotificationEventType.SCHEDULED_RUN_FAILED.value, "Run failed", "Boom"
    )

    assert routine == []
    assert [e.status for e in failure] == [NotificationStatus.SENT.value]


def test_dedupe_key_suppresses_repeat_within_24h(db, user):
    add_preference(db, user.id)
    add_channel(db, user.id)

    first = notifications.dispatch(
        db,
        user.id,
        NotificationEventType.HIGH_MATCH_JOB.value,
        "Match",
        "Body",
        dedupe_key="job:abc",
    )
    second = notifications.dispatch(
        db,
        user.id,
        NotificationEventType.HIGH_MATCH_JOB.value,
        "Match",
        "Body",
        dedupe_key="job:abc",
    )

    assert len(first) == 1
    assert second == []
    stored = db.scalars(
        select(NotificationEvent).where(NotificationEvent.dedupe_key == "job:abc")
    ).all()
    assert len(stored) == 1
    assert len(MemoryChannel.sent) == 1


def test_dedupe_does_not_block_a_different_key(db, user):
    add_preference(db, user.id)
    add_channel(db, user.id)

    notifications.dispatch(db, user.id, "high_match_job", "A", "B", dedupe_key="job:1")
    events = notifications.dispatch(db, user.id, "high_match_job", "A", "B", dedupe_key="job:2")

    assert len(events) == 1


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------
def test_broken_channel_is_recorded_and_does_not_raise(db, user):
    add_preference(db, user.id)
    add_channel(db, user.id, "exploding")
    add_channel(db, user.id, "memory")

    events = notifications.dispatch(
        db, user.id, NotificationEventType.APPLICATION_READY.value, "Ready", "Body"
    )

    by_channel = {e.channel_type: e for e in events}
    assert by_channel["exploding"].status == NotificationStatus.FAILED.value
    assert "channel exploded" in by_channel["exploding"].error
    assert by_channel["exploding"].attempts == 1
    assert by_channel["memory"].status == NotificationStatus.SENT.value


def test_dispatch_without_channels_returns_empty(db, user):
    add_preference(db, user.id)
    assert notifications.dispatch(db, user.id, "daily_digest", "S", "B") == []


def test_test_channel_reports_and_records(db, user):
    channel = add_channel(db, user.id, "memory")
    result = notifications.test_channel(db, user.id, "memory")

    assert result.ok is True
    assert channel.last_test_ok is True
    assert channel.last_test_at is not None


def test_test_channel_for_missing_channel_is_not_an_error(db, user):
    result = notifications.test_channel(db, user.id, "telegram")
    assert result.ok is False
    assert "telegram" in result.message


# ---------------------------------------------------------------------------
# Adapters degrade instead of raising
# ---------------------------------------------------------------------------
def test_builtin_channels_are_registered():
    types = {entry["channel_type"] for entry in list_channels()}
    assert {"email", "telegram", "slack", "whatsapp"} <= types
    for entry in list_channels():
        assert isinstance(entry["config_schema"], list)


@pytest.mark.parametrize("channel_type", ["email", "telegram", "slack", "whatsapp"])
def test_unconfigured_adapter_returns_failure_without_network(channel_type):
    adapter = get_channel_adapter(channel_type, {}, None)
    result = adapter.send(
        NotificationMessage(subject="s", body="b", event_type="daily_digest")
    )
    assert result.ok is False
    assert "not configured" in result.message


def test_whatsapp_template_placeholders_render():
    from app.services.notifications.whatsapp_channel import render_template

    rendered = render_template(
        {"to": "{{to}}", "text": {"body": "{{message}}"}},
        {"to": "919876543210", "message": "hello"},
    )
    assert rendered == {"to": "919876543210", "text": {"body": "hello"}}


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------
def test_daily_digest_is_none_when_nothing_happened(db, user):
    add_preference(db, user.id)
    assert notifications.render_daily_digest(db, user.id) is None


def test_daily_digest_summarises_new_jobs(db, user):
    add_preference(db, user.id)
    db.add(Job(user_id=user.id, title="React Developer", company="Acme", dedupe_key="j1"))
    db.flush()

    message = notifications.render_daily_digest(db, user.id)

    assert message is not None
    assert message.payload["new_jobs"] == 1
    assert message.event_type == NotificationEventType.DAILY_DIGEST.value


# ---------------------------------------------------------------------------
# Follow-ups
# ---------------------------------------------------------------------------
def make_application(db, user_id: str) -> Application:
    job = Job(user_id=user_id, title="React Developer", company="Acme", dedupe_key="job-1")
    db.add(job)
    db.flush()
    application = Application(user_id=user_id, job_id=job.id, status="submitted")
    db.add(application)
    db.flush()
    return application


def test_notify_due_followups_marks_notified_at(db, user):
    add_preference(db, user.id)
    add_channel(db, user.id)
    application = make_application(db, user.id)
    followup = FollowUp(
        user_id=user.id,
        application_id=application.id,
        due_date=date.today() - timedelta(days=1),
        kind="check_in",
    )
    db.add(followup)
    db.flush()

    sent = notify_due_followups(db, user.id)

    assert sent == 1
    assert followup.notified_at is not None
    assert len(MemoryChannel.sent) == 1
    assert "React Developer" in MemoryChannel.sent[0].subject


def test_notify_due_followups_is_not_repeated(db, user):
    add_preference(db, user.id)
    add_channel(db, user.id)
    application = make_application(db, user.id)
    db.add(
        FollowUp(
            user_id=user.id,
            application_id=application.id,
            due_date=date.today(),
            kind="check_in",
        )
    )
    db.flush()

    assert notify_due_followups(db, user.id) == 1
    assert notify_due_followups(db, user.id) == 0
    assert len(MemoryChannel.sent) == 1


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
@pytest.fixture()
def sched(db, monkeypatch):
    @contextmanager
    def fake_scope():
        yield db
        db.flush()

    monkeypatch.setattr(scheduler_module, "session_scope", fake_scope)
    instance = scheduler_module.AgentScheduler()
    try:
        yield instance
    finally:
        instance.shutdown()


def add_schedule(db, user_id: str, key: str, cron: str = "0 8 * * *") -> Schedule:
    row = Schedule(
        user_id=user_id,
        key=key,
        cron=cron,
        timezone="Asia/Kolkata",
        enabled=True,
        agent_key="notification",
    )
    db.add(row)
    db.flush()
    return row


def test_reconcile_is_idempotent(db, user, sched):
    add_schedule(db, user.id, "daily_discovery")
    add_schedule(db, user.id, "daily_digest", cron="0 9 * * *")

    sched.reconcile()
    sched.reconcile()
    sched.reconcile()

    assert sched.job_ids() == sorted(
        [f"{user.id}:daily_discovery", f"{user.id}:daily_digest"]
    )


def test_reconcile_drops_jobs_for_disabled_schedules(db, user, sched):
    row = add_schedule(db, user.id, "daily_digest")
    sched.reconcile()
    assert len(sched.job_ids()) == 1

    row.enabled = False
    db.flush()
    sched.reconcile()

    assert sched.job_ids() == []


def test_malformed_cron_is_recorded_and_others_still_schedule(db, user, sched):
    broken = add_schedule(db, user.id, "broken", cron="not a cron at all")
    add_schedule(db, user.id, "healthy", cron="0 9 * * *")

    sched.reconcile()

    assert broken.last_status == scheduler_module.INVALID_CRON_STATUS
    assert sched.job_ids() == [f"{user.id}:healthy"]


def test_next_run_for_uses_the_cron(db, user, sched):
    add_schedule(db, user.id, "daily_digest", cron="0 9 * * *")
    sched.reconcile()

    upcoming = sched.next_run_for(user.id, "daily_digest")

    assert upcoming is not None
    assert upcoming > datetime.now(timezone.utc)
    assert sched.next_run_for(user.id, "missing") is None


def test_run_now_records_an_agent_run(db, user, sched):
    add_preference(db, user.id)
    add_channel(db, user.id)
    add_schedule(db, user.id, "daily_digest", cron="0 9 * * *")
    db.add(Job(user_id=user.id, title="React Developer", company="Acme", dedupe_key="j9"))
    db.flush()

    run_id = sched.run_now(user.id, "daily_digest")

    from app.db.models.automation import AgentRun

    run = db.get(AgentRun, run_id)
    assert run is not None
    assert run.agent_key == "notification"
    assert run.status == "success"
    assert run.finished_at is not None
    assert len(MemoryChannel.sent) == 1


def test_agent_failure_is_recorded_not_raised(db, user, sched):
    from app.agents.registry import run_agent

    run = run_agent(db, user.id, "discovery")

    assert run.status == "failed"
    assert "wired in" in run.error
    assert run.steps[0].status == "failed"


def test_bootstrap_schedules_seeds_rows_without_a_ui_visit(db, user):
    """Regression test: schedule rows used to only appear once a user opened
    the Automations screen (which calls the same sync as a side effect of a
    GET). Until then the scheduler had nothing to reconcile and no agent ever
    fired on its own cron. bootstrap_schedules must seed every agent's
    schedule row up front, at process startup, with no UI interaction."""
    from app.agents.registry import bootstrap_schedules, list_agent_specs

    touched = bootstrap_schedules(db)

    specs_with_cron = [s for s in list_agent_specs() if s.default_cron]
    rows = db.execute(select(Schedule).where(Schedule.user_id == user.id)).scalars().all()

    assert touched == len(specs_with_cron)
    assert {row.key for row in rows} == {s.key for s in specs_with_cron}
    assert all(row.cron == s.default_cron for row, s in zip(
        sorted(rows, key=lambda r: r.key), sorted(specs_with_cron, key=lambda s: s.key)
    ))


def test_bootstrap_schedules_is_idempotent(db, user):
    from app.agents.registry import bootstrap_schedules

    first = bootstrap_schedules(db)
    second = bootstrap_schedules(db)

    assert first == second
    rows = db.execute(select(Schedule).where(Schedule.user_id == user.id)).scalars().all()
    assert len(rows) == first


def test_bootstrap_schedules_lets_the_scheduler_pick_up_discovery(db, user, sched):
    """End-to-end proof that a fresh user gets a live scheduled job for
    'discovery' as soon as the process starts, with no page ever opened."""
    from app.agents.registry import bootstrap_schedules

    bootstrap_schedules(db)
    sched.reconcile()

    assert f"{user.id}:discovery" in sched.job_ids()

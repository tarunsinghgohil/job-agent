"""The agent registry the scheduler and the Agent Control Center dispatch into.

Agents are registered rather than imported ad hoc so that the control center can
list them, the scheduler can fire them by key, and every execution -- manual or
scheduled -- lands in the same ``agent_runs`` / ``agent_run_steps`` tables. That
uniform run history is what makes the control center honest about what ran, when,
and why it failed.

Agents owned by other modules are registered with a placeholder callable so the
rows, schedules and UI exist now and only the implementation has to be swapped in.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.automation import AgentDefinition, AgentRun, AgentRunStep, Schedule
from app.db.models.enums import AgentRunStatus, NotificationEventType, NotificationStatus
from app.services.followups import notify_due_followups
from app.services.notifications.service import (
    dispatch,
    render_daily_digest,
    render_weekly_summary,
)

logger = logging.getLogger(__name__)

MAX_ERROR_CHARS = 2000

# Agents that contact someone outside the product. These are created disabled.
OUTBOUND_AGENT_KEYS = frozenset({"auto_apply"})
# Agents the user switches on from their own screen. Also created disabled, so
# a fresh install does not start hitting job sources on a schedule unasked.
OPT_IN_AGENT_KEYS = OUTBOUND_AGENT_KEYS | frozenset({"job_hunt"})


class UnknownAgentError(LookupError):
    """Raised when a key has no registered agent."""


@dataclass(frozen=True, slots=True)
class AgentSpec:
    key: str
    name: str
    description: str
    default_cron: str


AgentCallable = Callable[[Session, str, dict], dict]

_REGISTRY: dict[str, tuple[AgentSpec, AgentCallable]] = {}


def register_agent(spec: AgentSpec, fn: AgentCallable) -> AgentSpec:
    _REGISTRY[spec.key] = (spec, fn)
    return spec


def get_agent(key: str) -> tuple[AgentSpec, AgentCallable] | None:
    return _REGISTRY.get(key)


def list_agent_specs() -> list[AgentSpec]:
    """Registration order, which is also the natural pipeline order."""
    return [spec for spec, _ in _REGISTRY.values()]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _counts(summary: dict) -> tuple[int, int, int]:
    def pick(*names: str) -> int:
        for name in names:
            value = summary.get(name)
            if isinstance(value, (int, float)):
                return int(value)
        return 0

    return (
        pick("processed", "items_processed"),
        pick("succeeded", "items_succeeded"),
        pick("failed", "items_failed"),
    )


def ensure_agent_definition(db: Session, user_id: str, spec: AgentSpec) -> AgentDefinition:
    """Create the control-center row for an agent the first time it is used."""
    definition = db.scalar(
        select(AgentDefinition).where(
            AgentDefinition.user_id == user_id, AgentDefinition.key == spec.key
        )
    )
    if definition is None:
        definition = AgentDefinition(
            user_id=user_id,
            key=spec.key,
            name=spec.name,
            description=spec.description,
            schedule_cron=spec.default_cron,
            # Agents that reach out to employers start switched off. The user
            # turns this on deliberately; it is not something to inherit from a
            # default. (The agent additionally refuses to run unless
            # auto_submit_enabled is set and approval_required is cleared.)
            enabled=spec.key not in OPT_IN_AGENT_KEYS,
        )
        db.add(definition)
        db.flush()
    return definition


def ensure_agent_definitions(db: Session, user_id: str) -> list[AgentDefinition]:
    return [ensure_agent_definition(db, user_id, spec) for spec in list_agent_specs()]


def sync_schedule(db: Session, user_id: str, agent: AgentDefinition) -> Schedule | None:
    """Keep the Schedule row in step with the agent's own cron setting.

    The scheduler only reconciles jobs against rows in the ``schedules`` table,
    not against ``AgentDefinition`` directly, so an agent with a cron set but no
    corresponding schedule row never actually fires. This used to only run when
    a user opened the Automations screen, which meant nothing ran automatically
    until that page had been visited at least once. ``bootstrap_schedules`` now
    calls this for every user at process startup so scheduling does not depend
    on a UI visit.
    """
    if not agent.schedule_cron:
        return None
    row = db.execute(
        select(Schedule).where(Schedule.user_id == user_id, Schedule.key == agent.key)
    ).scalar_one_or_none()
    if row is None:
        row = Schedule(user_id=user_id, key=agent.key, agent_key=agent.key, cron=agent.schedule_cron)
        db.add(row)
    row.cron = agent.schedule_cron
    row.enabled = agent.enabled
    row.description = agent.name
    row.agent_key = agent.key
    return row


def bootstrap_schedules(db: Session) -> int:
    """Ensure agent + schedule rows exist for every user. Returns rows touched."""
    from app.db.models.identity import User

    touched = 0
    for user_id in db.scalars(select(User.id)).all():
        for agent in ensure_agent_definitions(db, user_id):
            if sync_schedule(db, user_id, agent) is not None:
                touched += 1
    db.flush()
    return touched


def run_agent(
    db: Session,
    user_id: str,
    key: str,
    *,
    trigger: str = "manual",
    config: dict | None = None,
) -> AgentRun:
    """Execute one agent, recording the run, its step, and its outcome.

    Errors are captured on the run rather than propagated, so a failing agent
    leaves a diagnosable row behind instead of an empty history.
    """
    entry = get_agent(key)
    if entry is None:
        raise UnknownAgentError(f"No agent registered under '{key}'.")
    spec, fn = entry

    definition = ensure_agent_definition(db, user_id, spec)
    run = AgentRun(
        user_id=user_id,
        agent_id=definition.id,
        agent_key=key,
        trigger=trigger,
        status=AgentRunStatus.RUNNING.value,
        started_at=_utcnow(),
    )
    db.add(run)
    db.flush()

    step = AgentRunStep(
        run_id=run.id,
        sequence=1,
        name=spec.name or key,
        status=AgentRunStatus.RUNNING.value,
    )
    db.add(step)

    merged_config = {**dict(definition.config or {}), **dict(config or {})}
    started = perf_counter()
    try:
        summary = fn(db, user_id, merged_config) or {}
        if not isinstance(summary, dict):
            summary = {"detail": str(summary)}
        processed, succeeded, failed = _counts(summary)

        run.summary = summary
        run.items_processed = processed
        run.items_succeeded = succeeded
        run.items_failed = failed
        if failed and succeeded:
            run.status = AgentRunStatus.PARTIAL.value
        elif failed:
            run.status = AgentRunStatus.FAILED.value
        else:
            run.status = AgentRunStatus.SUCCESS.value

        step.status = run.status
        step.message = str(summary.get("detail", ""))[:500]
        step.payload = summary
    except Exception as exc:  # noqa: BLE001 - the run row is the error channel
        logger.exception("Agent %s failed for user %s.", key, user_id)
        error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]
        run.status = AgentRunStatus.FAILED.value
        run.error = error
        run.summary = {"detail": error}
        step.status = AgentRunStatus.FAILED.value
        step.message = error[:500]
        _notify_failure(db, user_id, spec, error)

    duration_ms = int((perf_counter() - started) * 1000)
    run.duration_ms = duration_ms
    run.finished_at = _utcnow()
    step.duration_ms = duration_ms

    definition.last_run_at = run.finished_at
    definition.last_status = run.status
    db.flush()
    return run


def _notify_failure(db: Session, user_id: str, spec: AgentSpec, error: str) -> None:
    """Tell the user an agent broke; dispatch is already failure-tolerant."""
    dispatch(
        db,
        user_id,
        NotificationEventType.SCHEDULED_RUN_FAILED.value,
        subject=f"Agent failed: {spec.name}",
        body=f"The {spec.name} agent failed.\n\n{error}",
        payload={"agent_key": spec.key},
        dedupe_key=f"agent_failed:{spec.key}:{_utcnow().date().isoformat()}",
    )


# ---------------------------------------------------------------------------
# Implemented agents
# ---------------------------------------------------------------------------
def run_notification_agent(db: Session, user_id: str, config: dict) -> dict:
    """Send the daily digest (or the weekly summary when configured to)."""
    weekly = str(config.get("mode", "daily")).lower() == "weekly"
    message = (
        render_weekly_summary(db, user_id) if weekly else render_daily_digest(db, user_id)
    )
    if message is None:
        return {"processed": 0, "succeeded": 0, "failed": 0, "detail": "nothing to report"}

    period = _utcnow().date().isoformat()
    events = dispatch(
        db,
        user_id,
        message.event_type,
        message.subject,
        message.body,
        payload=message.payload,
        dedupe_key=f"{message.event_type}:{period}",
        url=message.url,
    )
    sent = sum(1 for event in events if event.status == NotificationStatus.SENT.value)
    return {
        "processed": len(events),
        "succeeded": sent,
        "failed": len(events) - sent,
        "detail": f"{'weekly summary' if weekly else 'daily digest'} sent on {sent} channel(s)",
        "channels": [event.channel_type for event in events],
    }


def run_followup_agent(db: Session, user_id: str, config: dict) -> dict:
    """Alert on follow-ups that are due and have not been announced yet."""
    sent = notify_due_followups(db, user_id)
    return {
        "processed": sent,
        "succeeded": sent,
        "failed": 0,
        "detail": f"{sent} follow-up reminder(s) delivered",
    }


def _pending(module: str) -> AgentCallable:
    """Placeholder body for agents another module owns."""

    def _run(db: Session, user_id: str, config: dict) -> dict:
        raise NotImplementedError(f"wired in {module}")

    return _run


# TODO(discovery): implement in app/services/sources (job-source adapter runner).
register_agent(
    AgentSpec(
        key="discovery",
        name="Discovery",
        description="Pulls new postings from every enabled job source.",
        default_cron="0 8 * * *",
    ),
    _pending("app/services/sources"),
)

# TODO(normalization): implement in app/services/normalize.py.
register_agent(
    AgentSpec(
        key="normalization",
        name="Normalization",
        description="Cleans titles, companies, locations and salary into comparable fields.",
        default_cron="10 8 * * *",
    ),
    _pending("app/services/normalize.py"),
)

# TODO(deduplication): implement in app/services/dedupe.py.
register_agent(
    AgentSpec(
        key="deduplication",
        name="Deduplication",
        description="Collapses the same role reposted across sources into one job.",
        default_cron="15 8 * * *",
    ),
    _pending("app/services/dedupe.py"),
)

# TODO(qualification): implement in app/services/matching/rules.py.
register_agent(
    AgentSpec(
        key="qualification",
        name="Qualification",
        description="Applies hard rules to drop jobs that can never be a fit.",
        default_cron="20 8 * * *",
    ),
    _pending("app/services/matching/rules.py"),
)

# TODO(matching): implement in app/services/matching (scoring engine).
register_agent(
    AgentSpec(
        key="matching",
        name="Matching",
        description="Scores qualified jobs against the profile and preferences.",
        default_cron="25 8 * * *",
    ),
    _pending("app/services/matching"),
)

# TODO(resume_recommendation): implement in app/services/resume.
register_agent(
    AgentSpec(
        key="resume_recommendation",
        name="Resume recommendation",
        description="Picks the best existing resume variant for each match.",
        default_cron="30 8 * * *",
    ),
    _pending("app/services/resume"),
)

# TODO(resume_tailoring): implement in app/services/resume.
register_agent(
    AgentSpec(
        key="resume_tailoring",
        name="Resume tailoring",
        description="Generates an evidence-backed tailored resume for high matches.",
        default_cron="35 8 * * *",
    ),
    _pending("app/services/resume"),
)

# TODO(answer): implement in app/services/answers.py (answer bank resolution).
register_agent(
    AgentSpec(
        key="answer",
        name="Answer",
        description="Resolves application questions from the answer bank.",
        default_cron="40 8 * * *",
    ),
    _pending("app/services/answers.py"),
)

# TODO(application_preparation): implement in app/services/applications.py.
register_agent(
    AgentSpec(
        key="application_preparation",
        name="Application preparation",
        description="Assembles a review-ready application package per approved job.",
        default_cron="45 8 * * *",
    ),
    _pending("app/services/applications.py"),
)

register_agent(
    AgentSpec(
        key="notification",
        name="Notification",
        description="Delivers the daily digest across the user's enabled channels.",
        default_cron="0 9 * * *",
    ),
    run_notification_agent,
)

register_agent(
    AgentSpec(
        key="followup",
        name="Follow-up",
        description="Reminds about follow-ups that are due on submitted applications.",
        default_cron="30 9 * * *",
    ),
    run_followup_agent,
)

# Implemented in app/agents/wiring.py. Disabled by default: it is the only
# agent that contacts an employer, so switching it on is a deliberate act.
register_agent(
    AgentSpec(
        key="auto_apply",
        name="Auto apply (email lane)",
        description=(
            "Emails prepared applications to addresses employers published in their "
            "postings, within the daily cap. Never touches LinkedIn or portal forms."
        ),
        default_cron="0 10 * * *",
    ),
    _pending("app/agents/wiring.py"),
)

register_agent(
    AgentSpec(
        key="job_hunt",
        name="3x Job Hunt",
        description=(
            "Runs the full hunt: generates query variations, searches enabled sources, "
            "ranks every job by location priority, experience, skills and freshness, "
            "and alerts on new apply-first matches."
        ),
        default_cron="0 2,8,14,20 * * *",
    ),
    _pending("app/agents/wiring.py"),
)

# TODO(learning): implement in app/services/learning.py (outcome-driven weighting).
register_agent(
    AgentSpec(
        key="learning",
        name="Learning",
        description="Adjusts scoring weights from application outcomes.",
        default_cron="0 3 * * 0",
    ),
    _pending("app/services/learning.py"),
)


__all__ = [
    "AgentSpec",
    "UnknownAgentError",
    "register_agent",
    "get_agent",
    "list_agent_specs",
    "run_agent",
    "ensure_agent_definition",
    "ensure_agent_definitions",
    "sync_schedule",
    "bootstrap_schedules",
    "run_notification_agent",
    "run_followup_agent",
]

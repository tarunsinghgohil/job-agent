"""Agent control center and schedules."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.deps import Context, CurrentPreferences, DbSession
from app.core.errors import NotFoundError, ValidationError
from app.db.models.automation import AgentDefinition, AgentRun, Schedule
from app.schemas.common import MessageResponse
from app.schemas.ops import (
    AgentIn,
    AgentOut,
    AgentRunDetailOut,
    AgentRunOut,
    AgentRunStepOut,
    ScheduleIn,
    ScheduleOut,
)
from app.services import audit
from app.agents.registry import ensure_agent_definitions, run_agent, sync_schedule
from app.services.scheduler import scheduler

router = APIRouter(tags=["automation"])


def _agent_out(agent: AgentDefinition, next_run: Any = None) -> AgentOut:
    return AgentOut(
        id=agent.id,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        key=agent.key,
        name=agent.name,
        description=agent.description,
        enabled=agent.enabled,
        schedule_cron=agent.schedule_cron,
        config=agent.config or {},
        max_retries=agent.max_retries,
        last_run_at=agent.last_run_at,
        last_status=agent.last_status,
        next_run_at=next_run or agent.next_run_at,
    )


@router.get("/agents", response_model=list[AgentOut])
def list_agents(db: DbSession, ctx: Context) -> list[AgentOut]:
    agents = ensure_agent_definitions(db, ctx.user_id)
    db.flush()
    out: list[AgentOut] = []
    for agent in agents:
        try:
            next_run = scheduler.next_run_for(ctx.user_id, agent.key)
        except Exception:
            next_run = None
        out.append(_agent_out(agent, next_run))
    return out


@router.put("/agents/{key}", response_model=AgentOut)
def update_agent(key: str, payload: AgentIn, db: DbSession, ctx: Context) -> AgentOut:
    ensure_agent_definitions(db, ctx.user_id)
    agent = db.execute(
        select(AgentDefinition).where(
            AgentDefinition.user_id == ctx.user_id, AgentDefinition.key == key
        )
    ).scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"There is no {key!r} agent.")

    changes = payload.model_dump(exclude_none=True)
    for name, value in changes.items():
        setattr(agent, name, value)
    db.flush()

    # A cron or enabled change must reach the running scheduler immediately.
    if {"schedule_cron", "enabled"} & set(changes):
        sync_schedule(db, ctx.user_id, agent)
        db.flush()
        try:
            scheduler.reconcile()
        except Exception:
            pass

    audit.record(
        db, action="agent.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="agent", entity_id=agent.id,
        summary=f"Updated agent {key}: {', '.join(sorted(changes))}",
    )
    return _agent_out(agent)


@router.post("/agents/{key}/run", response_model=AgentRunDetailOut)
def run_agent_now(key: str, db: DbSession, ctx: Context) -> AgentRunDetailOut:
    ensure_agent_definitions(db, ctx.user_id)
    try:
        run = run_agent(db, ctx.user_id, key, trigger="manual")
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc

    db.flush()
    audit.record(
        db, action="agent.run", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="agent_run", entity_id=run.id,
        summary=f"Ran the {key} agent: {run.status}",
        success=run.status in ("success", "partial"),
    )
    return AgentRunDetailOut(
        **AgentRunOut.model_validate(run).model_dump(),
        steps=[AgentRunStepOut.model_validate(s) for s in run.steps],
    )


@router.get("/agents/runs", response_model=list[AgentRunOut])
def list_runs(
    db: DbSession,
    ctx: Context,
    agent_key: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[AgentRunOut]:
    stmt = select(AgentRun).where(AgentRun.user_id == ctx.user_id)
    if agent_key:
        stmt = stmt.where(AgentRun.agent_key == agent_key)
    rows = db.execute(
        stmt.order_by(AgentRun.created_at.desc()).limit(limit)
    ).scalars().all()
    return [AgentRunOut.model_validate(r) for r in rows]


@router.get("/agents/runs/{run_id}", response_model=AgentRunDetailOut)
def get_run(run_id: str, db: DbSession, ctx: Context) -> AgentRunDetailOut:
    run = db.get(AgentRun, run_id)
    if run is None or run.user_id != ctx.user_id:
        raise NotFoundError("That run does not exist.")
    return AgentRunDetailOut(
        **AgentRunOut.model_validate(run).model_dump(),
        steps=[AgentRunStepOut.model_validate(s) for s in run.steps],
    )


# --------------------------------------------------------------------------
# Schedules
# --------------------------------------------------------------------------
@router.get("/schedules", response_model=list[ScheduleOut])
def list_schedules(db: DbSession, ctx: Context) -> list[ScheduleOut]:
    agents = ensure_agent_definitions(db, ctx.user_id)
    for agent in agents:
        sync_schedule(db, ctx.user_id, agent)
    db.flush()

    rows = db.execute(
        select(Schedule).where(Schedule.user_id == ctx.user_id).order_by(Schedule.key)
    ).scalars().all()

    out: list[ScheduleOut] = []
    for row in rows:
        try:
            row.next_run_at = scheduler.next_run_for(ctx.user_id, row.key) or row.next_run_at
        except Exception:
            pass
        out.append(ScheduleOut.model_validate(row))
    return out


@router.put("/schedules/{key}", response_model=ScheduleOut)
def update_schedule(
    key: str, payload: ScheduleIn, db: DbSession, ctx: Context
) -> ScheduleOut:
    row = db.execute(
        select(Schedule).where(Schedule.user_id == ctx.user_id, Schedule.key == key)
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"There is no {key!r} schedule.")

    changes = payload.model_dump(exclude_none=True)
    if "cron" in changes:
        from apscheduler.triggers.cron import CronTrigger

        try:
            CronTrigger.from_crontab(changes["cron"])
        except (ValueError, TypeError) as exc:
            raise ValidationError(f"{changes['cron']!r} is not a valid cron expression.") from exc

    for name, value in changes.items():
        setattr(row, name, value)

    # Keep the owning agent in step so the two cannot disagree.
    agent = db.execute(
        select(AgentDefinition).where(
            AgentDefinition.user_id == ctx.user_id, AgentDefinition.key == row.agent_key
        )
    ).scalar_one_or_none()
    if agent is not None:
        if "cron" in changes:
            agent.schedule_cron = row.cron
        if "enabled" in changes:
            agent.enabled = row.enabled

    db.flush()
    try:
        scheduler.reconcile()
    except Exception:
        pass

    audit.record(
        db, action="schedule.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="schedule", entity_id=row.id,
        summary=f"Updated schedule {key}: {', '.join(sorted(changes))}",
    )
    return ScheduleOut.model_validate(row)


@router.post("/schedules/{key}/run-now", response_model=AgentRunOut)
def run_schedule_now(key: str, db: DbSession, ctx: Context) -> AgentRunOut:
    row = db.execute(
        select(Schedule).where(Schedule.user_id == ctx.user_id, Schedule.key == key)
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"There is no {key!r} schedule.")

    try:
        run = run_agent(db, ctx.user_id, row.agent_key or key, trigger="manual")
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc

    db.flush()
    return AgentRunOut.model_validate(run)

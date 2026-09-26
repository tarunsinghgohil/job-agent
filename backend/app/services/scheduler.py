"""APScheduler wrapper that reconciles jobs against the ``schedules`` table.

The table is the source of truth, not the scheduler's memory. Every job id is
derived deterministically from ``user_id`` and ``schedule_key`` and reconciled
with ``replace_existing=True``, so restarting the process re-derives exactly the
same job set instead of stacking a second copy of every scheduled task -- the
duplicate-task failure mode the spec calls out.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.config import settings
from app.db.models.automation import Schedule
from app.db.session import session_scope

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 3
MISFIRE_GRACE_SECONDS = 3600
INVALID_CRON_STATUS = "invalid_cron"


def job_id_for(user_id: str, schedule_key: str) -> str:
    return f"{user_id}:{schedule_key}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _build_trigger(cron: str, tz: str) -> CronTrigger:
    return CronTrigger.from_crontab(cron, timezone=tz or settings.timezone)


def _run_scheduled(user_id: str, schedule_key: str) -> None:
    """APScheduler entry point: one fire, one session, one AgentRun row.

    A fire runs in a worker thread with no request context, so it opens and owns
    its own session; anything it raises would only reach APScheduler's logger, so
    failures are recorded on the schedule row instead.
    """
    from app.agents.registry import run_agent

    with session_scope() as db:
        schedule = db.scalar(
            select(Schedule).where(Schedule.user_id == user_id, Schedule.key == schedule_key)
        )
        if schedule is None or not schedule.enabled:
            logger.info("Schedule %s is gone or disabled; skipping fire.", schedule_key)
            return

        agent_key = schedule.agent_key or schedule.key
        schedule.last_run_at = _utcnow()
        try:
            run = run_agent(
                db,
                user_id,
                agent_key,
                trigger="schedule",
                config=dict(schedule.payload or {}),
            )
            schedule.last_status = run.status
        except Exception:  # noqa: BLE001 - a bad agent must not kill the scheduler
            logger.exception("Scheduled agent %s failed for user %s.", agent_key, user_id)
            schedule.last_status = "failed"

        try:
            schedule.next_run_at = _build_trigger(schedule.cron, schedule.timezone).get_next_fire_time(
                None, _utcnow()
            )
        except (ValueError, TypeError):
            schedule.next_run_at = None


class AgentScheduler:
    """Owns the process-wide BackgroundScheduler and keeps it in sync with the DB."""

    def __init__(self) -> None:
        self._scheduler: BackgroundScheduler | None = None
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------
    def _get(self) -> BackgroundScheduler:
        with self._lock:
            if self._scheduler is None:
                self._scheduler = BackgroundScheduler(
                    executors={"default": ThreadPoolExecutor(MAX_CONCURRENT)},
                    job_defaults={
                        "coalesce": True,
                        "misfire_grace_time": MISFIRE_GRACE_SECONDS,
                        "max_instances": 1,
                    },
                    timezone=settings.timezone or "UTC",
                )
            return self._scheduler

    @property
    def running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    def start(self) -> None:
        if not settings.scheduler_enabled:
            logger.info("Scheduler disabled by settings; no jobs will be registered.")
            return
        scheduler_ = self._get()
        with self._lock:
            if not scheduler_.running:
                scheduler_.start()
                logger.info("Scheduler started with max %s concurrent runs.", MAX_CONCURRENT)
        self.reconcile()

    def shutdown(self) -> None:
        with self._lock:
            if self._scheduler is not None and self._scheduler.running:
                self._scheduler.shutdown(wait=False)
                logger.info("Scheduler stopped.")

    # -- reconciliation ----------------------------------------------------
    def _remove(self, job_id: str) -> None:
        try:
            self._get().remove_job(job_id)
        except JobLookupError:
            pass

    def reconcile(self) -> None:
        """Make the live job set exactly match the enabled schedule rows."""
        scheduler_ = self._get()
        wanted: set[str] = set()

        with session_scope() as db:
            schedules = list(db.scalars(select(Schedule).where(Schedule.enabled.is_(True))))
            for schedule in schedules:
                identifier = job_id_for(schedule.user_id, schedule.key)
                try:
                    trigger = _build_trigger(schedule.cron, schedule.timezone)
                except Exception as exc:  # noqa: BLE001 - one bad row must not stop the rest
                    logger.error(
                        "Schedule %s has an unusable cron expression %r: %s",
                        identifier,
                        schedule.cron,
                        exc,
                    )
                    schedule.last_status = INVALID_CRON_STATUS
                    schedule.next_run_at = None
                    self._remove(identifier)
                    continue

                # Before start() APScheduler keeps pending jobs in a plain list that
                # replace_existing cannot de-duplicate, so drop any prior copy first.
                self._remove(identifier)
                scheduler_.add_job(
                    _run_scheduled,
                    trigger=trigger,
                    id=identifier,
                    name=schedule.description or schedule.key,
                    args=[schedule.user_id, schedule.key],
                    replace_existing=True,
                    coalesce=True,
                    misfire_grace_time=MISFIRE_GRACE_SECONDS,
                    max_instances=1,
                )
                wanted.add(identifier)
                schedule.next_run_at = trigger.get_next_fire_time(None, _utcnow())
                if schedule.last_status == INVALID_CRON_STATUS:
                    schedule.last_status = ""

        for job in list(scheduler_.get_jobs()):
            if job.id not in wanted:
                logger.info("Removing scheduler job %s; it has no enabled schedule row.", job.id)
                self._remove(job.id)

    # -- queries and manual runs -------------------------------------------
    def job_ids(self) -> list[str]:
        return sorted(job.id for job in self._get().get_jobs())

    def next_run_for(self, user_id: str, schedule_key: str) -> datetime | None:
        identifier = job_id_for(user_id, schedule_key)
        for job in self._get().get_jobs():
            if job.id == identifier:
                nxt = getattr(job, "next_run_time", None)
                if nxt is not None:
                    return nxt
                break

        with session_scope() as db:
            schedule = db.scalar(
                select(Schedule).where(Schedule.user_id == user_id, Schedule.key == schedule_key)
            )
            if schedule is None or not schedule.enabled:
                return None
            try:
                return _build_trigger(schedule.cron, schedule.timezone).get_next_fire_time(
                    None, _utcnow()
                )
            except Exception:  # noqa: BLE001 - invalid cron simply has no next run
                return None

    def run_now(self, user_id: str, schedule_key: str) -> str:
        """Run a schedule's agent immediately and return the AgentRun id."""
        from app.agents.registry import run_agent

        with session_scope() as db:
            schedule = db.scalar(
                select(Schedule).where(Schedule.user_id == user_id, Schedule.key == schedule_key)
            )
            agent_key = (schedule.agent_key or schedule.key) if schedule else schedule_key
            config = dict(schedule.payload or {}) if schedule else {}

            run = run_agent(db, user_id, agent_key, trigger="manual", config=config)
            run_id = run.id
            if schedule is not None:
                schedule.last_run_at = _utcnow()
                schedule.last_status = run.status
        return run_id


scheduler = AgentScheduler()

__all__ = ["AgentScheduler", "scheduler", "job_id_for", "MAX_CONCURRENT", "INVALID_CRON_STATUS"]

"""Job source management.

Adding a provider is configuration: the UI renders each adapter's declared
config schema, so a new source never requires a frontend code change.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import Context, DbSession
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.base import utcnow
from app.db.models.enums import SourceHealth
from app.db.models.jobs import JobSource
from app.schemas.common import MessageResponse, TestResult
from app.schemas.jobs import AdapterDescriptor, DiscoverResult, JobSourceIn, JobSourceOut
from app.services import audit, secrets
from app.services.discovery import discover
from app.services.jobs import score_unscored
from app.services.sources import UnknownAdapterError, get_adapter, list_adapters

router = APIRouter(prefix="/sources", tags=["sources"])


def _serialize(source: JobSource) -> JobSourceOut:
    return JobSourceOut(
        id=source.id,
        created_at=source.created_at,
        updated_at=source.updated_at,
        name=source.name,
        adapter_type=source.adapter_type,
        base_url=source.base_url,
        config=source.config or {},
        enabled=source.enabled,
        priority=source.priority,
        schedule_cron=source.schedule_cron,
        query_templates=source.query_templates or [],
        rate_limit_per_hour=source.rate_limit_per_hour,
        source_rules=source.source_rules or {},
        health=source.health,
        last_success_at=source.last_success_at,
        last_attempt_at=source.last_attempt_at,
        last_error=source.last_error,
        consecutive_failures=source.consecutive_failures,
        has_credential=bool(source.credential_ref),
    )


def _owned(db: Any, user_id: str, source_id: str) -> JobSource:
    source = db.get(JobSource, source_id)
    if source is None or source.user_id != user_id or source.deleted_at is not None:
        raise NotFoundError("That job source does not exist.")
    return source


def _store_credential(db: Any, ctx: Context, source: JobSource, credential: str | None) -> None:
    """Credentials live in the encrypted table; the source only holds a pointer."""
    if credential is None:
        return
    key = f"source:{source.id}"
    if not credential.strip():
        secrets.delete(db, ctx.user_id, key)
        source.credential_ref = None
        return
    row = secrets.put(
        db, ctx.user_id, key,
        credential,
        label=f"{source.name} credential",
        provider=source.adapter_type,
    )
    source.credential_ref = row.id


@router.get("/adapters", response_model=list[AdapterDescriptor])
def available_adapters() -> list[AdapterDescriptor]:
    return [AdapterDescriptor(**a) for a in list_adapters()]


@router.get("", response_model=list[JobSourceOut])
def list_sources(db: DbSession, ctx: Context) -> list[JobSourceOut]:
    rows = db.execute(
        select(JobSource)
        .where(JobSource.user_id == ctx.user_id, JobSource.deleted_at.is_(None))
        .order_by(JobSource.priority, JobSource.name)
    ).scalars().all()
    return [_serialize(s) for s in rows]


@router.post("", response_model=JobSourceOut, status_code=201)
def create_source(payload: JobSourceIn, db: DbSession, ctx: Context) -> JobSourceOut:
    try:
        get_adapter(payload.adapter_type, payload.config, None)
    except UnknownAdapterError as exc:
        raise ValidationError(str(exc)) from exc

    existing = db.execute(
        select(JobSource).where(
            JobSource.user_id == ctx.user_id,
            JobSource.name == payload.name,
            JobSource.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("A source with that name already exists.")

    data = payload.model_dump(exclude={"credential"})
    source = JobSource(user_id=ctx.user_id, **data)
    db.add(source)
    db.flush()

    _store_credential(db, ctx, source, payload.credential)
    db.flush()

    audit.record(
        db, action="source.create", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job_source", entity_id=source.id,
        summary=f"Added job source {source.name} ({source.adapter_type})",
    )
    return _serialize(source)


@router.put("/{source_id}", response_model=JobSourceOut)
def update_source(
    source_id: str, payload: JobSourceIn, db: DbSession, ctx: Context
) -> JobSourceOut:
    source = _owned(db, ctx.user_id, source_id)
    for name, value in payload.model_dump(exclude={"credential"}).items():
        setattr(source, name, value)
    _store_credential(db, ctx, source, payload.credential)
    db.flush()

    audit.record(
        db, action="source.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job_source", entity_id=source.id,
        summary=f"Updated job source {source.name}",
    )
    return _serialize(source)


@router.delete("/{source_id}", response_model=MessageResponse)
def delete_source(source_id: str, db: DbSession, ctx: Context) -> MessageResponse:
    source = _owned(db, ctx.user_id, source_id)
    source.deleted_at = utcnow()
    source.enabled = False
    if source.credential_ref:
        secrets.delete(db, ctx.user_id, f"source:{source.id}")
        source.credential_ref = None

    audit.record(
        db, action="source.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job_source", entity_id=source.id,
        summary=f"Removed job source {source.name}",
    )
    return MessageResponse(message="Job source removed. Jobs already discovered are kept.")


@router.post("/{source_id}/test", response_model=TestResult)
def test_source(source_id: str, db: DbSession, ctx: Context) -> TestResult:
    source = _owned(db, ctx.user_id, source_id)
    credential = secrets.resolve_by_ref(db, source.credential_ref)

    try:
        adapter = get_adapter(source.adapter_type, source.config or {}, credential)
        result = adapter.test_connection()
    except UnknownAdapterError as exc:
        result_ok, message, details = False, str(exc), {}
    except Exception as exc:
        result_ok, message, details = False, f"{type(exc).__name__}: {exc}"[:400], {}
    else:
        result_ok, message, details = result.ok, result.message, result.details

    source.last_attempt_at = utcnow()
    if result_ok:
        source.health = SourceHealth.HEALTHY
        source.last_success_at = utcnow()
        source.last_error = ""
        source.consecutive_failures = 0
    else:
        source.consecutive_failures += 1
        source.health = (
            SourceHealth.FAILING if source.consecutive_failures >= 3 else SourceHealth.DEGRADED
        )
        source.last_error = message[:2000]

    audit.record(
        db, action="source.test", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job_source", entity_id=source.id,
        summary=f"Tested {source.name}: {'ok' if result_ok else 'failed'}",
        success=result_ok,
    )
    return TestResult(ok=result_ok, message=message, details=details)


@router.post("/{source_id}/sync", response_model=DiscoverResult)
def sync_source(source_id: str, db: DbSession, ctx: Context) -> DiscoverResult:
    source = _owned(db, ctx.user_id, source_id)
    result = discover(db, ctx.user_id, source_ids=[source.id])
    db.flush()
    score_unscored(db, ctx.user_id, actor=ctx.actor)

    audit.record(
        db, action="source.sync", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job_source", entity_id=source.id,
        summary=f"Synced {source.name}: {result.created} new, {result.updated} updated",
        success=not result.errors,
    )
    return DiscoverResult(
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        errors=result.errors,
        per_source=result.per_source,
    )

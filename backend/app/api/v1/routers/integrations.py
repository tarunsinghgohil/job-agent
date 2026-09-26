"""Credential management.

The API never returns a stored secret. Responses carry a masked hint, where
the value came from, and the result of the last connection test.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import Context, DbSession
from app.core.errors import NotFoundError, ValidationError
from app.schemas.common import MessageResponse, TestResult
from app.schemas.ops import IntegrationIn, IntegrationOut
from app.services import audit, secrets

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", response_model=list[IntegrationOut])
def list_integrations(db: DbSession, ctx: Context) -> list[IntegrationOut]:
    return [IntegrationOut(**row) for row in secrets.describe_all(db, ctx.user_id)]


@router.put("/{key}", response_model=IntegrationOut)
def set_integration(
    key: str, payload: IntegrationIn, db: DbSession, ctx: Context
) -> IntegrationOut:
    if key not in secrets.SECRET_CATALOGUE:
        raise NotFoundError(f"{key!r} is not a known integration.")

    try:
        secrets.put(db, ctx.user_id, key, payload.value, label=payload.label)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    db.flush()
    audit.record(
        db,
        action="integration.set",
        user_id=ctx.user_id,
        actor=ctx.actor,
        entity_type="encrypted_secret",
        entity_id=key,
        # Deliberately records only that a credential changed, never its value.
        summary=f"Stored a new credential for {key}",
    )

    row = next(r for r in secrets.describe_all(db, ctx.user_id) if r["key"] == key)
    return IntegrationOut(**row)


@router.post("/{key}/test", response_model=TestResult)
def test_integration(key: str, db: DbSession, ctx: Context) -> TestResult:
    if key not in secrets.SECRET_CATALOGUE:
        raise NotFoundError(f"{key!r} is not a known integration.")

    ok, message = secrets.test_credential(db, ctx.user_id, key)
    secrets.record_test(db, ctx.user_id, key, ok, "" if ok else message)
    db.flush()

    audit.record(
        db, action="integration.test", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="encrypted_secret", entity_id=key,
        summary=f"Tested {key}: {'ok' if ok else 'failed'}", success=ok,
    )
    return TestResult(ok=ok, message=message)


@router.delete("/{key}", response_model=MessageResponse)
def delete_integration(key: str, db: DbSession, ctx: Context) -> MessageResponse:
    if key not in secrets.SECRET_CATALOGUE:
        raise NotFoundError(f"{key!r} is not a known integration.")

    removed = secrets.delete(db, ctx.user_id, key)
    audit.record(
        db, action="integration.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="encrypted_secret", entity_id=key,
        summary=f"Disconnected {key}",
    )
    if not removed:
        return MessageResponse(
            message="Nothing stored for that integration. Any value in use comes from "
            "the environment and must be removed there.",
            ok=False,
        )
    return MessageResponse(message="Credential removed.")

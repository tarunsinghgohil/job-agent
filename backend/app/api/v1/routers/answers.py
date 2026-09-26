"""Answer bank CRUD and the resolution/drafting endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.deps import Context, CurrentProfile, DbSession, rate_limit_ai
from app.core.errors import NotFoundError
from app.db.models.applications import AnswerBankEntry
from app.schemas.applications import (
    AnswerIn,
    AnswerOut,
    ResolveAnswerRequest,
    ResolvedAnswerOut,
)
from app.schemas.common import MessageResponse
from app.services import answers as answer_service, audit
from app.services.ai.client import AIService
from app.services.jobs import get_owned_job
from app.services.normalize import normalize_company

router = APIRouter(prefix="/answers", tags=["answers"])


def _owned(db, user_id: str, answer_id: str) -> AnswerBankEntry:
    entry = db.get(AnswerBankEntry, answer_id)
    if entry is None or entry.user_id != user_id:
        raise NotFoundError("That answer does not exist.")
    return entry


@router.get("", response_model=list[AnswerOut])
def list_answers(
    db: DbSession, ctx: Context, category: str | None = None, q: str | None = None
) -> list[AnswerOut]:
    stmt = select(AnswerBankEntry).where(AnswerBankEntry.user_id == ctx.user_id)
    if category:
        stmt = stmt.where(AnswerBankEntry.category == category)
    if q:
        stmt = stmt.where(AnswerBankEntry.question.ilike(f"%{q.strip()}%"))

    rows = db.execute(
        stmt.order_by(AnswerBankEntry.priority, AnswerBankEntry.question)
    ).scalars().all()
    return [AnswerOut.model_validate(r) for r in rows]


@router.post("", response_model=AnswerOut, status_code=201)
def create_answer(payload: AnswerIn, db: DbSession, ctx: Context) -> AnswerOut:
    data = payload.model_dump()
    question = data.pop("question")
    answer = data.pop("answer")
    if data.get("company_normalized"):
        data["company_normalized"] = normalize_company(data["company_normalized"])

    entry = answer_service.upsert_entry(db, ctx.user_id, question, answer, **data)
    db.flush()
    audit.record(
        db, action="answer.upsert", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="answer_bank", entity_id=entry.id,
        summary=f"Saved answer for: {entry.question[:80]}",
    )
    return AnswerOut.model_validate(entry)


@router.put("/{answer_id}", response_model=AnswerOut)
def update_answer(
    answer_id: str, payload: AnswerIn, db: DbSession, ctx: Context
) -> AnswerOut:
    entry = _owned(db, ctx.user_id, answer_id)
    data = payload.model_dump()

    entry.question = data.pop("question")
    entry.answer = data.pop("answer")
    entry.normalized_key = answer_service.normalize_question(entry.question)
    if data.get("company_normalized"):
        data["company_normalized"] = normalize_company(data["company_normalized"])
    for name, value in data.items():
        setattr(entry, name, value)

    db.flush()
    audit.record(
        db, action="answer.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="answer_bank", entity_id=entry.id,
        summary=f"Updated answer for: {entry.question[:80]}",
    )
    return AnswerOut.model_validate(entry)


@router.delete("/{answer_id}", response_model=MessageResponse)
def delete_answer(answer_id: str, db: DbSession, ctx: Context) -> MessageResponse:
    entry = _owned(db, ctx.user_id, answer_id)
    db.delete(entry)
    audit.record(
        db, action="answer.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="answer_bank", entity_id=answer_id, summary="Deleted an answer",
    )
    return MessageResponse(message="Answer removed.")


@router.post("/resolve", response_model=ResolvedAnswerOut)
def resolve(
    payload: ResolveAnswerRequest,
    db: DbSession,
    ctx: Context,
    profile: CurrentProfile,
) -> ResolvedAnswerOut:
    """Resolve a question through the full precedence chain."""
    job = get_owned_job(db, ctx.user_id, payload.job_id) if payload.job_id else None
    outcome = answer_service.resolve_answer(
        db,
        ctx.user_id,
        payload.question,
        job=job,
        profile=profile,
        ai_service=AIService(db, ctx.user_id) if payload.allow_ai else None,
        allow_ai=payload.allow_ai,
    )
    return ResolvedAnswerOut(**outcome.as_dict())


@router.post("/draft", response_model=ResolvedAnswerOut)
def draft(
    payload: ResolveAnswerRequest,
    db: DbSession,
    ctx: Context,
    profile: CurrentProfile,
    _: Annotated[None, Depends(rate_limit_ai)] = None,
) -> ResolvedAnswerOut:
    """Force the AI path, for when the user wants a fresh draft."""
    job = get_owned_job(db, ctx.user_id, payload.job_id) if payload.job_id else None
    ai = AIService(db, ctx.user_id)
    ai.require_enabled()

    from app.services.ai.functions import answer_question

    known = [
        (e.question, e.answer)
        for e in db.execute(
            select(AnswerBankEntry).where(
                AnswerBankEntry.user_id == ctx.user_id, AnswerBankEntry.enabled.is_(True)
            )
        ).scalars().all()[:25]
    ]
    data = answer_question(db, ai, ctx.user_id, payload.question, profile, known, job=job)

    return ResolvedAnswerOut(
        question=payload.question,
        answer=str(data.get("answer", "")),
        state="needs_review" if data.get("needs_review", True) else "inferred",
        confidence=float(data.get("confidence") or 0.5),
        resolved_from="ai",
        answer_bank_id=None,
        evidence_ids=[str(e) for e in (data.get("evidence_used") or [])],
        note="Drafted from stored evidence. Review before submitting.",
    )

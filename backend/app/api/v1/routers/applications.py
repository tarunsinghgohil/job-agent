"""Application queue, tracker, and follow-ups."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from app.core.deps import Context, CurrentPreferences, CurrentProfile, DbSession
from app.core.errors import NotFoundError, ValidationError
from app.db.models.applications import (
    Application,
    ApplicationAnswer,
    FollowUp,
)
from app.db.models.enums import ApplicationStatus
from app.db.models.jobs import Job
from app.schemas.common import MessageResponse, Page
from app.schemas.applications import (
    ApplicationAnswerIn,
    ApplicationAnswerOut,
    ApplicationAssetOut,
    ApplicationDetailOut,
    ApplicationIn,
    ApplicationOut,
    ApplicationPatch,
    FollowUpIn,
    FollowUpOut,
    PrepareResult,
    RejectRequest,
    StatusChangeRequest,
    StatusHistoryOut,
    SubmitRequest,
)
from app.services import applications as app_service, audit, followups as followup_service
from app.services.ai.client import AIService
from app.services.jobs import current_match, get_owned_job

router = APIRouter(tags=["applications"])


def _application_out(application: Application, job: Job | None) -> ApplicationOut:
    return ApplicationOut(
        id=application.id,
        created_at=application.created_at,
        updated_at=application.updated_at,
        job_id=application.job_id,
        job_title=job.title if job else "",
        company=job.company if job else "",
        job_url=job.url if job else "",
        resume_version_id=application.resume_version_id,
        status=application.status,
        channel=application.channel,
        match_score=application.match_score,
        approved_at=application.approved_at,
        submitted_at=application.submitted_at,
        closed_at=application.closed_at,
        next_action=application.next_action,
        next_action_due=application.next_action_due,
        notes=application.notes,
        failure_reason=application.failure_reason,
        outcome_reason=application.outcome_reason,
    )


def _detail_out(db: Any, application: Application) -> ApplicationDetailOut:
    job = db.get(Job, application.job_id)
    base = _application_out(application, job)
    return ApplicationDetailOut(
        **base.model_dump(),
        history=[StatusHistoryOut.model_validate(h) for h in application.history],
        answers=[ApplicationAnswerOut.model_validate(a) for a in application.answers],
        assets=[
            ApplicationAssetOut.model_validate(a)
            for a in sorted(application.assets, key=lambda a: a.created_at, reverse=True)
        ],
        followups=[
            FollowUpOut(
                **{
                    **FollowUpOut.model_validate(f).model_dump(),
                    "company": job.company if job else "",
                    "job_title": job.title if job else "",
                }
            )
            for f in application.followups
        ],
    )


@router.get("/applications", response_model=Page[ApplicationOut])
def list_applications(
    db: DbSession,
    ctx: Context,
    status: str | None = None,
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
) -> Page[ApplicationOut]:
    stmt = (
        select(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .where(Application.user_id == ctx.user_id)
    )
    if status:
        stmt = stmt.where(Application.status == status)
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(Job.title.ilike(needle), Job.company.ilike(needle)))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(Application.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    rows = db.execute(stmt).all()
    return Page.build(
        [_application_out(a, j) for a, j in rows], total, page, page_size
    )


@router.post("/applications", response_model=ApplicationDetailOut, status_code=201)
def create_application(
    payload: ApplicationIn, db: DbSession, ctx: Context, prefs: CurrentPreferences
) -> ApplicationDetailOut:
    job = get_owned_job(db, ctx.user_id, payload.job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")

    match = current_match(db, job.id)
    application = app_service.create(
        db,
        ctx.user_id,
        job,
        prefs,
        resume_version_id=payload.resume_version_id,
        channel=str(payload.channel),
        notes=payload.notes,
        match_score=match.score if match else None,
        actor=ctx.actor,
    )
    db.flush()
    return _detail_out(db, application)


@router.get("/applications/{application_id}", response_model=ApplicationDetailOut)
def get_application(application_id: str, db: DbSession, ctx: Context) -> ApplicationDetailOut:
    return _detail_out(db, app_service.get_owned(db, ctx.user_id, application_id))


@router.patch("/applications/{application_id}", response_model=ApplicationDetailOut)
def patch_application(
    application_id: str, payload: ApplicationPatch, db: DbSession, ctx: Context
) -> ApplicationDetailOut:
    application = app_service.get_owned(db, ctx.user_id, application_id)
    changes = payload.model_dump(exclude_none=True)
    for name, value in changes.items():
        setattr(application, name, str(value) if name == "channel" else value)
    db.flush()
    audit.record(
        db, action="application.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="application", entity_id=application.id,
        summary=f"Updated application fields: {', '.join(sorted(changes))}",
    )
    return _detail_out(db, application)


@router.post("/applications/{application_id}/approve", response_model=ApplicationDetailOut)
def approve(application_id: str, db: DbSession, ctx: Context) -> ApplicationDetailOut:
    application = app_service.get_owned(db, ctx.user_id, application_id)
    app_service.transition(
        db, application, ApplicationStatus.APPROVED, reason="Approved by user", actor=ctx.actor
    )
    db.flush()
    return _detail_out(db, application)


@router.post("/applications/{application_id}/reject", response_model=ApplicationDetailOut)
def reject(
    application_id: str, payload: RejectRequest, db: DbSession, ctx: Context
) -> ApplicationDetailOut:
    application = app_service.get_owned(db, ctx.user_id, application_id)
    app_service.transition(
        db, application, ApplicationStatus.REJECTED, reason=payload.reason, actor=ctx.actor
    )
    db.flush()
    return _detail_out(db, application)


@router.post("/applications/{application_id}/prepare", response_model=PrepareResult)
def prepare(
    application_id: str, db: DbSession, ctx: Context, profile: CurrentProfile
) -> PrepareResult:
    application = app_service.get_owned(db, ctx.user_id, application_id)
    job = db.get(Job, application.job_id)
    if job is None:
        raise NotFoundError("The job for this application no longer exists.")

    result = app_service.prepare(
        db,
        application,
        job,
        profile=profile,
        ai_service=AIService(db, ctx.user_id),
        actor=ctx.actor,
    )
    db.flush()
    return PrepareResult(**result)


@router.post("/applications/{application_id}/submit", response_model=ApplicationDetailOut)
def submit(
    application_id: str,
    payload: SubmitRequest,
    db: DbSession,
    ctx: Context,
    prefs: CurrentPreferences,
    profile: CurrentProfile,
) -> ApplicationDetailOut:
    application = app_service.get_owned(db, ctx.user_id, application_id)
    job = db.get(Job, application.job_id)
    if job is None:
        raise NotFoundError("The job for this application no longer exists.")

    app_service.submit(
        db,
        application,
        job,
        prefs,
        confirmed=payload.confirm_manual_submission,
        reference=payload.reference,
        actor=ctx.actor,
        profile=profile,
    )
    db.flush()
    return _detail_out(db, application)


@router.post("/applications/{application_id}/status", response_model=ApplicationDetailOut)
def change_status(
    application_id: str, payload: StatusChangeRequest, db: DbSession, ctx: Context
) -> ApplicationDetailOut:
    application = app_service.get_owned(db, ctx.user_id, application_id)
    app_service.transition(
        db, application, str(payload.status), reason=payload.reason, actor=ctx.actor
    )
    db.flush()
    return _detail_out(db, application)


@router.get("/applications/{application_id}/history", response_model=list[StatusHistoryOut])
def history(application_id: str, db: DbSession, ctx: Context) -> list[StatusHistoryOut]:
    application = app_service.get_owned(db, ctx.user_id, application_id)
    return [StatusHistoryOut.model_validate(h) for h in application.history]


@router.post("/applications/{application_id}/answers", response_model=ApplicationAnswerOut)
def upsert_application_answer(
    application_id: str, payload: ApplicationAnswerIn, db: DbSession, ctx: Context
) -> ApplicationAnswerOut:
    application = app_service.get_owned(db, ctx.user_id, application_id)

    existing = next(
        (a for a in application.answers if a.question == payload.question), None
    )
    if existing is None:
        existing = ApplicationAnswer(
            application_id=application.id, question=payload.question
        )
        db.add(existing)

    existing.answer = payload.answer
    existing.state = payload.state
    existing.confidence = payload.confidence
    existing.resolved_from = "user"
    db.flush()

    audit.record(
        db, action="application.answer.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="application", entity_id=application.id,
        summary=f"Edited an application answer: {payload.question[:60]}",
    )
    return ApplicationAnswerOut.model_validate(existing)


# --------------------------------------------------------------------------
# Follow-ups
# --------------------------------------------------------------------------
@router.post("/applications/{application_id}/followups", response_model=FollowUpOut, status_code=201)
def add_followup(
    application_id: str, payload: FollowUpIn, db: DbSession, ctx: Context
) -> FollowUpOut:
    application = app_service.get_owned(db, ctx.user_id, application_id)
    followup = followup_service.create_followup(
        db,
        ctx.user_id,
        application.id,
        payload.due_date,
        kind=payload.kind,
        note=payload.note,
    )
    db.flush()
    job = db.get(Job, application.job_id)
    return FollowUpOut(
        **{
            **FollowUpOut.model_validate(followup).model_dump(),
            "company": job.company if job else "",
            "job_title": job.title if job else "",
        }
    )


@router.get("/followups", response_model=list[FollowUpOut])
def list_followups(
    db: DbSession,
    ctx: Context,
    due_before: date | None = None,
    include_completed: bool = False,
) -> list[FollowUpOut]:
    rows = followup_service.due_followups(
        db, ctx.user_id, before=due_before, include_completed=include_completed
    )
    out: list[FollowUpOut] = []
    for followup in rows:
        application = db.get(Application, followup.application_id)
        job = db.get(Job, application.job_id) if application else None
        out.append(
            FollowUpOut(
                **{
                    **FollowUpOut.model_validate(followup).model_dump(),
                    "company": job.company if job else "",
                    "job_title": job.title if job else "",
                }
            )
        )
    return out


@router.post("/followups/{followup_id}/complete", response_model=MessageResponse)
def complete_followup(followup_id: str, db: DbSession, ctx: Context) -> MessageResponse:
    followup = db.get(FollowUp, followup_id)
    if followup is None or followup.user_id != ctx.user_id:
        raise NotFoundError("That follow-up does not exist.")
    followup_service.complete_followup(db, followup_id)
    audit.record(
        db, action="followup.complete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="followup", entity_id=followup_id, summary="Marked a follow-up done",
    )
    return MessageResponse(message="Follow-up completed.")

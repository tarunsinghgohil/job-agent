"""Application queue, tracker, answer bank, and follow-up schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.models.enums import ApplicationChannel, ApplicationStatus
from app.schemas.common import ORMModel, TimestampedModel


# --------------------------------------------------------------------------
# Answer bank
# --------------------------------------------------------------------------
class AnswerIn(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    category: str = "general"
    variables: dict[str, Any] = Field(default_factory=dict)
    state: str = "verified"
    confidence: float = Field(default=1.0, ge=0, le=1)
    enabled: bool = True
    job_id: str | None = None
    company_normalized: str = ""
    priority: int = Field(default=100, ge=0, le=10000)


class AnswerOut(TimestampedModel):
    id: str
    question: str
    normalized_key: str
    answer: str
    category: str
    variables: dict[str, Any] = Field(default_factory=dict)
    source: str
    state: str
    confidence: float
    enabled: bool
    job_id: str | None = None
    company_normalized: str
    priority: int


class ResolveAnswerRequest(BaseModel):
    question: str = Field(min_length=1)
    job_id: str | None = None
    allow_ai: bool = True


class ResolvedAnswerOut(BaseModel):
    question: str
    answer: str
    state: str
    confidence: float
    resolved_from: str
    answer_bank_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    note: str = ""


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
class ApplicationIn(BaseModel):
    job_id: str
    resume_version_id: str | None = None
    channel: ApplicationChannel = ApplicationChannel.MANUAL
    notes: str = ""


class ApplicationPatch(BaseModel):
    resume_version_id: str | None = None
    channel: ApplicationChannel | None = None
    notes: str | None = None
    next_action: str | None = None
    next_action_due: date | None = None
    recruiter_id: str | None = None


class StatusChangeRequest(BaseModel):
    status: ApplicationStatus
    reason: str = ""


class RejectRequest(BaseModel):
    reason: str = ""


class SubmitRequest(BaseModel):
    """Explicit acknowledgement is required for approval-only lanes."""

    confirm_manual_submission: bool = False
    reference: str = ""


class ApplicationAnswerIn(BaseModel):
    question: str = Field(min_length=1)
    answer: str = ""
    state: str = "needs_review"
    confidence: float = Field(default=0.0, ge=0, le=1)


class ApplicationAnswerOut(ORMModel):
    id: str
    question: str
    answer: str
    state: str
    confidence: float
    resolved_from: str
    answer_bank_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ApplicationAssetOut(ORMModel):
    id: str
    asset_type: str
    content: str
    version: int
    is_current: bool
    generated_by: str
    model_used: str
    evidence_ids: list[str] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class StatusHistoryOut(ORMModel):
    id: str
    from_status: str
    to_status: str
    reason: str
    actor: str
    created_at: datetime


class ApplicationOut(TimestampedModel):
    id: str
    job_id: str
    job_title: str = ""
    company: str = ""
    job_url: str = ""
    resume_version_id: str | None = None
    status: str
    channel: str
    match_score: float | None = None
    approved_at: datetime | None = None
    submitted_at: datetime | None = None
    closed_at: datetime | None = None
    next_action: str = ""
    next_action_due: date | None = None
    notes: str = ""
    failure_reason: str = ""
    outcome_reason: str = ""


class ApplicationDetailOut(ApplicationOut):
    history: list[StatusHistoryOut] = Field(default_factory=list)
    answers: list[ApplicationAnswerOut] = Field(default_factory=list)
    assets: list[ApplicationAssetOut] = Field(default_factory=list)
    followups: list["FollowUpOut"] = Field(default_factory=list)


class PrepareResult(BaseModel):
    application_id: str
    assets_generated: list[str] = Field(default_factory=list)
    answers_resolved: int = 0
    answers_needing_review: int = 0
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Follow-ups
# --------------------------------------------------------------------------
class FollowUpIn(BaseModel):
    due_date: date
    kind: str = "check_in"
    note: str = ""


class FollowUpOut(TimestampedModel):
    id: str
    application_id: str
    due_date: date
    kind: str
    note: str
    completed_at: datetime | None = None
    notified_at: datetime | None = None
    company: str = ""
    job_title: str = ""


ApplicationDetailOut.model_rebuild()

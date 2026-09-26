"""Application answer engine (spec section 18).

Resolution order, most trustworthy first:
  1. job-specific override,
  2. company-specific override,
  3. exact question match in the answer bank,
  4. normalized-key match (so wording differences still hit),
  5. fuzzy match above a confidence floor,
  6. AI fallback grounded in stored evidence,
  7. nothing -- returned as ``needs_review`` rather than invented.

The engine never fabricates. When it cannot ground an answer it says so.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.applications import AnswerBankEntry
from app.db.models.enums import AnswerState
from app.db.models.identity import CareerProfile
from app.db.models.jobs import Job
from app.services.normalize import jaccard, norm_text, normalize_company, tokens

logger = logging.getLogger(__name__)

FUZZY_ACCEPT_THRESHOLD = 0.62

# Common question phrasings collapse onto one key so "Years of React?" and
# "How many years of React experience do you have?" resolve to the same answer.
_QUESTION_NOISE = {
    "how", "many", "much", "what", "is", "are", "do", "does", "you", "your",
    "the", "a", "an", "of", "in", "for", "to", "have", "with", "please",
    "tell", "us", "about", "can", "could", "would", "will", "and", "or",
    "years", "year", "yrs", "experience", "total",
}


def normalize_question(question: str) -> str:
    """Stable key for a question, ignoring phrasing noise and punctuation."""
    words = [w for w in tokens(question) if w not in _QUESTION_NOISE]
    return " ".join(sorted(words))[:200]


@dataclass(slots=True)
class ResolvedAnswer:
    question: str
    answer: str = ""
    state: str = AnswerState.NEEDS_REVIEW
    confidence: float = 0.0
    resolved_from: str = "none"
    answer_bank_id: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "state": str(self.state),
            "confidence": round(self.confidence, 3),
            "resolved_from": self.resolved_from,
            "answer_bank_id": self.answer_bank_id,
            "evidence_ids": self.evidence_ids,
            "note": self.note,
        }


_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def render_variables(template: str, context: dict[str, Any]) -> str:
    """Substitute ``{{ key }}`` placeholders from the profile context.

    An unresolved placeholder is left intact rather than blanked, so a missing
    value is visible to the user instead of silently producing a broken answer.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = context.get(key)
        return str(value) if value not in (None, "") else match.group(0)

    return _VARIABLE_RE.sub(replace, template or "")


def profile_context(profile: CareerProfile | None) -> dict[str, Any]:
    if profile is None:
        return {}
    context: dict[str, Any] = {
        "full_name": profile.full_name,
        "email": profile.email,
        "phone": profile.phone,
        "location": profile.location,
        "headline": profile.headline,
        "notice_period": profile.notice_period,
        "current_ctc": profile.current_ctc_lpa,
        "expected_ctc": profile.expected_ctc_lpa,
        "total_experience": profile.total_experience_years,
        "relocation": "Yes" if profile.open_to_relocation else "No",
        "work_authorization": "Yes" if profile.work_authorization else "No",
    }
    for ps in profile.profile_skills or []:
        if ps.skill and ps.years is not None:
            context[f"years_{norm_text(ps.skill.name).replace(' ', '_')}"] = ps.years
    return context


def _candidates(db: Session, user_id: str, job: Job | None) -> list[AnswerBankEntry]:
    stmt = select(AnswerBankEntry).where(
        AnswerBankEntry.user_id == user_id, AnswerBankEntry.enabled.is_(True)
    )
    rows = list(db.execute(stmt).scalars().all())

    company_key = normalize_company(job.company) if job else ""
    job_id = job.id if job else None

    def applicable(entry: AnswerBankEntry) -> bool:
        if entry.job_id and entry.job_id != job_id:
            return False
        if entry.company_normalized and entry.company_normalized != company_key:
            return False
        return True

    def rank(entry: AnswerBankEntry) -> tuple[int, int]:
        # Job override beats company override beats general; then user priority.
        specificity = 0 if entry.job_id else (1 if entry.company_normalized else 2)
        return (specificity, entry.priority)

    return sorted((e for e in rows if applicable(e)), key=rank)


def resolve_answer(
    db: Session,
    user_id: str,
    question: str,
    *,
    job: Job | None = None,
    profile: CareerProfile | None = None,
    ai_service: Any = None,
    allow_ai: bool = True,
) -> ResolvedAnswer:
    """Resolve one question. Deterministic sources always win over AI."""
    question = (question or "").strip()
    if not question:
        return ResolvedAnswer(question="", note="No question was supplied.")

    result = ResolvedAnswer(question=question)
    context = profile_context(profile)
    entries = _candidates(db, user_id, job)
    target_key = normalize_question(question)
    question_norm = norm_text(question)

    # 1-3. exact question text, honouring override specificity ordering.
    for entry in entries:
        if norm_text(entry.question) == question_norm:
            result.answer = render_variables(entry.answer, context)
            result.state = entry.state or AnswerState.VERIFIED
            result.confidence = float(entry.confidence or 1.0)
            result.resolved_from = (
                "job_override" if entry.job_id
                else "company_override" if entry.company_normalized
                else "answer_bank"
            )
            result.answer_bank_id = entry.id
            return result

    # 4. normalized key match.
    for entry in entries:
        entry_key = entry.normalized_key or normalize_question(entry.question)
        if entry_key and entry_key == target_key:
            result.answer = render_variables(entry.answer, context)
            result.state = entry.state or AnswerState.VERIFIED
            result.confidence = min(1.0, float(entry.confidence or 1.0) * 0.95)
            result.resolved_from = "normalized_key"
            result.answer_bank_id = entry.id
            return result

    # 5. fuzzy match.
    best: tuple[float, AnswerBankEntry | None] = (0.0, None)
    for entry in entries:
        similarity = jaccard(tokens(question), tokens(entry.question))
        if similarity > best[0]:
            best = (similarity, entry)

    if best[1] is not None and best[0] >= FUZZY_ACCEPT_THRESHOLD:
        entry = best[1]
        result.answer = render_variables(entry.answer, context)
        result.state = AnswerState.INFERRED
        result.confidence = round(best[0], 3)
        result.resolved_from = "fuzzy_match"
        result.answer_bank_id = entry.id
        result.note = f"Matched the stored question {entry.question!r}. Confirm before submitting."
        return result

    # 6. AI fallback, grounded in evidence.
    if allow_ai and ai_service is not None and getattr(ai_service, "enabled", False):
        try:
            from app.services.ai.functions import answer_question

            known = [(e.question, e.answer) for e in entries[:25]]
            data = answer_question(
                db, ai_service, user_id, question, profile, known, job=job
            )
            answer_text = str(data.get("answer") or "").strip()
            if answer_text:
                result.answer = answer_text
                needs_review = bool(data.get("needs_review", True))
                result.confidence = float(data.get("confidence") or 0.5)
                result.state = (
                    AnswerState.NEEDS_REVIEW if needs_review or result.confidence < 0.7
                    else AnswerState.INFERRED
                )
                result.resolved_from = "ai"
                result.evidence_ids = [
                    str(e) for e in (data.get("evidence_used") or []) if e
                ]
                result.note = "Drafted from stored evidence. Review before submitting."
                return result
        except Exception as exc:
            logger.info("AI answer fallback failed for %r: %s", question[:60], exc)
            result.note = "No stored answer, and the AI draft could not be generated."
            return result

    result.note = (
        "No stored answer matched. Add one to the answer bank, or enable AI drafting."
    )
    return result


def upsert_entry(
    db: Session,
    user_id: str,
    question: str,
    answer: str,
    **fields: Any,
) -> AnswerBankEntry:
    """Create or update a bank entry, keeping ``normalized_key`` in sync."""
    key = normalize_question(question)
    job_id = fields.get("job_id")
    company = fields.get("company_normalized", "")

    stmt = select(AnswerBankEntry).where(
        AnswerBankEntry.user_id == user_id,
        AnswerBankEntry.normalized_key == key,
    )
    existing = None
    for row in db.execute(stmt).scalars().all():
        if (row.job_id or None) == (job_id or None) and (row.company_normalized or "") == (company or ""):
            existing = row
            break

    if existing is None:
        existing = AnswerBankEntry(user_id=user_id, question=question, answer=answer)
        db.add(existing)

    existing.question = question
    existing.answer = answer
    existing.normalized_key = key
    for name, value in fields.items():
        if value is not None and hasattr(existing, name):
            setattr(existing, name, value)
    return existing

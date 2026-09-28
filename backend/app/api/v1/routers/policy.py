"""Preferences, matching rules, and saved searches.

This is the router that makes the product configurable instead of hard-coded:
everything the matching engine reads is edited through here.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import Context, CurrentPreferences, DbSession
from app.core.errors import NotFoundError
from app.db.models.preferences import JobPreference, MatchRule, SavedSearch
from app.schemas.common import MessageResponse
from app.schemas.policy import (
    MatchRuleIn,
    MatchRuleOut,
    PreferencesIn,
    PreferencesOut,
    RuleTestRequest,
    SavedSearchIn,
    SavedSearchOut,
)
from app.services import audit
from app.services.jobs import get_owned_job
from app.services.rules import evaluate_rules

router = APIRouter(tags=["policy"])

_PREF_FIELDS = list(PreferencesIn.model_fields.keys())


def _serialize_prefs(prefs: JobPreference) -> PreferencesOut:
    return PreferencesOut(
        id=prefs.id,
        created_at=prefs.created_at,
        updated_at=prefs.updated_at,
        **{f: getattr(prefs, f) for f in _PREF_FIELDS},
    )


def _serialize_rule(rule: MatchRule) -> MatchRuleOut:
    raw = rule.value or {}
    return MatchRuleOut(
        id=rule.id,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        name=rule.name,
        field=rule.field,
        operator=rule.operator,
        value=raw.get("value") if isinstance(raw, dict) else raw,
        weight=rule.weight,
        is_hard=rule.is_hard,
        enabled=rule.enabled,
        priority=rule.priority,
        explanation=rule.explanation,
        case_sensitive=rule.case_sensitive,
    )


# --------------------------------------------------------------------------
# Preferences
# --------------------------------------------------------------------------
@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(prefs: CurrentPreferences) -> PreferencesOut:
    if not prefs.scoring_weights:
        prefs.scoring_weights = JobPreference.default_weights()
    return _serialize_prefs(prefs)


@router.put("/preferences", response_model=PreferencesOut)
def update_preferences(
    payload: PreferencesIn, db: DbSession, prefs: CurrentPreferences, ctx: Context
) -> PreferencesOut:
    changes: dict[str, Any] = {}
    for name, value in payload.model_dump().items():
        if getattr(prefs, name, None) != value:
            changes[name] = value
            setattr(prefs, name, value)

    if not prefs.scoring_weights:
        prefs.scoring_weights = JobPreference.default_weights()

    db.flush()
    if changes:
        from app.services.suggest import invalidate_user

        invalidate_user(ctx.user_id)
        audit.record(
            db,
            action="preferences.update",
            user_id=ctx.user_id,
            actor=ctx.actor,
            entity_type="job_preferences",
            entity_id=prefs.id,
            summary=f"Updated preferences: {', '.join(sorted(changes))}",
            after=changes,
            ip_address=ctx.ip_address,
        )
    return _serialize_prefs(prefs)


@router.post("/preferences/reset-weights", response_model=PreferencesOut)
def reset_weights(db: DbSession, prefs: CurrentPreferences, ctx: Context) -> PreferencesOut:
    prefs.scoring_weights = JobPreference.default_weights()
    db.flush()
    audit.record(
        db, action="preferences.reset_weights", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="job_preferences", entity_id=prefs.id,
        summary="Reset scoring weights to defaults",
    )
    return _serialize_prefs(prefs)


# --------------------------------------------------------------------------
# Matching rules
# --------------------------------------------------------------------------
@router.get("/rules", response_model=list[MatchRuleOut])
def list_rules(db: DbSession, ctx: Context) -> list[MatchRuleOut]:
    rows = db.execute(
        select(MatchRule).where(MatchRule.user_id == ctx.user_id).order_by(MatchRule.priority)
    ).scalars().all()
    return [_serialize_rule(r) for r in rows]


@router.post("/rules", response_model=MatchRuleOut, status_code=201)
def create_rule(payload: MatchRuleIn, db: DbSession, ctx: Context) -> MatchRuleOut:
    rule = MatchRule(
        user_id=ctx.user_id,
        name=payload.name,
        field=str(payload.field),
        operator=str(payload.operator),
        value=payload.value,
        weight=payload.weight,
        is_hard=payload.is_hard,
        enabled=payload.enabled,
        priority=payload.priority,
        explanation=payload.explanation,
        case_sensitive=payload.case_sensitive,
    )
    db.add(rule)
    db.flush()
    audit.record(
        db, action="rule.create", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="match_rule", entity_id=rule.id,
        summary=f"Created {'hard' if rule.is_hard else 'soft'} rule: {rule.name}",
        after={"field": rule.field, "operator": rule.operator, "is_hard": rule.is_hard},
    )
    return _serialize_rule(rule)


def _owned_rule(db: Any, user_id: str, rule_id: str) -> MatchRule:
    rule = db.get(MatchRule, rule_id)
    if rule is None or rule.user_id != user_id:
        raise NotFoundError("That rule does not exist.")
    return rule


@router.put("/rules/{rule_id}", response_model=MatchRuleOut)
def update_rule(
    rule_id: str, payload: MatchRuleIn, db: DbSession, ctx: Context
) -> MatchRuleOut:
    rule = _owned_rule(db, ctx.user_id, rule_id)
    before = {"field": rule.field, "operator": rule.operator, "is_hard": rule.is_hard,
              "weight": rule.weight, "enabled": rule.enabled}

    rule.name = payload.name
    rule.field = str(payload.field)
    rule.operator = str(payload.operator)
    rule.value = payload.value
    rule.weight = payload.weight
    rule.is_hard = payload.is_hard
    rule.enabled = payload.enabled
    rule.priority = payload.priority
    rule.explanation = payload.explanation
    rule.case_sensitive = payload.case_sensitive
    db.flush()

    audit.record(
        db, action="rule.update", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="match_rule", entity_id=rule.id,
        summary=f"Updated rule: {rule.name}", before=before,
        after={"field": rule.field, "operator": rule.operator, "is_hard": rule.is_hard,
               "weight": rule.weight, "enabled": rule.enabled},
    )
    return _serialize_rule(rule)


@router.delete("/rules/{rule_id}", response_model=MessageResponse)
def delete_rule(rule_id: str, db: DbSession, ctx: Context) -> MessageResponse:
    rule = _owned_rule(db, ctx.user_id, rule_id)
    name = rule.name
    db.delete(rule)
    audit.record(
        db, action="rule.delete", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="match_rule", entity_id=rule_id, summary=f"Deleted rule: {name}",
    )
    return MessageResponse(message="Rule deleted. Re-score jobs to apply the change.")


@router.post("/rules/{rule_id}/test")
def test_rule(
    rule_id: str, payload: RuleTestRequest, db: DbSession, ctx: Context
) -> dict[str, Any]:
    """Evaluate a single rule against a real job, for the rule builder UI."""
    rule = _owned_rule(db, ctx.user_id, rule_id)
    job = get_owned_job(db, ctx.user_id, payload.job_id)
    if job is None:
        raise NotFoundError("That job does not exist.")

    evaluation = evaluate_rules(job, [rule])
    outcome = evaluation.outcomes[0] if evaluation.outcomes else None
    return {
        "rule_id": rule.id,
        "job_id": job.id,
        "job_title": job.title,
        "passed": outcome.passed if outcome else False,
        "detail": outcome.detail if outcome else "Rule is disabled.",
        "is_hard": rule.is_hard,
        "awarded": outcome.awarded if outcome else 0.0,
        "would_reject": bool(evaluation.hard_failures),
    }


# --------------------------------------------------------------------------
# Saved searches
# --------------------------------------------------------------------------
@router.get("/saved-searches", response_model=list[SavedSearchOut])
def list_saved_searches(db: DbSession, ctx: Context) -> list[SavedSearchOut]:
    rows = db.execute(
        select(SavedSearch).where(SavedSearch.user_id == ctx.user_id).order_by(SavedSearch.name)
    ).scalars().all()
    return [SavedSearchOut.model_validate(r) for r in rows]


@router.post("/saved-searches", response_model=SavedSearchOut, status_code=201)
def create_saved_search(payload: SavedSearchIn, db: DbSession, ctx: Context) -> SavedSearchOut:
    search = SavedSearch(user_id=ctx.user_id, **payload.model_dump())
    db.add(search)
    db.flush()
    audit.record(
        db, action="saved_search.create", user_id=ctx.user_id, actor=ctx.actor,
        entity_type="saved_search", entity_id=search.id, summary=f"Saved search: {search.name}",
    )
    return SavedSearchOut.model_validate(search)


@router.put("/saved-searches/{search_id}", response_model=SavedSearchOut)
def update_saved_search(
    search_id: str, payload: SavedSearchIn, db: DbSession, ctx: Context
) -> SavedSearchOut:
    search = db.get(SavedSearch, search_id)
    if search is None or search.user_id != ctx.user_id:
        raise NotFoundError("That saved search does not exist.")
    for name, value in payload.model_dump().items():
        setattr(search, name, value)
    db.flush()
    return SavedSearchOut.model_validate(search)


@router.delete("/saved-searches/{search_id}", response_model=MessageResponse)
def delete_saved_search(search_id: str, db: DbSession, ctx: Context) -> MessageResponse:
    search = db.get(SavedSearch, search_id)
    if search is None or search.user_id != ctx.user_id:
        raise NotFoundError("That saved search does not exist.")
    db.delete(search)
    return MessageResponse(message="Saved search deleted.")

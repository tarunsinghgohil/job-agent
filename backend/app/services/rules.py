"""Dynamic rule engine.

Users build rules in the dashboard (field / operator / value / weight / hard).
This module evaluates them against a job. It is deliberately the only place
that knows how to interpret a rule, so the UI, the matcher and the rule-test
endpoint can never drift apart.

Rules are data, not code: adding a rule must never require a deployment.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.db.models.enums import RuleField, RuleOperator
from app.services.normalize import norm_text, normalize_company, tokens

# Regex evaluation is bounded so a pathological user-authored pattern cannot
# hang a request. Patterns are user-supplied but single-user, so this is a
# guardrail against mistakes rather than a hostile-input defence.
_MAX_PATTERN_LENGTH = 200


@dataclass(slots=True)
class RuleOutcome:
    rule_id: str
    name: str
    field: str
    operator: str
    passed: bool
    is_hard: bool
    weight: float
    awarded: float
    explanation: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "field": self.field,
            "operator": self.operator,
            "passed": self.passed,
            "is_hard": self.is_hard,
            "weight": self.weight,
            "awarded": self.awarded,
            "explanation": self.explanation,
            "detail": self.detail,
        }


@dataclass(slots=True)
class RuleEvaluation:
    outcomes: list[RuleOutcome] = field(default_factory=list)
    hard_failures: list[str] = field(default_factory=list)
    bonus: float = 0.0

    @property
    def passed_hard(self) -> bool:
        return not self.hard_failures


class JobView:
    """Adapter exposing a Job (ORM row or plain dict) as rule-addressable fields.

    Accepting both means the rule-test endpoint can evaluate an unsaved job
    without first persisting it.
    """

    def __init__(self, job: Any):
        self._job = job

    def _get(self, name: str, default: Any = None) -> Any:
        if isinstance(self._job, dict):
            return self._job.get(name, default)
        return getattr(self._job, name, default)

    def value_for(self, rule_field: str) -> Any:
        if rule_field == RuleField.TITLE:
            return self._get("title", "") or ""
        if rule_field == RuleField.COMPANY:
            return self._get("company", "") or ""
        if rule_field == RuleField.LOCATION:
            return self._get("location", "") or ""
        if rule_field == RuleField.DESCRIPTION:
            return self._get("description", "") or ""
        if rule_field == RuleField.INDUSTRY:
            return self._get("industry", "") or ""
        if rule_field == RuleField.EMPLOYMENT_TYPE:
            return self._get("employment_type", "") or ""
        if rule_field == RuleField.SOURCE:
            return self._get("source_name", "") or ""
        if rule_field == RuleField.REMOTE:
            return bool(self._get("is_remote", False))
        if rule_field == RuleField.SALARY_LPA:
            # Compare against the top of the range: a job offering 14-18 LPA
            # satisfies a ">= 16" rule.
            return self._get("salary_max_lpa") or self._get("salary_min_lpa")
        if rule_field == RuleField.EXPERIENCE_MIN:
            return self._get("experience_min_years")
        if rule_field == RuleField.EXPERIENCE_MAX:
            return self._get("experience_max_years")
        if rule_field == RuleField.SKILLS:
            skills = self._get("skills") or []
            names = []
            for s in skills:
                if isinstance(s, str):
                    names.append(s)
                else:
                    names.append(getattr(s, "skill_name", "") or getattr(s, "skill_slug", ""))
            return [n for n in names if n]
        return self._get(rule_field)

    def searchable_text(self) -> str:
        return norm_text(
            " ".join(
                str(x or "")
                for x in (
                    self._get("title"),
                    self._get("company"),
                    self._get("description"),
                    self._get("industry"),
                    self._get("location"),
                )
            )
        )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _rule_value(raw: Any) -> Any:
    """Rule values are stored as JSON ``{"value": ...}`` or a bare scalar."""
    if isinstance(raw, dict):
        if "value" in raw:
            return raw["value"]
        if "values" in raw:
            return raw["values"]
        return raw
    return raw


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _text_of(actual: Any, case_sensitive: bool) -> str:
    if isinstance(actual, (list, tuple, set)):
        joined = " ".join(str(a) for a in actual)
    else:
        joined = str(actual or "")
    return joined if case_sensitive else norm_text(joined)


def _needle(expected: Any, case_sensitive: bool) -> str:
    return str(expected) if case_sensitive else norm_text(str(expected))


def evaluate_operator(
    operator: str,
    actual: Any,
    expected: Any,
    *,
    case_sensitive: bool = False,
) -> tuple[bool, str]:
    """Return ``(passed, detail)``. Never raises on bad user input."""
    op = str(operator)

    if op in (RuleOperator.CONTAINS, RuleOperator.NOT_CONTAINS):
        haystack = _text_of(actual, case_sensitive)
        wanted = [_needle(e, case_sensitive) for e in _as_list(expected) if str(e).strip()]
        if not wanted:
            return (True, "no value configured")
        hits = [w for w in wanted if w and w in haystack]
        if op == RuleOperator.CONTAINS:
            return (bool(hits), f"matched {hits}" if hits else f"none of {wanted} present")
        return (not hits, f"excluded term present: {hits}" if hits else "no excluded terms")

    if op in (RuleOperator.EQUALS, RuleOperator.NOT_EQUALS):
        left = _text_of(actual, case_sensitive)
        right = _needle(expected, case_sensitive)
        equal = left == right
        if op == RuleOperator.EQUALS:
            return (equal, f"{left!r} == {right!r}" if equal else f"{left!r} != {right!r}")
        return (not equal, f"{left!r} != {right!r}" if not equal else f"{left!r} == {right!r}")

    if op in (RuleOperator.IN, RuleOperator.NOT_IN):
        left = _text_of(actual, case_sensitive)
        options = [_needle(e, case_sensitive) for e in _as_list(expected)]
        # Substring rather than equality: "Jaipur, Rajasthan" should satisfy
        # a location rule listing "Jaipur".
        present = any(o and (o in left or left in o) for o in options if o)
        if op == RuleOperator.IN:
            return (present, f"{left!r} in {options}" if present else f"{left!r} not in {options}")
        return (not present, f"{left!r} not in {options}" if not present else f"{left!r} in {options}")

    if op in (RuleOperator.GTE, RuleOperator.LTE, RuleOperator.GT, RuleOperator.LT):
        left = _to_number(actual)
        right = _to_number(_as_list(expected)[0] if _as_list(expected) else expected)
        if left is None or right is None:
            # Unknown data must not silently pass a hard numeric filter.
            return (False, "value unavailable for numeric comparison")
        result = {
            RuleOperator.GTE: left >= right,
            RuleOperator.LTE: left <= right,
            RuleOperator.GT: left > right,
            RuleOperator.LT: left < right,
        }[op]
        return (result, f"{left} {op} {right}")

    if op == RuleOperator.BETWEEN:
        values = _as_list(expected)
        left = _to_number(actual)
        if left is None or len(values) < 2:
            return (False, "value unavailable for range comparison")
        low, high = _to_number(values[0]), _to_number(values[1])
        if low is None or high is None:
            return (False, "invalid range bounds")
        if low > high:
            low, high = high, low
        return (low <= left <= high, f"{low} <= {left} <= {high}")

    if op == RuleOperator.REGEX:
        pattern = str(_as_list(expected)[0] if _as_list(expected) else expected or "")
        if not pattern or len(pattern) > _MAX_PATTERN_LENGTH:
            return (False, "pattern missing or too long")
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            found = re.search(pattern, _text_of(actual, True), flags) is not None
        except re.error as exc:
            return (False, f"invalid regular expression: {exc}")
        return (found, "pattern matched" if found else "pattern did not match")

    return (True, f"unknown operator {op!r}; rule skipped")


def evaluate_rules(job: Any, rules: list[Any]) -> RuleEvaluation:
    """Evaluate every enabled rule, highest priority first.

    Hard rules that fail produce a hard failure. Soft rules contribute their
    weight as a bonus when they pass. Soft rules never subtract, so a user
    cannot accidentally drive a score negative by adding rules.
    """
    evaluation = RuleEvaluation()
    ordered = sorted(
        (r for r in rules if getattr(r, "enabled", True)),
        key=lambda r: getattr(r, "priority", 100),
    )

    view = JobView(job)
    for rule in ordered:
        rule_field = getattr(rule, "field", "")
        actual = view.value_for(rule_field)
        expected = _rule_value(getattr(rule, "value", None))
        operator = getattr(rule, "operator", RuleOperator.CONTAINS)
        case_sensitive = bool(getattr(rule, "case_sensitive", False))

        passed, detail = evaluate_operator(
            operator, actual, expected, case_sensitive=case_sensitive
        )
        is_hard = bool(getattr(rule, "is_hard", False))
        weight = float(getattr(rule, "weight", 0.0) or 0.0)
        awarded = weight if (passed and not is_hard) else 0.0

        explanation = getattr(rule, "explanation", "") or ""
        name = getattr(rule, "name", "") or f"{rule_field} {operator}"

        if not passed and is_hard:
            evaluation.hard_failures.append(explanation or f"Failed required rule: {name}")
        if awarded:
            evaluation.bonus += awarded

        evaluation.outcomes.append(
            RuleOutcome(
                rule_id=str(getattr(rule, "id", "")),
                name=name,
                field=str(rule_field),
                operator=str(operator),
                passed=passed,
                is_hard=is_hard,
                weight=weight,
                awarded=awarded,
                explanation=explanation,
                detail=detail,
            )
        )

    return evaluation

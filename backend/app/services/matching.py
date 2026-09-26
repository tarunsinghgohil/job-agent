"""The matching engine (spec section 8).

Hybrid model, in a fixed order:

1. **Deterministic hard filters** -- must-have keywords, salary floor, excluded
   keywords, employment type, location, experience bounds, excluded companies,
   and any user rule flagged ``is_hard``. A hard failure forces ``REJECT``
   regardless of how attractive the rest of the job looks. Deterministic rules
   have final authority; AI never overrides them.
2. **Weighted scoring** -- every factor yields a 0..1 ratio multiplied by a
   user-editable weight. Default weights sum to 100.
3. **Semantic scoring** -- optional, opt-in, and only ever applied *after* the
   deterministic pass, because it costs money per job.

The output is deliberately verbose: the UI has to be able to explain to the
user exactly why a job scored what it did.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.normalize import norm_text, normalize_company, tokens
from app.services.rules import JobView, RuleEvaluation, evaluate_rules

ENGINE_VERSION = "2"

# Roles are matched on meaningful tokens only; "developer" alone should not
# make every job a role match.
_STOPWORD_ROLE_TOKENS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "at", "on",
    "senior", "junior", "lead", "staff", "principal", "mid", "level", "sr", "jr",
}


@dataclass(slots=True)
class MatchResult:
    score: float = 0.0
    decision: str = "REJECT"
    deterministic_score: float = 0.0
    semantic_score: float | None = None
    breakdown: dict[str, float] = field(default_factory=dict)
    hard_fail_reasons: list[str] = field(default_factory=list)
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    positive_signals: list[str] = field(default_factory=list)
    rule_results: list[dict] = field(default_factory=list)
    explanation: str = ""
    recommended_resume_id: str | None = None
    recommendation_reason: str = ""
    engine_version: str = ENGINE_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "decision": self.decision,
            "deterministic_score": round(self.deterministic_score, 2),
            "semantic_score": self.semantic_score,
            "breakdown": {k: round(v, 2) for k, v in self.breakdown.items()},
            "hard_fail_reasons": self.hard_fail_reasons,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "positive_signals": self.positive_signals,
            "rule_results": self.rule_results,
            "explanation": self.explanation,
            "recommended_resume_id": self.recommended_resume_id,
            "recommendation_reason": self.recommendation_reason,
            "engine_version": self.engine_version,
        }


def _keyword_present(keyword: str, haystack: str) -> bool:
    """Substring match on normalized text.

    Normalization keeps ``.``/``+``/``#``, so "React.js" and "Node.js" survive
    and "react" still matches "React.js" as a substring.
    """
    needle = norm_text(keyword)
    return bool(needle) and needle in haystack


def _role_matches(title: str, target_roles: list[str]) -> tuple[bool, str | None]:
    """A role matches on full-phrase containment or a strong token overlap."""
    title_norm = norm_text(title)
    title_tokens = tokens(title) - _STOPWORD_ROLE_TOKENS
    best: tuple[float, str | None] = (0.0, None)

    for role in target_roles or []:
        role_norm = norm_text(role)
        if not role_norm:
            continue
        if role_norm in title_norm:
            return (True, role)
        role_tokens = tokens(role) - _STOPWORD_ROLE_TOKENS
        if not role_tokens:
            continue
        overlap = len(role_tokens & title_tokens) / len(role_tokens)
        if overlap > best[0]:
            best = (overlap, role)

    # Two thirds of the meaningful words of a target role must appear.
    return (best[0] >= 0.66, best[1] if best[0] >= 0.66 else None)


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator <= 0 else max(0.0, min(1.0, numerator / denominator))


def _salary_fit(job: JobView, prefs: Any) -> tuple[float, str | None]:
    """0 when below the floor, 1 at or above target, linear in between.

    An unknown salary scores a neutral 0.5 rather than 0, because most feeds
    omit compensation and scoring those jobs to zero would bury them.
    """
    top = job.value_for("salary_lpa")
    minimum = getattr(prefs, "min_salary_lpa", None)
    target = getattr(prefs, "target_salary_lpa", None)

    if top is None:
        return (0.5, None)
    if minimum and top < minimum:
        return (0.0, None)
    if target and top >= target:
        return (1.0, f"Pays {top} LPA, at or above the {target} LPA target")
    if minimum and target and target > minimum:
        return (_ratio(top - minimum, target - minimum), None)
    return (1.0, f"Pays {top} LPA")


def _experience_fit(job: JobView, prefs: Any) -> tuple[float, bool, str]:
    """Return ``(ratio, hard_fail, reason)`` for the experience window."""
    job_min = job.value_for("experience_min")
    job_max = job.value_for("experience_max")
    user_min = getattr(prefs, "experience_min_years", None)
    user_max = getattr(prefs, "experience_max_years", None)

    if job_min is None and job_max is None:
        return (0.6, False, "")
    if user_min is None and user_max is None:
        return (1.0, False, "")

    # The job's requirement must overlap the user's configured window.
    lo = job_min if job_min is not None else 0.0
    hi = job_max if job_max is not None else float("inf")
    u_lo = user_min if user_min is not None else 0.0
    u_hi = user_max if user_max is not None else float("inf")

    if lo > u_hi:
        return (0.0, True, f"Requires {lo}+ years, above the configured maximum of {u_hi}")
    if hi < u_lo:
        return (0.0, True, f"Caps experience at {hi} years, below the configured minimum of {u_lo}")
    return (1.0, False, "")


def _location_fit(job: JobView, prefs: Any) -> tuple[float, bool, str, str | None]:
    """Return ``(ratio, hard_fail, reason, signal)``."""
    is_remote = bool(job.value_for("remote"))
    remote_ok = bool(getattr(prefs, "remote_ok", True))
    remote_only = bool(getattr(prefs, "remote_only", False))
    preferred = [p for p in (getattr(prefs, "preferred_locations", None) or []) if str(p).strip()]
    location_norm = norm_text(job.value_for("location"))

    if is_remote and remote_ok:
        return (1.0, False, "", "Remote role")
    if remote_only and not is_remote:
        return (0.0, True, "Remote-only is set and this role is not remote", None)
    if not preferred:
        return (0.7, False, "", None)
    if not location_norm:
        return (0.5, False, "", None)

    for pref in preferred:
        pref_norm = norm_text(pref)
        if pref_norm and (pref_norm in location_norm or location_norm in pref_norm):
            return (1.0, False, "", f"Located in {pref}")

    return (
        0.0,
        True,
        f"Location {job.value_for('location')!r} is not in the preferred list",
        None,
    )


def score_job(
    job: Any,
    preferences: Any,
    rules: list[Any] | None = None,
    *,
    resumes: list[Any] | None = None,
    semantic_score: float | None = None,
) -> MatchResult:
    """Score one job. Pure: it reads nothing and writes nothing."""
    view = JobView(job)
    result = MatchResult()
    haystack = view.searchable_text()
    title = str(view.value_for("title") or "")

    weights = dict(getattr(preferences, "scoring_weights", None) or {})
    if not weights:
        from app.db.models.preferences import JobPreference

        weights = JobPreference.default_weights()

    def weight_of(key: str) -> float:
        return float(weights.get(key, 0.0) or 0.0)

    # --- 1. deterministic hard filters -----------------------------------
    must_have = [k for k in (getattr(preferences, "must_have_keywords", None) or []) if str(k).strip()]
    matched_must = [k for k in must_have if _keyword_present(k, haystack)]
    missing_must = [k for k in must_have if k not in matched_must]
    if must_have and not matched_must:
        result.hard_fail_reasons.append(
            f"None of the required keywords are present: {', '.join(must_have)}"
        )
    elif missing_must:
        result.missing_skills.extend(missing_must)

    excluded = [k for k in (getattr(preferences, "excluded_keywords", None) or []) if str(k).strip()]
    for keyword in excluded:
        if _keyword_present(keyword, haystack):
            result.hard_fail_reasons.append(f"Contains excluded keyword: {keyword}")

    company_norm = normalize_company(view.value_for("company"))
    for blocked in getattr(preferences, "excluded_companies", None) or []:
        if company_norm and normalize_company(blocked) == company_norm:
            result.hard_fail_reasons.append(f"{view.value_for('company')} is on the excluded list")

    allowed_employment = [
        norm_text(e) for e in (getattr(preferences, "employment_types", None) or []) if str(e).strip()
    ]
    job_employment = norm_text(view.value_for("employment_type"))
    if allowed_employment and job_employment and job_employment not in allowed_employment:
        result.hard_fail_reasons.append(
            f"Employment type {job_employment!r} is not in the allowed list"
        )

    salary_ratio, salary_signal = _salary_fit(view, preferences)
    minimum = getattr(preferences, "min_salary_lpa", None)
    top_salary = view.value_for("salary_lpa")
    if minimum and top_salary is not None and top_salary < minimum:
        result.hard_fail_reasons.append(
            f"Pays {top_salary} LPA, below the {minimum} LPA minimum"
        )

    exp_ratio, exp_fail, exp_reason = _experience_fit(view, preferences)
    if exp_fail:
        result.hard_fail_reasons.append(exp_reason)

    loc_ratio, loc_fail, loc_reason, loc_signal = _location_fit(view, preferences)
    if loc_fail:
        result.hard_fail_reasons.append(loc_reason)

    # --- 2. user-authored rules ------------------------------------------
    rule_eval: RuleEvaluation = evaluate_rules(job, rules or [])
    result.rule_results = [o.as_dict() for o in rule_eval.outcomes]
    result.hard_fail_reasons.extend(rule_eval.hard_failures)

    # --- 3. weighted scoring ----------------------------------------------
    must_ratio = 1.0 if not must_have else _ratio(len(matched_must), len(must_have))
    result.breakdown["must_have_skills"] = must_ratio * weight_of("must_have_skills")
    result.matched_skills.extend(matched_must)

    role_hit, matched_role = _role_matches(title, getattr(preferences, "target_roles", None) or [])
    result.breakdown["role_fit"] = (1.0 if role_hit else 0.35) * weight_of("role_fit")
    if matched_role:
        result.positive_signals.append(f"Title matches target role: {matched_role}")

    nice = [k for k in (getattr(preferences, "nice_to_have_keywords", None) or []) if str(k).strip()]
    matched_nice = [k for k in nice if _keyword_present(k, haystack)]
    missing_nice = [k for k in nice if k not in matched_nice]
    # Half the listed nice-to-haves is treated as full marks; no job lists them all.
    nice_ratio = 1.0 if not nice else min(1.0, len(matched_nice) / max(1.0, len(nice) * 0.5))
    result.breakdown["preferred_skills"] = nice_ratio * weight_of("preferred_skills")
    result.matched_skills.extend(matched_nice)
    result.missing_skills.extend(missing_nice[:8])

    result.breakdown["experience_fit"] = exp_ratio * weight_of("experience_fit")
    result.breakdown["location_fit"] = loc_ratio * weight_of("location_fit")
    result.breakdown["salary_fit"] = salary_ratio * weight_of("salary_fit")
    if salary_signal:
        result.positive_signals.append(salary_signal)
    if loc_signal:
        result.positive_signals.append(loc_signal)

    industries = [norm_text(i) for i in (getattr(preferences, "industries", None) or []) if str(i).strip()]
    job_industry = norm_text(view.value_for("industry"))
    industry_hit = bool(industries) and any(
        i and (i in job_industry or job_industry in i) for i in industries if job_industry
    )
    result.breakdown["industry_fit"] = (
        1.0 if industry_hit else (0.5 if not industries else 0.0)
    ) * weight_of("industry_fit")
    if industry_hit:
        result.positive_signals.append(f"Industry match: {view.value_for('industry')}")

    preferred_companies = [
        normalize_company(c)
        for c in (getattr(preferences, "preferred_companies", None) or [])
        if str(c).strip() and norm_text(c) != "any"
    ]
    company_hit = bool(company_norm) and company_norm in preferred_companies
    result.breakdown["company_preference"] = (
        1.0 if company_hit else (0.5 if not preferred_companies else 0.0)
    ) * weight_of("company_preference")
    if company_hit:
        result.positive_signals.append(f"{view.value_for('company')} is on the preferred list")

    is_remote = bool(view.value_for("remote"))
    remote_ratio = 1.0 if (is_remote and getattr(preferences, "remote_ok", True)) else 0.4
    result.breakdown["remote_fit"] = remote_ratio * weight_of("remote_fit")

    if rule_eval.bonus:
        result.breakdown["custom_rules"] = rule_eval.bonus

    deterministic = sum(result.breakdown.values())
    result.deterministic_score = max(0.0, min(100.0, deterministic))

    # --- 4. semantic blend (opt-in) ---------------------------------------
    result.semantic_score = semantic_score
    if semantic_score is not None and getattr(preferences, "semantic_scoring_enabled", False):
        blend = float(getattr(preferences, "semantic_weight", 0.2) or 0.0)
        blend = max(0.0, min(1.0, blend))
        result.score = result.deterministic_score * (1 - blend) + semantic_score * blend
    else:
        result.score = result.deterministic_score

    result.score = round(max(0.0, min(100.0, result.score)), 2)

    # --- 5. decision --------------------------------------------------------
    review_threshold = float(getattr(preferences, "review_threshold", 70) or 70)
    high_threshold = float(getattr(preferences, "high_priority_threshold", 85) or 85)

    if result.hard_fail_reasons:
        result.decision = "REJECT"
    elif result.score >= high_threshold:
        result.decision = "HIGH_PRIORITY"
    elif result.score >= review_threshold:
        result.decision = "REVIEW"
    else:
        result.decision = "REJECT"

    # De-duplicate while preserving order.
    result.matched_skills = list(dict.fromkeys(result.matched_skills))
    result.missing_skills = list(dict.fromkeys(result.missing_skills))
    result.positive_signals = list(dict.fromkeys(result.positive_signals))

    if resumes:
        resume_id, reason = recommend_resume(job, resumes, result)
        result.recommended_resume_id = resume_id
        result.recommendation_reason = reason

    result.explanation = build_explanation(job, result)
    return result


def build_explanation(job: Any, result: MatchResult) -> str:
    """Plain-language summary. This is what the user actually reads."""
    view = JobView(job)
    title = view.value_for("title") or "This role"
    company = view.value_for("company") or "the company"

    if result.hard_fail_reasons:
        reasons = "; ".join(result.hard_fail_reasons[:3])
        return f"Rejected: {reasons}."

    parts = [f"{title} at {company} scored {result.score:.0f}/100 ({result.decision})."]
    if result.matched_skills:
        parts.append(f"Matched skills: {', '.join(result.matched_skills[:6])}.")
    if result.positive_signals:
        parts.append(" ".join(f"{s}." for s in result.positive_signals[:3]))
    if result.missing_skills:
        parts.append(f"Not evidenced in the posting: {', '.join(result.missing_skills[:5])}.")

    top_factors = sorted(result.breakdown.items(), key=lambda kv: kv[1], reverse=True)[:3]
    if top_factors:
        rendered = ", ".join(f"{k.replace('_', ' ')} {v:.0f}" for k, v in top_factors if v > 0)
        if rendered:
            parts.append(f"Biggest contributors: {rendered}.")

    return " ".join(parts)


def recommend_resume(
    job: Any, resumes: list[Any], result: MatchResult | None = None
) -> tuple[str | None, str]:
    """Pick the resume whose declared focus best overlaps this job.

    Deterministic on purpose: the AI resume-advice endpoint is a separate,
    optional second opinion, not the thing that picks the file.
    """
    if not resumes:
        return (None, "")

    view = JobView(job)
    haystack = view.searchable_text()
    title_tokens = tokens(view.value_for("title"))

    best: tuple[float, Any, list[str]] = (-1.0, None, [])
    for resume in resumes:
        if getattr(resume, "is_active", True) is False:
            continue
        reasons: list[str] = []
        score = 0.0

        for role in getattr(resume, "role_focus", None) or []:
            role_tokens = tokens(role) - _STOPWORD_ROLE_TOKENS
            if role_tokens and role_tokens & title_tokens:
                score += 3.0
                reasons.append(f"targets {role}")
                break

        skill_hits = [
            s for s in (getattr(resume, "skill_focus", None) or []) if _keyword_present(s, haystack)
        ]
        if skill_hits:
            score += min(4.0, len(skill_hits))
            reasons.append(f"covers {', '.join(skill_hits[:3])}")

        industry_hits = [
            i
            for i in (getattr(resume, "industry_focus", None) or [])
            if _keyword_present(i, haystack)
        ]
        if industry_hits:
            score += 1.5
            reasons.append(f"industry fit ({industry_hits[0]})")

        if getattr(resume, "is_default", False):
            score += 0.5

        if score > best[0]:
            best = (score, resume, reasons)

    _, chosen, reasons = best
    if chosen is None:
        return (None, "")

    if reasons:
        reason = f"{getattr(chosen, 'name', 'Resume')} {', and '.join(reasons)}."
    else:
        reason = f"{getattr(chosen, 'name', 'Resume')} is the default resume; no stronger match."
    return (str(getattr(chosen, "id", "")) or None, reason)

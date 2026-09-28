"""The per-job hunt assessment. Pure: no database, no network.

Order of evaluation:

1. Signals -- work mode, remote region, seniority, experience, freshness.
2. Location tier -- the first tier (in the user's priority order) the job fits.
3. Role, skill, semantic and apply-link fit.
4. Hard "not a match" reasons: intern/junior roles, under-levelled experience,
   a different job family, a location outside every tier, a stale posting,
   and (optionally) the policy's excluded companies/keywords and salary floor.
5. A 0..100 hunt score from user-editable weights.
6. Category: ``apply_first`` when the tier is an apply-first tier *and* the
   job is a strong fit; ``review`` for weaker fits or review tiers;
   ``not_match`` otherwise. Every outcome carries human-readable reasons.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.services.hunt.defaults import effective_weights
from app.services.hunt.signals import (
    EXPERIENCE_RATIOS,
    RegionResult,
    assess_freshness,
    contains_place,
    detect_remote_region,
    detect_seniority,
    detect_work_mode,
    experience_fit,
    freshness_ratio,
    humanize_age,
    in_country,
)
from app.services.matching import _role_matches
from app.services.normalize import (
    APPLY_LINK_QUALITY,
    best_apply_link,
    norm_text,
    normalize_company,
)
from app.services.resume.parser import contains_term, extract_skills, normalize_skill_list

# Titles this generic say nothing about the stack, so they only count as the
# right job family when the description's skills line up.
_GENERIC_TITLE_TERMS = (
    "software engineer", "software developer", "sde", "developer", "programmer",
    "engineer", "application developer", "product engineer",
)

SECTION_LABELS = {"apply_first": "Apply First", "review": "Worth Reviewing"}


@dataclass(slots=True)
class Assessment:
    category: str = "not_match"
    section: str = "Not a Match"
    tier_name: str = ""
    tier_group: str = ""
    tier_rank: int | None = None
    tier_kind: str = ""
    score: float = 0.0
    strength: str = "weak"
    work_mode: str = "unknown"
    remote_region: str = ""
    seniority: str = "mid"
    experience_fit: str = "unknown"
    skill_overlap: float | None = None
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    semantic_score: float | None = None
    freshness_at: datetime | None = None
    freshness_basis: str = "unknown"
    freshness_hours: float | None = None
    apply_link_type: str = "none"
    apply_link_label: str = ""
    best_apply_url: str = ""
    public_contact_email: str = ""
    reasons: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    breakdown: dict[str, float] = field(default_factory=dict)
    explanation: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "section": self.section,
            "tier_name": self.tier_name,
            "tier_group": self.tier_group,
            "tier_rank": self.tier_rank,
            "tier_kind": self.tier_kind,
            "score": round(self.score, 1),
            "strength": self.strength,
            "work_mode": self.work_mode,
            "remote_region": self.remote_region,
            "seniority": self.seniority,
            "experience_fit": self.experience_fit,
            "skill_overlap": None if self.skill_overlap is None else round(self.skill_overlap, 3),
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "semantic_score": self.semantic_score,
            "freshness_at": self.freshness_at.isoformat() if self.freshness_at else None,
            "freshness_basis": self.freshness_basis,
            "freshness_hours": None if self.freshness_hours is None else round(self.freshness_hours, 1),
            "apply_link_type": self.apply_link_type,
            "apply_link_label": self.apply_link_label,
            "best_apply_url": self.best_apply_url,
            "public_contact_email": self.public_contact_email,
            "reasons": self.reasons,
            "highlights": self.highlights,
            "warnings": self.warnings,
            "breakdown": {k: round(v, 2) for k, v in self.breakdown.items()},
            "explanation": self.explanation,
        }


def _get(job: Any, name: str, default: Any = None) -> Any:
    if isinstance(job, dict):
        value = job.get(name, default)
    else:
        value = getattr(job, name, default)
    return default if value is None else value


# ---------------------------------------------------------------------------
# Location tiers
# ---------------------------------------------------------------------------
def match_tier(
    tiers: list[dict[str, Any]],
    *,
    work_mode: str,
    location: str,
    region: RegionResult,
    country: str,
    country_places: list[str],
    accept_worldwide_remote: bool,
) -> tuple[int | None, dict[str, Any] | None, list[str]]:
    """First tier (in priority order) the job fits: ``(rank, tier, warnings)``."""
    location_norm = norm_text(location)
    job_in_country = in_country(location, country, country_places)
    # A posting that names a city but not a mode is an office job.
    mode = work_mode if work_mode != "unknown" else ("onsite" if location_norm else "unknown")

    for rank, tier in enumerate(tiers):
        modes = tier.get("work_modes") or ["remote", "hybrid", "onsite"]
        if mode not in modes:
            continue
        places = [str(p) for p in (tier.get("places") or []) if str(p).strip()]

        if mode == "remote":
            if not places:
                return (rank, tier, [])
            # Places on a remote tier say where the remote role must be open
            # to: the whole country, or specific cities ("Remote - Pune").
            country_listed = any(norm_text(p) == norm_text(country) for p in places)
            if region.kind == "country" and (
                country_listed or any(contains_place(p, location_norm) for p in places)
            ):
                return (rank, tier, [])
            if region.kind == "worldwide" and accept_worldwide_remote and country_listed:
                return (rank, tier, [f"{region.label or 'Worldwide'} remote: confirm hiring from {country}"])
            if region.kind == "unknown" and country_listed:
                return (rank, tier, [f"Remote region not stated: confirm hiring from {country}"])
            continue

        # onsite / hybrid
        if not places:
            return (rank, tier, [])
        for place in places:
            if norm_text(place) == norm_text(country):
                if job_in_country:
                    return (rank, tier, [])
            elif contains_place(place, location_norm):
                return (rank, tier, [])
    return (None, None, [])


def section_label(kind: str, tier: dict[str, Any]) -> str:
    group = str(tier.get("group") or tier.get("name") or "").strip()
    return f"{SECTION_LABELS.get(kind, 'Worth Reviewing')} — {group}" if group else SECTION_LABELS[kind]


# ---------------------------------------------------------------------------
# Role and skills
# ---------------------------------------------------------------------------
def role_fit(
    title: str,
    target_roles: list[str],
    role_keywords: list[str],
    skill_overlap: float | None,
) -> tuple[float, str]:
    hit, matched_role = _role_matches(title, target_roles)
    if hit:
        return (1.0, f"Title matches {matched_role}")
    title_norm = norm_text(title)
    for keyword in role_keywords or []:
        if contains_term(keyword, title_norm, normalized=True):
            return (0.8, f"Related title ({keyword})")
    if any(contains_term(t, title_norm, normalized=True) for t in _GENERIC_TITLE_TERMS):
        if skill_overlap is not None and skill_overlap >= 0.5:
            return (0.6, "Generic title, but the stack matches yours")
        return (0.25, "")
    return (0.0, "")


def skill_match(
    candidate_skills: list[str],
    title: str,
    description: str,
) -> tuple[float | None, list[str], list[str]]:
    """Coverage of the job's listed skills by the candidate's skills.

    Custom candidate skills outside the vocabulary still count when the job
    text names them, so a niche skill is not silently ignored.
    """
    text = f"{title}\n{description}"
    job_skills = extract_skills(text)
    candidate = normalize_skill_list(candidate_skills)
    candidate_keys = {s.lower() for s in candidate}
    text_norm = norm_text(text)

    for skill in candidate:
        if skill not in job_skills and contains_term(skill, text_norm, normalized=True):
            job_skills.append(skill)

    if not job_skills:
        return (None, [], [])
    matched = [s for s in job_skills if s.lower() in candidate_keys]
    missing = [s for s in job_skills if s.lower() not in candidate_keys]
    return (len(matched) / len(job_skills), matched, missing)


# ---------------------------------------------------------------------------
# Policy filters shared with the main matching engine
# ---------------------------------------------------------------------------
def policy_reasons(job: Any, policy: Any) -> list[str]:
    if policy is None:
        return []
    reasons: list[str] = []
    company = normalize_company(_get(job, "company", ""))
    for blocked in getattr(policy, "excluded_companies", None) or []:
        if company and normalize_company(blocked) == company:
            reasons.append(f"{_get(job, 'company', '')} is on your excluded companies list")
    text_norm = norm_text(f"{_get(job, 'title', '')}\n{_get(job, 'description', '')}")
    for keyword in getattr(policy, "excluded_keywords", None) or []:
        if str(keyword).strip() and contains_term(str(keyword), text_norm, normalized=True):
            reasons.append(f"Mentions excluded keyword: {keyword}")
    floor = getattr(policy, "min_salary_lpa", None)
    top = _get(job, "salary_max_lpa") or _get(job, "salary_min_lpa")
    currency = str(_get(job, "currency", "INR") or "INR").upper()
    if floor and top is not None and currency == "INR" and float(top) < float(floor):
        reasons.append(f"Pays up to {top:g} LPA, below your {floor:g} LPA minimum")
    return reasons


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def strength_for(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 65:
        return "good"
    if score >= 50:
        return "partial"
    return "weak"


def assess_job(
    job: Any,
    config: Any,
    *,
    policy: Any = None,
    semantic_score: float | None = None,
    now: datetime | None = None,
) -> Assessment:
    """Assess one job against the hunt configuration."""
    result = Assessment()
    title = str(_get(job, "title", "") or "")
    description = str(_get(job, "description", "") or "")
    location = str(_get(job, "location", "") or "")
    country = str(getattr(config, "country", "") or "India")
    country_places = list(getattr(config, "country_places", None) or [])
    candidate_years = getattr(config, "experience_years", None)

    # --- 1. signals -------------------------------------------------------
    result.work_mode = detect_work_mode(location, title, description, bool(_get(job, "is_remote", False)))
    region = RegionResult("", "")
    if result.work_mode == "remote":
        region = detect_remote_region(
            location, description, country=country, country_places=country_places
        )
        result.remote_region = region.as_text()
    result.seniority = detect_seniority(title)

    fit, fit_reason = experience_fit(
        candidate_years,
        _get(job, "experience_min_years"),
        _get(job, "experience_max_years"),
        result.seniority,
    )
    result.experience_fit = fit

    fresh = assess_freshness(
        _get(job, "posted_at"), _get(job, "source_updated_at"), _get(job, "first_seen_at"), now=now
    )
    result.freshness_at = fresh.at
    result.freshness_basis = fresh.basis
    result.freshness_hours = fresh.age_hours
    if fresh.warning:
        result.warnings.append(fresh.warning)

    # --- 2. location tier ---------------------------------------------------
    tiers = [t for t in (getattr(config, "location_tiers", None) or []) if isinstance(t, dict)]
    rank, tier, tier_warnings = match_tier(
        tiers,
        work_mode=result.work_mode,
        location=location,
        region=region,
        country=country,
        country_places=country_places,
        accept_worldwide_remote=bool(getattr(config, "accept_worldwide_remote", True)),
    )
    result.warnings.extend(tier_warnings)
    region_uncertain = bool(tier_warnings)
    if tier is not None:
        result.tier_rank = rank
        result.tier_name = str(tier.get("name") or "")
        result.tier_group = str(tier.get("group") or result.tier_name)
        result.tier_kind = str(tier.get("kind") or "apply_first")
        result.highlights.append(f"{result.tier_name} ({result.work_mode})")

    # --- 3. role, skills, semantic, apply link ---------------------------
    overlap, matched, missing = skill_match(
        list(getattr(config, "skills", None) or []), title, description
    )
    result.skill_overlap = overlap
    result.matched_skills = matched
    result.missing_skills = missing
    role_ratio, role_reason = role_fit(
        title,
        list(getattr(config, "target_roles", None) or []),
        list(getattr(config, "role_keywords", None) or []),
        overlap,
    )
    if role_reason:
        result.highlights.append(role_reason)

    result.semantic_score = semantic_score

    best_url, link_type, link_label = best_apply_link(_get(job, "apply_url", ""), _get(job, "url", ""))
    email = str(_get(job, "application_email", "") or "").strip()
    result.public_contact_email = email
    if link_type in ("none", "aggregator") and email:
        # A published application address beats an aggregator copy.
        link_quality_type = "email"
    else:
        link_quality_type = link_type
    result.best_apply_url = best_url
    result.apply_link_type = link_type if best_url else ("email" if email else "none")
    result.apply_link_label = link_label if best_url else ("Email" if email else "")
    if link_type == "ats":
        result.highlights.append(f"Direct application via {link_label}")

    # --- 4. hard "not a match" reasons -----------------------------------
    excluded_seniority = {str(s).lower() for s in (getattr(config, "excluded_seniority", None) or [])}
    seniority_excluded = result.seniority in excluded_seniority
    if seniority_excluded:
        result.reasons.append(f"{result.seniority.title()}-level role")
    if fit == "under":
        stated = _get(job, "experience_min_years") is not None or _get(job, "experience_max_years") is not None
        # A title-only "under" verdict repeats the seniority reason; skip it.
        if stated or not seniority_excluded:
            result.reasons.append(fit_reason or "Pitched well below your experience")
    elif fit_reason:
        (result.highlights if fit in ("strong", "good") else result.warnings).append(fit_reason)
    if role_ratio <= 0.25:
        result.reasons.append(f"Different job family: {title}")
    if tier is None:
        if result.work_mode == "remote" and region.kind == "foreign":
            result.reasons.append(f"Remote, but only for {region.label}")
        elif location:
            result.reasons.append(f"{location} is outside your location priorities")
        else:
            result.reasons.append("Location not stated")
    max_age = int(getattr(config, "max_age_days", 0) or 0)
    if max_age > 0 and fresh.age_hours is not None and fresh.age_hours > max_age * 24:
        result.reasons.append(
            f"Posted {humanize_age(fresh.age_hours)} ago, older than your {max_age}-day window"
        )
    if getattr(config, "respect_policy_filters", True):
        result.reasons.extend(policy_reasons(job, policy))

    # --- 5. score ---------------------------------------------------------
    weights = effective_weights(config)
    location_ratio = 0.0
    if rank is not None:
        location_ratio = max(0.5, 1.0 - 0.1 * rank) * (0.7 if region_uncertain else 1.0)
    ratios = {
        "location": location_ratio,
        "role": role_ratio,
        "skills": 0.5 if overlap is None else overlap,
        "experience": EXPERIENCE_RATIOS.get(fit, 0.6),
        "freshness": freshness_ratio(fresh.age_hours),
        "semantic": 0.5 if semantic_score is None else float(semantic_score),
        "apply_link": APPLY_LINK_QUALITY.get(link_quality_type, 0.2),
    }
    if getattr(config, "semantic_mode", "local") == "off":
        weights["semantic"] = 0.0
    total_weight = sum(weights.values()) or 1.0
    result.breakdown = {k: ratios[k] * weights[k] * 100.0 / total_weight for k in ratios}
    result.score = round(max(0.0, min(100.0, sum(result.breakdown.values()))), 1)
    result.strength = strength_for(result.score)

    # --- 6. category ------------------------------------------------------
    if result.reasons or tier is None:
        result.category = "not_match"
        result.section = "Not a Match"
        result.strength = "none"
    else:
        min_overlap = float(getattr(config, "min_skill_overlap", 0.4) or 0.0)
        threshold = float(getattr(config, "apply_first_threshold", 65) or 0)
        strong_fit = (
            result.score >= threshold
            and (overlap is None or overlap >= min_overlap)
            and fit in ("strong", "good", "unknown")
            and role_ratio >= 0.6
            and not region_uncertain
        )
        result.category = "apply_first" if (result.tier_kind == "apply_first" and strong_fit) else "review"
        result.section = section_label(result.category, tier)
        if result.tier_kind == "apply_first" and not strong_fit:
            result.warnings.append(_demotion_reason(result, overlap, min_overlap, threshold, role_ratio, region_uncertain))

    result.highlights = list(dict.fromkeys(h for h in result.highlights if h))
    result.warnings = list(dict.fromkeys(w for w in result.warnings if w))
    result.explanation = build_explanation(title, _get(job, "company", ""), result)
    return result


def _demotion_reason(
    result: Assessment,
    overlap: float | None,
    min_overlap: float,
    threshold: float,
    role_ratio: float,
    region_uncertain: bool,
) -> str:
    if region_uncertain:
        return "Moved to review until the remote region is confirmed"
    if overlap is not None and overlap < min_overlap:
        return f"Moved to review: covers {overlap:.0%} of the listed skills (minimum {min_overlap:.0%})"
    if result.experience_fit == "stretch":
        return "Moved to review: asks for noticeably more experience"
    if role_ratio < 0.6:
        return "Moved to review: title is only loosely related"
    return f"Moved to review: score {result.score:.0f} is below your {threshold:.0f} apply-first bar"


def build_explanation(title: str, company: str, a: Assessment) -> str:
    who = f"{title} at {company}" if company else title
    if a.category == "not_match":
        return f"Not a match: {'; '.join(a.reasons[:3]) or 'outside your priorities'}."
    # Round half up, matching how the UI rounds the same number.
    parts = [f"{who} is in {a.section} ({a.strength}, {int(a.score + 0.5)}/100)."]
    if a.highlights:
        parts.append(" ".join(f"{h}." for h in a.highlights[:4]))
    if a.matched_skills:
        covered = f"Covers {len(a.matched_skills)} of {len(a.matched_skills) + len(a.missing_skills)} listed skills"
        if a.missing_skills:
            covered += f" (missing {', '.join(a.missing_skills[:4])})"
        parts.append(covered + ".")
    if a.freshness_hours is not None:
        parts.append(f"{'Posted' if a.freshness_basis == 'posted' else 'Seen'} {humanize_age(a.freshness_hours)} ago.")
    return " ".join(parts)


__all__ = [
    "Assessment",
    "SECTION_LABELS",
    "assess_job",
    "build_explanation",
    "match_tier",
    "policy_reasons",
    "role_fit",
    "section_label",
    "skill_match",
    "strength_for",
]

"""Deterministic signals read off a posting: work mode, region, seniority, age.

All functions are pure and work on plain strings so they are easy to test and
cheap enough to run over every job on every hunt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.services.normalize import norm_text


def _rx(*alternatives: str) -> re.Pattern[str]:
    body = "|".join(alternatives)
    return re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z0-9])")


# Patterns run on norm_text() output: lowercase, punctuation collapsed to
# spaces except "." "+" "#".
_HYBRID = _rx(
    r"hybrid",
    r"\d\s*days?\s*(?:a|per)?\s*week\s*(?:in|at|from)\s*(?:the\s*)?office",
    r"\d\s*days?\s*(?:in|at|from)\s*(?:the\s*)?office",
    r"work from office\s*\d",
    r"partially remote",
    r"flexible hybrid",
)
_REMOTE = _rx(
    r"remote",
    r"work from home",
    r"wfh",
    r"work from anywhere",
    r"fully distributed",
    r"telecommute",
    r"home based",
)
# Stronger phrasing required before description text alone makes a job remote.
_REMOTE_STRONG = _rx(
    r"fully remote",
    r"100\s*%?\s*remote",
    r"remote first",
    r"remote only",
    r"this is a remote (?:role|position|job)",
    r"remote (?:role|position|opportunity) (?:in|within|across) india",
    r"work from home",
    r"work from anywhere",
)
_ONSITE = _rx(r"on\s?site", r"in\s?office", r"work from office", r"wfo", r"office based")

_WORLDWIDE = _rx(r"worldwide", r"anywhere", r"global(?:ly)?", r"any location", r"international")

# Regions a remote role may be restricted to. The bare token "us" is only
# trusted in a location field; in running text it is the pronoun.
_FOREIGN_REGIONS: dict[str, re.Pattern[str]] = {
    "US": _rx(r"usa", r"u\.s\.a?\.?", r"united states", r"us only", r"us based", r"north america",
              r"americas", r"est timezone", r"pst timezone"),
    "Canada": _rx(r"canada", r"canadian"),
    "UK": _rx(r"united kingdom", r"uk only", r"uk based", r"england", r"london"),
    "Europe": _rx(r"europe", r"european union", r"eu only", r"emea", r"germany", r"netherlands",
                  r"spain", r"poland", r"portugal", r"france", r"cet timezone"),
    "LATAM": _rx(r"latam", r"latin america", r"brazil", r"mexico", r"argentina", r"colombia"),
    "Australia": _rx(r"australia", r"new zealand", r"anz"),
}
_LOCATION_ONLY_REGIONS: dict[str, re.Pattern[str]] = {
    "US": _rx(r"us", r"america"),
    "UK": _rx(r"uk", r"gb"),
    "Europe": _rx(r"eu"),
}
_APAC = _rx(r"apac", r"asia pacific", r"asia")


def contains_place(place: str, text_norm: str) -> bool:
    needle = norm_text(place)
    if not needle:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text_norm))


def in_country(location: str, country: str, country_places: list[str]) -> bool:
    """True when a location string names the country or one of its places."""
    loc = norm_text(location)
    if not loc:
        return False
    if contains_place(country, loc):
        return True
    return any(contains_place(p, loc) for p in country_places or [])


# ---------------------------------------------------------------------------
# Work mode
# ---------------------------------------------------------------------------
def detect_work_mode(
    location: str | None,
    title: str | None,
    description: str | None,
    is_remote: bool = False,
) -> str:
    """Classify a posting as ``remote``, ``hybrid``, ``onsite`` or ``unknown``.

    The location and title are authoritative; the description is only
    consulted when they are silent, and then only for unambiguous phrasing,
    because "remote" appears in plenty of onsite postings ("remote teams").
    """
    head = norm_text(f"{location or ''} {title or ''}")
    if _HYBRID.search(head):
        return "hybrid"
    if _REMOTE.search(head):
        return "remote"
    if _ONSITE.search(head):
        return "onsite"

    body = norm_text((description or "")[:4000])
    if _HYBRID.search(body):
        return "hybrid"
    if _REMOTE_STRONG.search(body):
        return "remote"
    if is_remote:
        return "remote"
    if _ONSITE.search(body):
        return "onsite"
    if norm_text(location):
        return "onsite"
    return "unknown"


# ---------------------------------------------------------------------------
# Remote region
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class RegionResult:
    # country | worldwide | foreign | unknown
    kind: str
    label: str = ""

    def as_text(self) -> str:
        return self.label or self.kind


def detect_remote_region(
    location: str | None,
    description: str | None,
    *,
    country: str,
    country_places: list[str],
) -> RegionResult:
    """Where a remote role may be done from.

    Distinguishes "Remote India" from "Remote US" and "Remote Worldwide",
    which a plain ``is_remote`` flag cannot.
    """
    loc = norm_text(location)
    if loc:
        if in_country(loc, country, country_places):
            return RegionResult("country", country)
        for label, pattern in _FOREIGN_REGIONS.items():
            if pattern.search(loc):
                return RegionResult("foreign", label)
        for label, pattern in _LOCATION_ONLY_REGIONS.items():
            if pattern.search(loc):
                return RegionResult("foreign", label)
        if _WORLDWIDE.search(loc):
            return RegionResult("worldwide", "Worldwide")
        if _APAC.search(loc):
            return RegionResult("worldwide", "APAC")

    body = norm_text((description or "")[:6000])
    if body:
        country_hit = contains_place(country, body) or any(
            contains_place(p, body) for p in (country_places or [])[:25]
        )
        foreign = next((label for label, p in _FOREIGN_REGIONS.items() if p.search(body)), None)
        if country_hit and not foreign:
            return RegionResult("country", country)
        if foreign and not country_hit:
            return RegionResult("foreign", foreign)
        if _WORLDWIDE.search(body) and not foreign:
            return RegionResult("worldwide", "Worldwide")
        if country_hit and foreign:
            # Both mentioned (e.g. "teams in the US and India"): lean on the
            # country but let the caller warn.
            return RegionResult("country", f"{country} (also mentions {foreign})")
    return RegionResult("unknown", "")


# ---------------------------------------------------------------------------
# Seniority
# ---------------------------------------------------------------------------
_SENIORITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("intern", _rx(r"intern", r"internship", r"trainee", r"apprentice", r"apprenticeship")),
    ("lead", _rx(r"lead", r"principal", r"staff", r"architect", r"head", r"manager", r"director",
                 r"vp", r"chief")),
    ("senior", _rx(r"senior", r"sr\.?", r"sde\s?(?:2|3|ii|iii)", r"engineer\s?(?:2|3|ii|iii)",
                   r"experienced")),
    ("junior", _rx(r"junior", r"jr\.?", r"entry level", r"fresher", r"freshers", r"graduate",
                   r"new grad", r"associate", r"sde\s?(?:1|i)", r"engineer\s?(?:1|i)")),
]


def detect_seniority(title: str | None) -> str:
    """Seniority from the title: intern, junior, mid, senior or lead.

    Checked most-senior first, so "Senior Associate" reads as senior and
    "Associate Engineer" as junior.
    """
    text = norm_text(title)
    if not text:
        return "mid"
    for level, pattern in _SENIORITY_PATTERNS:
        if pattern.search(text):
            return level
    return "mid"


# ---------------------------------------------------------------------------
# Experience fit
# ---------------------------------------------------------------------------
EXPERIENCE_RATIOS = {
    "strong": 1.0,
    "good": 0.8,
    "unknown": 0.6,
    "stretch": 0.4,
    "under": 0.0,
}


def experience_fit(
    candidate_years: float | None,
    job_min: float | None,
    job_max: float | None,
    seniority: str = "mid",
) -> tuple[str, str]:
    """Return ``(fit, reason)``.

    ``strong``  the candidate sits inside the asked range (5-8 for 5.5 yrs)
    ``good``    close to it (a 3-5 range, or a 6+ ask)
    ``stretch`` the ask is well above the candidate (8+ for 5.5 yrs)
    ``under``   the role is pitched far below the candidate (1-2 yrs)
    ``unknown`` the posting does not say and the title does not imply it
    """
    if candidate_years is None:
        return ("unknown", "")
    x = float(candidate_years)

    if job_min is None and job_max is None:
        if seniority in ("intern", "junior"):
            return ("under", f"{seniority.title()}-level title for a {x:g}-year candidate")
        if seniority in ("senior", "lead"):
            return ("good", f"{seniority.title()}-level title; no years stated")
        return ("unknown", "Experience not stated")

    lo = job_min
    hi = job_max
    rendered = (
        f"{lo:g}-{hi:g} yrs" if lo is not None and hi is not None
        else f"{lo:g}+ yrs" if lo is not None
        else f"up to {hi:g} yrs"
    )

    if hi is not None and hi < x - 2:
        return ("under", f"Asks for {rendered}; you have {x:g}")
    if lo is not None and lo > x + 1.5:
        return ("stretch", f"Asks for {rendered}; you have {x:g}")
    if (lo is None or lo <= x) and (hi is None or x <= hi):
        return ("strong", f"{rendered} fits your {x:g} yrs")
    return ("good", f"{rendered} is close to your {x:g} yrs")


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------
def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(slots=True)
class Freshness:
    at: datetime | None
    # posted | updated | first_seen | unknown
    basis: str
    age_hours: float | None
    warning: str = ""


def assess_freshness(
    posted_at: datetime | None,
    source_updated_at: datetime | None,
    first_seen_at: datetime | None,
    *,
    now: datetime | None = None,
) -> Freshness:
    """Pick the most trustworthy age signal and flag misleading ones.

    The original posting date wins. A recent *update* to an old posting is
    reported, not mistaken for a new job. With no posting date, the provider's
    update time and then our own first sighting are used, each with a warning.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    posted = _aware(posted_at)
    updated = _aware(source_updated_at)
    seen = _aware(first_seen_at)

    def hours(value: datetime) -> float:
        return max(0.0, (now - value).total_seconds() / 3600.0)

    if posted is not None:
        warning = ""
        if updated is not None and (updated - posted).total_seconds() > 36 * 3600:
            warning = (
                f"Updated {_humanize(hours(updated))} ago, but originally posted "
                f"{_humanize(hours(posted))} ago"
            )
        return Freshness(posted, "posted", hours(posted), warning)
    # No warning for these two: the basis is shown in the label itself
    # ("Updated 3h ago" / "Found 1h ago"), so repeating it is noise.
    if updated is not None:
        return Freshness(updated, "updated", hours(updated))
    if seen is not None:
        return Freshness(seen, "first_seen", hours(seen))
    return Freshness(None, "unknown", None, "Posting date unknown")


def freshness_ratio(age_hours: float | None) -> float:
    if age_hours is None:
        return 0.4
    if age_hours <= 24:
        return 1.0
    if age_hours <= 72:
        return 0.85
    if age_hours <= 7 * 24:
        return 0.7
    if age_hours <= 14 * 24:
        return 0.5
    if age_hours <= 30 * 24:
        return 0.3
    return 0.1


def _humanize(age_hours: float) -> str:
    if age_hours < 1:
        return "under an hour"
    if age_hours < 48:
        return f"{int(round(age_hours))}h"
    return f"{int(round(age_hours / 24))} days"


def humanize_age(age_hours: float | None) -> str:
    return "unknown" if age_hours is None else _humanize(age_hours)


__all__ = [
    "EXPERIENCE_RATIOS",
    "Freshness",
    "RegionResult",
    "assess_freshness",
    "contains_place",
    "detect_remote_region",
    "detect_seniority",
    "detect_work_mode",
    "experience_fit",
    "freshness_ratio",
    "humanize_age",
    "in_country",
]

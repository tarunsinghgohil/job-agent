"""Type-ahead suggestions for locations, roles, skills, companies and more.

Two candidate pools per kind:

* a static vocabulary, indexed once per process (``_static_index``), and
* the user's own data (profile, preferences, hunt setup, relevant jobs),
  cached per user for a short TTL so keystrokes do not hit the database.

Ranking is deterministic and cheap: exact > label prefix > every query word
prefixing a label word > alias prefix > substring > typo-tolerant match.
Personal entries get a boost so the user's own roles and skills float up.
"""
from __future__ import annotations

import difflib
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services import suggest_data as data

KINDS = (
    "location", "role", "skill", "title_word", "company", "industry",
    "employment_type", "company_type", "keyword", "query",
)

USER_CACHE_TTL_SECONDS = 60
MAX_USER_CANDIDATES = 400


def _norm(text: str | None) -> str:
    """Lowercase, strip accents, fold punctuation (keeps . + # /) to spaces."""
    if not text:
        return ""
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", str(text)) if not unicodedata.combining(c)
    ).lower()
    out = []
    for ch in folded:
        out.append(ch if ch.isalnum() or ch in ".+#/" else " ")
    return " ".join("".join(out).split())


@dataclass(slots=True)
class Entry:
    value: str
    label: str
    hint: str = ""
    aliases: tuple[str, ...] = ()
    weight: float = 0.0  # popularity, 0..50
    source: str = "catalog"  # catalog | yours
    # Precomputed normalized forms.
    n_label: str = ""
    n_words: tuple[str, ...] = ()
    n_aliases: tuple[str, ...] = ()

    def prepare(self) -> "Entry":
        self.n_label = _norm(self.label)
        self.n_words = tuple(self.n_label.split())
        self.n_aliases = tuple(a for a in (_norm(x) for x in self.aliases) if a)
        return self


@dataclass(slots=True)
class Match:
    entry: Entry
    score: float
    exact: bool = False
    via_alias: str = ""


def _popularity(index: int, total: int) -> float:
    return 50.0 * (1.0 - index / max(1, total))


def _build(entries: list[Entry]) -> list[Entry]:
    total = len(entries)
    for i, entry in enumerate(entries):
        if not entry.weight:
            entry.weight = _popularity(i, total)
        entry.prepare()
    return entries


@lru_cache(maxsize=None)
def _static_index(kind: str) -> tuple[Entry, ...]:
    """Built once per process; entries are never mutated afterwards."""
    from app.services.resume.parser import SKILL_GROUPS, SKILL_VOCABULARY

    entries: list[Entry] = []
    if kind == "location":
        for label, hint, aliases in data.LOCATION_MODES:
            entries.append(Entry(label, label, hint, aliases))
        entries.append(Entry("India", "India", "Country", ("IN", "Bharat")))
        for city, state, aliases in data.INDIAN_CITIES:
            entries.append(Entry(city, city, f"City · {state}", aliases))
        for state in data.INDIAN_STATES:
            entries.append(Entry(state, state, "State · India"))
        for country, aliases in data.COUNTRIES:
            if country != "India":
                entries.append(Entry(country, country, "Country", aliases))
    elif kind == "role":
        for role in data.BASE_ROLES:
            entries.append(Entry(role, role, "Role"))
        for prefix in data.SENIORITY_PREFIXES:
            for role in data.BASE_ROLES:
                if role.startswith(("Technical Lead", "Engineering Manager", "Scrum")):
                    continue
                label = f"{prefix} {role}"
                entries.append(Entry(label, label, "Role"))
    elif kind == "skill":
        for canonical, aliases in SKILL_VOCABULARY.items():
            extra = tuple(a for a in aliases if _norm(a) != _norm(canonical))
            entries.append(Entry(canonical, canonical, "Skill", extra))
        for shorthand, members in SKILL_GROUPS.items():
            if " " in shorthand:
                continue
            entries.append(
                Entry(
                    shorthand.upper(), shorthand.upper(),
                    f"Stack · {', '.join(members)}",
                    (f"{shorthand} stack",),
                )
            )
        known = {_norm(e.label) for e in entries}
        for skill in data.EXTRA_SKILLS:
            if _norm(skill) not in known:
                entries.append(Entry(skill, skill, "Skill"))
    elif kind == "title_word":
        for word in data.TITLE_WORDS:
            entries.append(Entry(word, word, "Title word"))
    elif kind == "company":
        for company in data.COMPANIES:
            entries.append(Entry(company, company, "Company"))
    elif kind == "industry":
        for industry in data.INDUSTRIES:
            entries.append(Entry(industry.lower(), industry, "Industry"))
    elif kind == "employment_type":
        for value, label, aliases in data.EMPLOYMENT_TYPES:
            entries.append(Entry(value, label, value, aliases))
    elif kind == "company_type":
        for value, aliases in data.COMPANY_TYPES:
            entries.append(Entry(value, "MNC" if value == "mnc" else value.replace("_", "-").title(), "Company type", aliases))
    elif kind == "keyword":
        # Keywords are matched against posting text, so skills and title words
        # are the useful vocabulary.
        seen: set[str] = set()
        for sub in ("skill", "title_word", "industry"):
            for e in _static_index(sub):
                key = _norm(e.label)
                if key in seen:
                    continue
                seen.add(key)
                entries.append(Entry(e.label, e.label, e.hint, e.aliases, e.weight))
    elif kind == "query":
        for e in _static_index("role"):
            entries.append(Entry(e.label, e.label, "Search", e.aliases, e.weight))
    return tuple(_build(entries))


# ---------------------------------------------------------------------------
# User-derived candidates
# ---------------------------------------------------------------------------
_user_cache: dict[tuple[str, str], tuple[float, list[Entry]]] = {}
_user_cache_lock = threading.Lock()


def _personal(values: list[tuple[str, str]]) -> list[Entry]:
    """``(label, hint)`` pairs -> entries, first occurrence wins."""
    out: list[Entry] = []
    seen: set[str] = set()
    for label, hint in values:
        label = " ".join(str(label or "").split())[:200]
        key = _norm(label)
        if not key or key in seen or len(key) < 2:
            continue
        seen.add(key)
        out.append(Entry(label, label, hint, (), 30.0, "yours").prepare())
        if len(out) >= MAX_USER_CANDIDATES:
            break
    return out


def _user_values(db: Session, user_id: str, kind: str) -> list[tuple[str, str]]:
    from app.db.models.hunt import HuntConfig, HuntResult
    from app.db.models.identity import CareerProfile, ProfileSkill, Skill
    from app.db.models.jobs import Job
    from app.db.models.preferences import JobPreference
    from app.db.models.resumes import Resume

    prefs = db.scalar(select(JobPreference).where(JobPreference.user_id == user_id))
    hunt = db.scalar(select(HuntConfig).where(HuntConfig.user_id == user_id))
    profile = db.scalar(select(CareerProfile).where(CareerProfile.user_id == user_id))
    values: list[tuple[str, str]] = []

    def relevant_jobs(column):
        """Distinct values from jobs the hunt did not rule out, most common first."""
        return db.execute(
            select(column, func.count())
            .join(HuntResult, HuntResult.job_id == Job.id)
            .where(
                Job.user_id == user_id,
                Job.deleted_at.is_(None),
                HuntResult.category != "not_match",
                column != "",
            )
            .group_by(column)
            .order_by(func.count().desc())
            .limit(150)
        ).all()

    if kind in ("role", "query"):
        for source, hint in (
            (hunt.target_roles if hunt else [], "Your hunt role"),
            (prefs.target_roles if prefs else [], "Your target role"),
            (profile.preferred_roles if profile else [], "Your profile"),
        ):
            values.extend((r, hint) for r in source or [])
        if profile is not None:
            values.extend((e.title, "Your experience") for e in profile.experiences)
        values.extend((t, "From your matched jobs") for t, _ in relevant_jobs(Job.title))
    elif kind in ("skill", "keyword"):
        for source, hint in (
            (hunt.skills if hunt else [], "Your skill"),
            (prefs.must_have_keywords if prefs else [], "Your must-have"),
            (prefs.nice_to_have_keywords if prefs else [], "Your nice-to-have"),
        ):
            values.extend((s, hint) for s in source or [])
        if profile is not None:
            rows = db.execute(
                select(Skill.name)
                .join(ProfileSkill, ProfileSkill.skill_id == Skill.id)
                .where(ProfileSkill.profile_id == profile.id)
            ).all()
            values.extend((name, "Your profile skill") for (name,) in rows)
        for resume in db.scalars(select(Resume).where(Resume.user_id == user_id, Resume.deleted_at.is_(None))):
            values.extend((s, "Resume focus") for s in resume.skill_focus or [])
    elif kind == "location":
        if hunt is not None:
            for tier in hunt.location_tiers or []:
                values.extend((p, "In your hunt priorities") for p in tier.get("places") or [])
        values.extend((loc, "Your preference") for loc in (prefs.preferred_locations if prefs else []) or [])
        if profile is not None and profile.location:
            values.append((profile.location, "Your profile"))
        values.extend((loc, "From your matched jobs") for loc, _ in relevant_jobs(Job.location))
    elif kind == "company":
        for source, hint in (
            (prefs.preferred_companies if prefs else [], "Preferred"),
            (prefs.excluded_companies if prefs else [], "Excluded"),
        ):
            values.extend((c, hint) for c in source or [])
        if profile is not None:
            values.extend((e.company, "Your experience") for e in profile.experiences)
        rows = db.execute(
            select(Job.company, func.count())
            .where(Job.user_id == user_id, Job.deleted_at.is_(None), Job.company != "")
            .group_by(Job.company)
            .order_by(func.count().desc())
            .limit(200)
        ).all()
        values.extend((c, "From your jobs") for c, _ in rows)
    elif kind == "industry":
        values.extend((i, "Your preference") for i in (prefs.industries if prefs else []) or [])
        values.extend((i, "Your profile") for i in (profile.preferred_industries if profile else []) or [])
    elif kind == "title_word":
        values.extend((w, "Your hunt") for w in (hunt.role_keywords if hunt else []) or [])
    if kind == "skill":
        # "React.js" typed into the hunt and "React" from the catalog are one
        # skill; canonicalize so the list does not show both.
        from app.services.resume.parser import normalize_skill_list

        values = [(name, hint) for label, hint in values for name in normalize_skill_list([label])]
    return values


def _user_entries(db: Session, user_id: str, kind: str) -> list[Entry]:
    key = (user_id, kind)
    now = time.monotonic()
    with _user_cache_lock:
        cached = _user_cache.get(key)
        if cached and now - cached[0] < USER_CACHE_TTL_SECONDS:
            return cached[1]
    entries = _personal(_user_values(db, user_id, kind))
    if kind == "query":
        entries.extend(_query_combos(db, user_id))
    with _user_cache_lock:
        _user_cache[key] = (now, entries)
        if len(_user_cache) > 2000:  # bounded; stale users simply rebuild
            _user_cache.clear()
    return entries


def _query_combos(db: Session, user_id: str) -> list[Entry]:
    """'<role> <tier location>' combinations for the hunt's custom queries."""
    from app.db.models.hunt import HuntConfig

    hunt = db.scalar(select(HuntConfig).where(HuntConfig.user_id == user_id))
    if hunt is None:
        return []
    suffixes: list[str] = []
    for tier in hunt.location_tiers or []:
        places = tier.get("places") or []
        if "remote" in (tier.get("work_modes") or []):
            suffixes.append(f"Remote {places[0]}".strip() if places else "Remote")
        elif places:
            suffixes.append(str(places[0]))
    pairs = [(f"{role} {suffix}", "Role + location") for role in (hunt.target_roles or [])[:15] for suffix in suffixes]
    return _personal(pairs)


def invalidate_user(user_id: str) -> None:
    with _user_cache_lock:
        for key in [k for k in _user_cache if k[0] == user_id]:
            _user_cache.pop(key, None)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
# Abbreviations people type in job-search boxes.
_ABBREVIATIONS: dict[str, str] = {
    "sr": "senior", "snr": "senior", "jr": "junior", "jnr": "junior",
    "fe": "frontend", "be": "backend", "fs": "full stack", "fullstack": "full stack",
    "mgr": "manager", "eng": "engineer", "dev": "developer", "js": "javascript",
    "ts": "typescript", "ml": "machine learning", "blr": "bengaluru", "hyd": "hyderabad",
    "ggn": "gurugram", "del": "delhi", "mum": "mumbai", "wfh": "remote",
}


def _expand(words: list[str]) -> list[str]:
    out: list[str] = []
    for word in words:
        out.extend(_ABBREVIATIONS.get(word, word).split())
    return out


def _word_hit(qw: str, words: tuple[str, ...] | list[str], fuzzy: bool) -> bool:
    for w in words:
        if w.startswith(qw):
            return True
        if fuzzy and len(qw) >= 4 and w[:1] == qw[:1]:
            if difflib.SequenceMatcher(None, qw, w[: len(qw) + 1]).ratio() >= 0.8:
                return True
    return False


def _score(entry: Entry, q: str, q_words: list[str]) -> Match | None:
    if not q:
        return Match(entry, entry.weight + (20 if entry.source == "yours" else 0))

    if entry.n_label == q:
        return Match(entry, 1000 + entry.weight, exact=True)
    for alias in entry.n_aliases:
        if alias == q:
            return Match(entry, 950 + entry.weight, exact=True, via_alias=alias)
    if entry.n_label.startswith(q):
        return Match(entry, 800 + entry.weight - len(entry.n_label) * 0.1)
    for alias in entry.n_aliases:
        # "bang" -> Bengaluru (via "Bangalore") should rank like a label prefix.
        if alias.startswith(q):
            return Match(entry, 790 + entry.weight - len(entry.n_label) * 0.1, via_alias=alias)
    if q_words and all(_word_hit(qw, entry.n_words, False) for qw in q_words):
        return Match(entry, 600 + entry.weight - len(entry.n_label) * 0.1)
    for alias in entry.n_aliases:
        alias_words = alias.split()
        if q_words and all(_word_hit(qw, alias_words, False) for qw in q_words):
            return Match(entry, 500 + entry.weight, via_alias=alias)
    if len(q) >= 3 and q in entry.n_label:
        return Match(entry, 300 + entry.weight)
    return None


def _fuzzy(entry: Entry, q_words: list[str]) -> Match | None:
    """Typo tolerance, word by word: every query word must prefix-match or be
    a near miss (same first letter, >= 80% similar) of some word."""
    if not q_words or not any(len(w) >= 4 for w in q_words):
        return None
    for candidate in (entry.n_label, *entry.n_aliases):
        words = candidate.split()
        if all(_word_hit(qw, words, True) for qw in q_words):
            via = candidate if candidate != entry.n_label else ""
            return Match(entry, 150 + entry.weight * 0.5, via_alias=via)
    return None


def suggest(
    db: Session,
    user_id: str,
    kind: str,
    q: str,
    *,
    limit: int = 8,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    """Ranked suggestions for ``q``. Returns ``{"items": [...], "kind", "q"}``."""
    if kind not in KINDS:
        raise ValueError(f"Unknown suggestion kind {kind!r}.")
    query = _norm(q)[:80]
    q_words = _expand(query.split())
    expanded = " ".join(q_words)
    excluded = {_norm(x) for x in (exclude or []) if x}

    personal = _user_entries(db, user_id, kind)
    catalog = _static_index(kind)

    matches: dict[str, Match] = {}

    def consider(entry: Entry, match: Match | None) -> None:
        if match is None or entry.n_label in excluded or entry.value.lower() in excluded:
            return
        if entry.source == "yours":
            match.score += 80
        current = matches.get(entry.n_label)
        if current is None or match.score > current.score:
            # Keep the catalog's hint/aliases when a personal entry duplicates it,
            # but let the personal boost decide the order.
            if current is not None and current.entry.source == "catalog" and entry.source == "yours":
                match = Match(current.entry, match.score, match.exact or current.exact, current.via_alias)
            matches[entry.n_label] = match

    for entry in personal:
        consider(entry, _score(entry, query, q_words) or (_score(entry, expanded, q_words) if expanded != query else None))
    for entry in catalog:
        consider(entry, _score(entry, query, q_words) or (_score(entry, expanded, q_words) if expanded != query else None))

    if query and len(matches) < limit:
        for entry in (*personal, *catalog):
            if entry.n_label not in matches:
                consider(entry, _fuzzy(entry, q_words))

    ranked = sorted(matches.values(), key=lambda m: (-m.score, m.entry.n_label))[:limit]
    items = []
    for m in ranked:
        hint = m.entry.hint
        if m.via_alias and m.via_alias != m.entry.n_label:
            hint = f"{hint} · matches “{m.via_alias}”" if hint else f"matches “{m.via_alias}”"
        items.append(
            {
                "value": m.entry.value,
                "label": m.entry.label,
                "hint": hint,
                "source": m.entry.source,
                "exact": m.exact,
            }
        )
    return {"kind": kind, "q": q, "items": items}


__all__ = ["KINDS", "invalidate_user", "suggest"]

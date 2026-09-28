"""Search-query variation generation.

One query misses jobs that use a different title for the same work, so the
hunt fans out: every target role against every location tier, plus a few
skill-combination queries ("React TypeScript Developer") that catch postings
titled around the stack instead of the role.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.resume.parser import normalize_skill_list
from app.services.sources.base import SourceQuery


@dataclass(slots=True)
class HuntQuery:
    label: str
    keywords: str
    location: str = ""
    remote: bool = False
    origin: str = "generated"  # generated | custom
    tier: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def signature(self) -> tuple[str, str, bool]:
        return (self.keywords.lower().strip(), self.location.lower().strip(), self.remote)

    def to_source_query(self, limit: int) -> SourceQuery:
        keywords = [self.keywords]
        return SourceQuery(
            keywords=keywords,
            locations=[self.location] if self.location else [],
            remote_only=self.remote,
            limit=limit,
        )


def _tier_targets(tier: dict[str, Any], country: str) -> list[tuple[str, str, bool]]:
    """``(location, label_suffix, remote)`` search targets for one tier."""
    modes = tier.get("work_modes") or []
    places = [str(p).strip() for p in (tier.get("places") or []) if str(p).strip()]
    targets: list[tuple[str, str, bool]] = []

    if "remote" in modes:
        where = places[0] if places else ""
        # A remote search is not narrowed to a city; the region goes in the
        # label so the user can read what was asked.
        targets.append(("", f"Remote {where}".strip(), True))
    if any(m in modes for m in ("onsite", "hybrid")):
        for place in places[:3] or [country]:
            prefix = "Hybrid " if modes == ["hybrid"] else ""
            targets.append((place, f"{prefix}{place}", False))
    return targets


def generate_queries(config: Any) -> list[HuntQuery]:
    """Build the ordered, de-duplicated query list for a hunt run.

    Custom queries come first and always run. Generated ones follow role
    order, each role searched across every location tier, so capping the
    list keeps the top roles in every location rather than one location only.
    """
    max_queries = max(1, int(getattr(config, "max_queries", 20) or 20))
    excluded = {str(q).strip().lower() for q in (getattr(config, "excluded_queries", None) or [])}
    country = str(getattr(config, "country", "") or "India")

    out: list[HuntQuery] = []
    seen: set[tuple[str, str, bool]] = set()

    def add(query: HuntQuery) -> None:
        if query.label.lower() in excluded:
            return
        if query.signature() in seen:
            return
        seen.add(query.signature())
        out.append(query)

    for text in getattr(config, "custom_queries", None) or []:
        text = str(text).strip()
        if text:
            add(HuntQuery(label=text, keywords=text, origin="custom"))

    if not getattr(config, "auto_queries", True):
        return out

    tiers = [t for t in (getattr(config, "location_tiers", None) or []) if isinstance(t, dict)]
    tier_targets = [(t, _tier_targets(t, country)) for t in tiers]
    roles = [str(r).strip() for r in (getattr(config, "target_roles", None) or []) if str(r).strip()]

    generated: list[HuntQuery] = []
    for role in roles:
        for tier, targets in tier_targets:
            for location, suffix, remote in targets:
                generated.append(
                    HuntQuery(
                        label=f"{role} {suffix}".strip(),
                        keywords=role,
                        location=location,
                        remote=remote,
                        tier=str(tier.get("name") or ""),
                    )
                )

    # Skill-combination queries for the top tier: the stack words employers
    # put in titles when they do not use a standard role name.
    skills = normalize_skill_list(getattr(config, "skills", None) or [])[:4]
    combos: list[str] = []
    if len(skills) >= 2:
        combos.append(f"{skills[0]} {skills[1]} Developer")
    if len(skills) >= 4:
        combos.append(f"{skills[0]} {skills[3]} Developer")
    if tier_targets and combos:
        first_tier, targets = tier_targets[0]
        for combo in combos:
            for location, suffix, remote in targets[:1]:
                generated.append(
                    HuntQuery(
                        label=f"{combo} {suffix}".strip(),
                        keywords=combo,
                        location=location,
                        remote=remote,
                        tier=str(first_tier.get("name") or ""),
                    )
                )

    # Order: each role across *every* location tier before the next role, so
    # the cap never spends itself on one tier (e.g. only "Remote India"
    # queries and no Jaipur search at all). Skill combos follow the top role.
    role_keys = [role for role in roles]
    combo_queries = [q for q in generated if q.keywords not in role_keys]
    for index, role in enumerate(role_keys):
        for query in generated:
            if query.keywords == role:
                add(query)
        if index == 0:
            for query in combo_queries:
                add(query)

    return out[:max(max_queries, sum(1 for q in out if q.origin == "custom"))]


def board_query(config: Any, limit: int) -> SourceQuery:
    """The single query used for board-style sources (Greenhouse, Lever...).

    Boards return a company's whole board and are filtered client-side on
    "any keyword present", so role names plus job-family words give recall;
    the hunt's own assessment does the precise filtering afterwards.
    """
    keywords: list[str] = []
    for value in list(getattr(config, "target_roles", None) or []) + list(
        getattr(config, "role_keywords", None) or []
    ):
        text = str(value).strip()
        # Board filtering is a plain substring test, so a short word like "ui"
        # would match "build" and pull in the entire board.
        if len(text) < 4:
            continue
        if text.lower() not in (k.lower() for k in keywords):
            keywords.append(text)
    return SourceQuery(keywords=keywords, limit=limit)


__all__ = ["HuntQuery", "board_query", "generate_queries"]

"""Layered job deduplication (spec §10).

The same opening reaches us from several sources with different ids, different
URLs, and slightly different titles. Matching runs cheapest-and-strongest
first so an exact identity never pays for a fuzzy scan, and the fuzzy layer is
constrained to one company so two unrelated roles can never collapse.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.jobs import Job
from app.services.normalize import (
    apply_link_quality,
    canonical_url,
    norm_text,
    normalize_company,
    normalize_location,
    text_hash,
    title_similarity,
)
from app.services.sources.base import RawJob

# Above this token overlap two titles at the same company are the same role.
# Tuned so "Senior Backend Engineer" matches "Senior Backend Engineer (Remote)"
# but not "Senior Frontend Engineer".
FUZZY_TITLE_THRESHOLD = 0.82


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; compare everything as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _sha256(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _get(obj: RawJob | Job, attr: str, default: Any = "") -> Any:
    value = getattr(obj, attr, default)
    return default if value is None else value


def compute_dedupe_key(raw: RawJob | Job, source_name: str) -> str:
    """Stable identity hash using the strongest signal the posting offers.

    Source + external id is authoritative when present; a canonical URL is next
    best; otherwise fall back to company/title/location, which is weak but
    still beats treating every ingest as a new job.
    """
    external_id = str(_get(raw, "external_id")).strip()
    if external_id:
        return _sha256("ext", norm_text(source_name), external_id.lower())

    url = canonical_url(str(_get(raw, "url")))
    if url:
        return _sha256("url", url.lower())

    return _sha256(
        "cta",
        normalize_company(str(_get(raw, "company"))),
        norm_text(str(_get(raw, "title"))),
        normalize_location(str(_get(raw, "location"))),
    )


def _base_query(user_id: str):
    return select(Job).where(Job.user_id == user_id, Job.deleted_at.is_(None))


def find_duplicate(
    db: Session, user_id: str, candidate: RawJob, source_name: str
) -> Job | None:
    """Return the existing Job this candidate duplicates, or None.

    Layers, in order of decreasing confidence:
      1. same source + external id
      2. identical canonical URL
      3. identical normalized company + title + location
      4. same company and a title similarity above the fuzzy threshold
      5. identical description hash
    """
    external_id = (candidate.external_id or "").strip()
    if external_id:
        hit = db.scalars(
            _base_query(user_id)
            .where(Job.source_name == source_name, Job.external_id == external_id)
            .limit(1)
        ).first()
        if hit is not None:
            return hit

        # A previous run may have recorded this posting under a different
        # source; the dedupe key encodes source+id, so check it too.
        hit = db.scalars(
            _base_query(user_id)
            .where(Job.dedupe_key == compute_dedupe_key(candidate, source_name))
            .limit(1)
        ).first()
        if hit is not None:
            return hit

    curl = canonical_url(candidate.url)
    if curl:
        hit = db.scalars(_base_query(user_id).where(Job.canonical_url == curl).limit(1)).first()
        if hit is not None:
            return hit

    company_key = normalize_company(candidate.company)
    title_key = norm_text(candidate.title)
    location_key = normalize_location(candidate.location)

    if company_key and title_key:
        same_company = list(
            db.scalars(
                _base_query(user_id).where(Job.company_normalized == company_key).limit(500)
            )
        )
        for existing in same_company:
            if (
                norm_text(existing.title) == title_key
                and normalize_location(existing.location) == location_key
            ):
                return existing
        for existing in same_company:
            if title_similarity(existing.title, candidate.title) >= FUZZY_TITLE_THRESHOLD:
                return existing

    # Descriptions are long enough that an exact hash collision across genuinely
    # different roles is not a practical concern; a shared boilerplate blurb is,
    # so this layer runs last and only for substantial text.
    description = candidate.description or ""
    if len(description.strip()) >= 200:
        hit = db.scalars(
            _base_query(user_id).where(Job.description_hash == text_hash(description)).limit(1)
        ).first()
        if hit is not None:
            return hit

    return None


_FILL_IF_EMPTY_STRINGS = (
    "location",
    "url",
    "apply_url",
    "description",
    "salary_raw",
    "industry",
    "external_id",
)
_FILL_IF_NONE_NUMBERS = (
    "salary_min_lpa",
    "salary_max_lpa",
    "experience_min_years",
    "experience_max_years",
)


def merge_duplicate(
    db: Session, existing: Job, candidate: RawJob, source_name: str
) -> Job:
    """Fold a re-sighting into the stored job without losing data.

    Enrichment only: a source that knows the salary fills a gap left by one
    that did not, but no source may overwrite a value another already
    supplied. First writer wins, so the record stops churning.
    """
    now = _utcnow()
    existing.seen_count = int(existing.seen_count or 0) + 1
    existing.last_seen_at = now
    if existing.first_seen_at is None:
        existing.first_seen_at = now

    sources = list(existing.duplicate_sources or [])
    if source_name and source_name not in sources and source_name != existing.source_name:
        sources.append(source_name)
        existing.duplicate_sources = sources

    for attr in _FILL_IF_EMPTY_STRINGS:
        if not str(getattr(existing, attr, "") or "").strip():
            value = str(getattr(candidate, attr, "") or "").strip()
            if value:
                setattr(existing, attr, value)

    for attr in _FILL_IF_NONE_NUMBERS:
        if getattr(existing, attr, None) is None:
            value = getattr(candidate, attr, None)
            if value is not None:
                setattr(existing, attr, value)

    # The one deliberate exception to "first writer wins": an application link
    # that goes more directly to the employer (their ATS or careers page)
    # replaces an aggregator copy, because that is the link worth applying via.
    candidate_link = str(getattr(candidate, "apply_url", "") or getattr(candidate, "url", "") or "").strip()
    if candidate_link and existing.apply_url and apply_link_quality(candidate_link) > apply_link_quality(
        existing.apply_url
    ):
        existing.apply_url = candidate_link

    if existing.posted_at is None and candidate.posted_at is not None:
        existing.posted_at = candidate.posted_at
    candidate_updated = getattr(candidate, "source_updated_at", None)
    if candidate_updated is not None and (
        existing.source_updated_at is None or _aware(candidate_updated) > _aware(existing.source_updated_at)
    ):
        existing.source_updated_at = candidate_updated
    if not existing.is_remote and candidate.is_remote:
        existing.is_remote = True

    # Derived columns are rebuilt from whatever now populates their source
    # field, so an enriched URL or description does not leave a stale index.
    if existing.url and not existing.canonical_url:
        existing.canonical_url = canonical_url(existing.url)
    if existing.description and not existing.description_hash:
        existing.description_hash = text_hash(existing.description)
    if existing.company and not existing.company_normalized:
        existing.company_normalized = normalize_company(existing.company)

    if candidate.raw and not existing.raw_payload:
        existing.raw_payload = candidate.raw

    return existing


__all__ = [
    "FUZZY_TITLE_THRESHOLD",
    "compute_dedupe_key",
    "find_duplicate",
    "merge_duplicate",
]

"""Job discovery: fan out over the user's enabled sources and ingest results.

This is the only place that turns provider payloads into ``Job`` rows. It owns
no transaction -- the caller (an API route or a scheduled run) decides when to
commit -- but it does flush, because dedupe has to see rows written earlier in
the same run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.enums import SourceHealth
from app.db.models.jobs import Job, JobEvent, JobSource
from app.db.models.ops import EncryptedSecret
from app.db.models.preferences import JobPreference, SavedSearch
from app.core.security import decrypt_secret
from app.services.dedupe import compute_dedupe_key, find_duplicate, merge_duplicate
from app.services.normalize import canonical_url, normalize_company, text_hash
from app.services.sources import RawJob, SourceQuery, get_adapter
from app.services.sources.base import SourceError, UnknownAdapterError

logger = logging.getLogger(__name__)

# A source is only marked failing after repeated failures; one flaky response
# should not take a provider out of the rotation.
FAILURE_THRESHOLD = 3


@dataclass(slots=True)
class DiscoveryResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict] = field(default_factory=list)
    per_source: dict = field(default_factory=dict)

    @property
    def total_seen(self) -> int:
        return self.created + self.updated + self.skipped


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------
def build_query(
    db: Session,
    user_id: str,
    *,
    saved_search_id: str | None = None,
    limit_per_source: int = 50,
) -> SourceQuery:
    """Turn stored user policy into a provider-agnostic search.

    A saved search wins when one is named, because the user chose it
    explicitly for this run; otherwise the standing preferences apply.
    """
    if saved_search_id:
        saved = db.scalars(
            select(SavedSearch).where(
                SavedSearch.id == saved_search_id, SavedSearch.user_id == user_id
            )
        ).first()
        if saved is None:
            raise ValueError(f"Saved search {saved_search_id} not found for this user.")
        return SourceQuery(
            keywords=[str(k) for k in (saved.keywords or []) if str(k).strip()],
            locations=[str(l) for l in (saved.locations or []) if str(l).strip()],
            remote_only=bool(saved.remote_only),
            min_salary_lpa=saved.min_salary_lpa,
            employment_types=[str(t) for t in (saved.employment_types or []) if str(t).strip()],
            limit=limit_per_source,
        )

    prefs = db.scalars(
        select(JobPreference).where(JobPreference.user_id == user_id)
    ).first()
    if prefs is None:
        return SourceQuery(limit=limit_per_source)

    return SourceQuery(
        keywords=[str(r) for r in (prefs.target_roles or []) if str(r).strip()],
        locations=[str(l) for l in (prefs.preferred_locations or []) if str(l).strip()],
        remote_only=bool(prefs.remote_only),
        min_salary_lpa=prefs.min_salary_lpa,
        employment_types=[str(t) for t in (prefs.employment_types or []) if str(t).strip()],
        limit=limit_per_source,
    )


def _load_sources(
    db: Session, user_id: str, source_ids: list[str] | None
) -> list[JobSource]:
    stmt = (
        select(JobSource)
        .where(
            JobSource.user_id == user_id,
            JobSource.enabled.is_(True),
            JobSource.deleted_at.is_(None),
        )
        .order_by(JobSource.priority.asc(), JobSource.name.asc())
    )
    if source_ids:
        stmt = stmt.where(JobSource.id.in_(list(source_ids)))
    return list(db.scalars(stmt))


def _resolve_credential(db: Session, source: JobSource) -> str | None:
    """Decrypt the source's stored credential, if it has one.

    Returns None (rather than raising) when the reference dangles, so the
    adapter reports a clean "credential required" failure instead of the run
    dying with a decryption traceback.
    """
    if not source.credential_ref:
        return None
    secret = db.scalars(
        select(EncryptedSecret).where(
            EncryptedSecret.id == source.credential_ref,
            EncryptedSecret.user_id == source.user_id,
        )
    ).first()
    if secret is None:
        logger.warning("Source %s references a missing credential.", source.id)
        return None
    try:
        return decrypt_secret(secret.ciphertext)
    except ValueError:
        logger.warning("Credential for source %s could not be decrypted.", source.id)
        return None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _new_job(user_id: str, source: JobSource, candidate: RawJob, dedupe_key: str) -> Job:
    now = _utcnow()
    description = candidate.description or ""
    return Job(
        user_id=user_id,
        source_id=source.id,
        source_name=source.name,
        external_id=(candidate.external_id or "")[:200],
        title=(candidate.title or "")[:300],
        company=(candidate.company or "")[:200],
        company_normalized=normalize_company(candidate.company)[:200],
        location=(candidate.location or "")[:200],
        is_remote=bool(candidate.is_remote),
        url=(candidate.url or "")[:1000],
        canonical_url=canonical_url(candidate.url)[:1000],
        apply_url=(candidate.apply_url or candidate.url or "")[:1000],
        description=description,
        description_hash=text_hash(description) if description else "",
        salary_min_lpa=candidate.salary_min_lpa,
        salary_max_lpa=candidate.salary_max_lpa,
        salary_raw=(candidate.salary_raw or "")[:200],
        currency=(candidate.currency or "INR")[:10],
        employment_type=(candidate.employment_type or "full_time")[:50],
        industry=(candidate.industry or "")[:100],
        experience_min_years=candidate.experience_min_years,
        experience_max_years=candidate.experience_max_years,
        posted_at=candidate.posted_at,
        status="new",
        dedupe_key=dedupe_key,
        first_seen_at=now,
        last_seen_at=now,
        seen_count=1,
        duplicate_sources=[],
        raw_payload=candidate.raw or {},
    )


def _record_event(db: Session, job: Job, event_type: str, source: JobSource, message: str) -> None:
    db.add(
        JobEvent(
            job_id=job.id,
            event_type=event_type,
            message=message,
            actor="discovery",
            payload={"source_id": source.id, "source_name": source.name},
        )
    )


def _mark_success(source: JobSource, found: int) -> None:
    now = _utcnow()
    source.last_attempt_at = now
    source.last_success_at = now
    source.consecutive_failures = 0
    source.last_error = ""
    source.health = SourceHealth.HEALTHY.value
    logger.info("Source %s returned %d postings.", source.name, found)


def _mark_failure(source: JobSource, error: str) -> None:
    source.last_attempt_at = _utcnow()
    source.consecutive_failures = int(source.consecutive_failures or 0) + 1
    source.last_error = error[:2000]
    source.health = (
        SourceHealth.FAILING.value
        if source.consecutive_failures >= FAILURE_THRESHOLD
        else SourceHealth.DEGRADED.value
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def discover(
    db: Session,
    user_id: str,
    *,
    source_ids: list[str] | None = None,
    saved_search_id: str | None = None,
    limit_per_source: int = 50,
) -> DiscoveryResult:
    """Run every enabled source and ingest what they return.

    One bad provider must never cost the user the rest of the run, so each
    source is wrapped individually and its failure recorded on its own row.
    """
    result = DiscoveryResult()
    query = build_query(
        db, user_id, saved_search_id=saved_search_id, limit_per_source=limit_per_source
    )

    for source in _load_sources(db, user_id, source_ids):
        stats = {"created": 0, "updated": 0, "skipped": 0, "found": 0, "error": ""}
        result.per_source[source.id] = stats
        try:
            adapter = get_adapter(
                source.adapter_type, source.config or {}, _resolve_credential(db, source)
            )
            candidates = adapter.search(query)
        except (SourceError, UnknownAdapterError) as exc:
            message = str(exc)
            _mark_failure(source, message)
            stats["error"] = message
            result.errors.append(
                {"source_id": source.id, "source_name": source.name, "error": message}
            )
            continue
        except Exception as exc:  # noqa: BLE001 - an adapter bug must not abort the run
            message = f"{type(exc).__name__}: {exc}"
            logger.exception("Source %s raised an unexpected error.", source.name)
            _mark_failure(source, message)
            stats["error"] = message
            result.errors.append(
                {"source_id": source.id, "source_name": source.name, "error": message}
            )
            continue

        stats["found"] = len(candidates)
        _mark_success(source, len(candidates))

        for candidate in candidates:
            try:
                created = _ingest(db, user_id, source, candidate)
            except Exception as exc:  # noqa: BLE001 - skip the posting, keep the run
                logger.warning(
                    "Skipping a posting from %s: %s", source.name, type(exc).__name__
                )
                stats["skipped"] += 1
                result.skipped += 1
                continue
            if created:
                stats["created"] += 1
                result.created += 1
            else:
                stats["updated"] += 1
                result.updated += 1

    # Flush (never commit) so the caller can query the run's jobs and events
    # before deciding whether to commit.
    db.flush()
    return result


def _ingest(db: Session, user_id: str, source: JobSource, candidate: RawJob) -> bool:
    """Insert or merge one posting. Returns True when a new Job was created."""
    if not (candidate.title or "").strip():
        raise ValueError("Posting has no title.")

    existing = find_duplicate(db, user_id, candidate, source.name)
    if existing is not None:
        merge_duplicate(db, existing, candidate, source.name)
        _record_event(
            db, existing, "seen_again", source, f"Seen again via {source.name}."
        )
        return False

    dedupe_key = compute_dedupe_key(candidate, source.name)
    # The (user_id, dedupe_key) unique constraint would otherwise fail the
    # whole transaction if a provider returned the same posting twice.
    clash = db.scalars(
        select(Job).where(Job.user_id == user_id, Job.dedupe_key == dedupe_key).limit(1)
    ).first()
    if clash is not None:
        merge_duplicate(db, clash, candidate, source.name)
        _record_event(db, clash, "seen_again", source, f"Seen again via {source.name}.")
        return False

    job = _new_job(user_id, source, candidate, dedupe_key)
    db.add(job)
    # Flush so the job has an id for its event and is visible to the dedupe
    # queries of every later posting in this same run.
    db.flush()
    _record_event(db, job, "discovered", source, f"Discovered via {source.name}.")
    return True


__all__ = ["DiscoveryResult", "FAILURE_THRESHOLD", "build_query", "discover"]

"""Lever postings adapter.

https://api.lever.co/v0/postings/{company}?mode=json -- public per-company
board, no credential, no server-side search.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.normalize import (
    is_remote_text,
    parse_experience,
    parse_salary,
    salary_from_numbers,
)
from app.services.sources.base import (
    JobSourceAdapter,
    RawJob,
    SourceError,
    SourceQuery,
    SourceTestResult,
    http_get_json,
    normalize_employment_type,
    register_adapter,
    sanitize_description,
)

API_BASE = "https://api.lever.co/v0/postings"


@register_adapter
class LeverAdapter(JobSourceAdapter):
    adapter_type = "lever"
    display_name = "Lever board"
    requires_credential = False
    config_schema = [
        {
            "key": "company",
            "label": "Lever company slug",
            "type": "text",
            "required": True,
            "help": "The slug in jobs.lever.co/<company>.",
            "placeholder": "acme",
        },
        {
            "key": "company_name",
            "label": "Company name",
            "type": "text",
            "required": False,
            "help": "Display name for postings; defaults to the slug.",
            "placeholder": "Acme Inc",
        },
    ]

    def _postings_url(self) -> str:
        return f"{API_BASE}/{self.require_config('company')}"

    def _company(self) -> str:
        return self.config_value("company_name") or self.config_value("company")

    def test_connection(self) -> SourceTestResult:
        try:
            payload = http_get_json(self._postings_url(), params={"mode": "json", "limit": 1})
        except SourceError as exc:
            return SourceTestResult(ok=False, message=str(exc))
        count = len(payload) if isinstance(payload, list) else 0
        return SourceTestResult(
            ok=True,
            message=f"Lever board '{self.config_value('company')}' reachable.",
            details={"sample_size": count},
        )

    def search(self, query: SourceQuery) -> list[RawJob]:
        payload = http_get_json(self._postings_url(), params={"mode": "json"})
        entries = payload if isinstance(payload, list) else []

        jobs: list[RawJob] = []
        limit = self._limit(query)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw_job = self._to_raw_job(entry)
            if not self._matches_keywords(query, raw_job.title, raw_job.description):
                continue
            if query.remote_only and not raw_job.is_remote:
                continue
            jobs.append(raw_job)
            if len(jobs) >= limit:
                break
        return jobs

    def _to_raw_job(self, entry: dict) -> RawJob:
        categories = entry.get("categories") or {}
        location = str(categories.get("location") or "").strip()
        title = str(entry.get("text") or "").strip()
        url = str(entry.get("hostedUrl") or "")

        # Lever gives both a plain-text and an HTML body; prefer the plain one
        # but still sanitize it, because it is attacker-controlled either way.
        body = entry.get("descriptionPlain") or entry.get("description") or ""
        extra = entry.get("additionalPlain") or entry.get("additional") or ""
        lists_text = "\n".join(
            f"{item.get('text', '')}\n{item.get('content', '')}"
            for item in (entry.get("lists") or [])
            if isinstance(item, dict)
        )
        description = sanitize_description("\n\n".join(p for p in (body, lists_text, extra) if p))

        salary_min, salary_max, salary_raw = self._salary(entry)
        exp_min, exp_max = parse_experience(description)

        return RawJob(
            external_id=str(entry.get("id") or url),
            title=title,
            company=self._company(),
            location=location,
            is_remote=bool(entry.get("workplaceType") == "remote")
            or is_remote_text(location, title, str(categories.get("allLocations") or "")),
            url=url,
            apply_url=str(entry.get("applyUrl") or url),
            description=description,
            salary_min_lpa=salary_min,
            salary_max_lpa=salary_max,
            salary_raw=salary_raw,
            currency="INR",
            employment_type=normalize_employment_type(categories.get("commitment")),
            industry=str(categories.get("department") or categories.get("team") or "").strip(),
            experience_min_years=exp_min,
            experience_max_years=exp_max,
            posted_at=_epoch_millis_to_datetime(entry.get("createdAt")),
            source_updated_at=_epoch_millis_to_datetime(entry.get("updatedAt")),
            raw=entry,
        )

    def _salary(self, entry: dict) -> tuple[float | None, float | None, str]:
        """Lever boards expose salary either as a numeric range or not at all."""
        salary_range = entry.get("salaryRange")
        if isinstance(salary_range, dict):
            currency = str(salary_range.get("currency") or "INR").upper()
            low, high = salary_from_numbers(
                salary_range.get("min"),
                salary_range.get("max"),
                currency=currency,
                period=str(salary_range.get("interval") or "year").lower(),
            )
            raw = " - ".join(
                str(v) for v in (salary_range.get("min"), salary_range.get("max")) if v
            )
            return low, high, f"{raw} {currency}".strip() if raw else ""
        if isinstance(salary_range, str) and salary_range.strip():
            low, high = parse_salary(salary_range)
            return low, high, salary_range.strip()[:200]
        return None, None, ""


def _epoch_millis_to_datetime(value: object) -> datetime | None:
    """Lever timestamps are epoch milliseconds, not ISO strings."""
    try:
        millis = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc)

"""Greenhouse job board adapter.

https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
Public, per-company, no credential. The API has no search parameter, so the
whole board is fetched and keyword filtering happens client-side.
"""
from __future__ import annotations

from app.services.normalize import is_remote_text, parse_experience, parse_salary
from app.services.sources.base import (
    JobSourceAdapter,
    RawJob,
    SourceError,
    SourceQuery,
    SourceTestResult,
    http_get_json,
    normalize_employment_type,
    parse_iso_datetime,
    register_adapter,
    sanitize_description,
)

API_BASE = "https://boards-api.greenhouse.io/v1/boards"


@register_adapter
class GreenhouseAdapter(JobSourceAdapter):
    adapter_type = "greenhouse"
    display_name = "Greenhouse board"
    requires_credential = False
    config_schema = [
        {
            "key": "board_token",
            "label": "Board token",
            "type": "text",
            "required": True,
            "help": "The company slug in boards.greenhouse.io/<token>.",
            "placeholder": "acme",
        },
        {
            "key": "company_name",
            "label": "Company name",
            "type": "text",
            "required": False,
            "help": "Display name for postings; defaults to the board token.",
            "placeholder": "Acme Inc",
        },
    ]

    def _jobs_url(self) -> str:
        return f"{API_BASE}/{self.require_config('board_token')}/jobs"

    def _company(self) -> str:
        return self.config_value("company_name") or self.config_value("board_token")

    def test_connection(self) -> SourceTestResult:
        try:
            payload = http_get_json(self._jobs_url())
        except SourceError as exc:
            return SourceTestResult(ok=False, message=str(exc))
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        return SourceTestResult(
            ok=True,
            message=f"Greenhouse board '{self.config_value('board_token')}' reachable.",
            details={"open_roles": len(jobs)},
        )

    def search(self, query: SourceQuery) -> list[RawJob]:
        payload = http_get_json(self._jobs_url(), params={"content": "true"})
        entries = payload.get("jobs", []) if isinstance(payload, dict) else []

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

    def fetch_job(self, external_id: str) -> RawJob | None:
        try:
            payload = http_get_json(f"{self._jobs_url()}/{external_id}")
        except SourceError:
            return None
        return self._to_raw_job(payload) if isinstance(payload, dict) else None

    def _to_raw_job(self, entry: dict) -> RawJob:
        # Greenhouse HTML-escapes the posting body inside `content`;
        # sanitize_description unescapes and then strips the markup.
        description = sanitize_description(entry.get("content"))
        location = str((entry.get("location") or {}).get("name") or "").strip()
        title = str(entry.get("title") or "").strip()
        url = str(entry.get("absolute_url") or "")

        metadata = entry.get("metadata") or []
        employment = ""
        salary_raw = ""
        for item in metadata:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").lower()
            value = item.get("value")
            if value is None or isinstance(value, (list, dict)):
                continue
            if "employment" in name or "job type" in name:
                employment = str(value)
            elif "salary" in name or "compensation" in name or "pay" in name:
                salary_raw = str(value)

        salary_min, salary_max = parse_salary(salary_raw) if salary_raw else (None, None)
        exp_min, exp_max = parse_experience(description)

        return RawJob(
            external_id=str(entry.get("id") or url),
            title=title,
            company=self._company(),
            location=location,
            is_remote=is_remote_text(location, title),
            url=url,
            apply_url=url,
            description=description,
            salary_min_lpa=salary_min,
            salary_max_lpa=salary_max,
            salary_raw=salary_raw,
            currency="INR",
            employment_type=normalize_employment_type(employment),
            industry="",
            experience_min_years=exp_min,
            experience_max_years=exp_max,
            posted_at=parse_iso_datetime(entry.get("updated_at") or entry.get("first_published")),
            raw=entry,
        )

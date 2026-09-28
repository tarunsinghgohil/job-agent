"""Remotive public job API adapter.

https://remotive.com/api/remote-jobs -- documented, public, no credential.
Every posting on Remotive is remote by definition.
"""
from __future__ import annotations

from typing import Any

from app.services.normalize import norm_text, parse_experience, parse_salary
from app.services.sources.base import (
    JobSourceAdapter,
    RawJob,
    SourceQuery,
    SourceTestResult,
    http_get_json,
    normalize_employment_type,
    parse_iso_datetime,
    register_adapter,
    sanitize_description,
    strip_currency_symbols,
)

API_URL = "https://remotive.com/api/remote-jobs"


@register_adapter
class RemotiveAdapter(JobSourceAdapter):
    adapter_type = "remotive"
    display_name = "Remotive (remote jobs)"
    requires_credential = False
    supports_search = True
    config_schema = [
        {
            "key": "category",
            "label": "Category",
            "type": "text",
            "required": False,
            "help": "Optional Remotive category slug, e.g. software-dev or data.",
            "placeholder": "software-dev",
        },
        {
            "key": "company_name",
            "label": "Company filter",
            "type": "text",
            "required": False,
            "help": "Restrict results to a single company as named on Remotive.",
            "placeholder": "Acme",
        },
    ]

    def test_connection(self) -> SourceTestResult:
        try:
            payload = http_get_json(API_URL, params={"limit": 1})
        except Exception as exc:
            return SourceTestResult(ok=False, message=str(exc))
        count = payload.get("job-count") if isinstance(payload, dict) else None
        return SourceTestResult(
            ok=True,
            message="Remotive API reachable.",
            details={"job_count": count},
        )

    # Remotive blocks clients that call more than twice a minute and asks for
    # at most ~4 fetches a day, so a batch of query variations is answered
    # with ONE request and filtered locally.
    BATCH_LIMIT = 300

    def search_many(self, queries: list[SourceQuery]) -> list[RawJob] | None:
        params: dict[str, Any] = {
            "limit": self.BATCH_LIMIT,
            "category": self.config_value("category") or "software-dev",
        }
        if self.config_value("company_name"):
            params["company_name"] = self.config_value("company_name")
        payload = http_get_json(API_URL, params=params)
        entries = payload.get("jobs", []) if isinstance(payload, dict) else []
        jobs = [self._to_raw_job(entry) for entry in entries if isinstance(entry, dict)]
        phrases = [_core_phrase(q.keyword_text()) for q in queries]
        phrases = [p for p in phrases if p]
        if not phrases:
            return jobs
        return [job for job in jobs if any(_title_matches(job.title, p) for p in phrases)]

    def query_signature(self, query: SourceQuery) -> tuple:
        # Every Remotive job is remote and the API has no location filter.
        return (query.keyword_text().lower(),)

    def search(self, query: SourceQuery) -> list[RawJob]:
        limit = self._limit(query)
        params: dict[str, Any] = {"limit": limit}
        if query.keyword_text():
            params["search"] = query.keyword_text()
        if self.config_value("category"):
            params["category"] = self.config_value("category")
        if self.config_value("company_name"):
            params["company_name"] = self.config_value("company_name")

        payload = http_get_json(API_URL, params=params)
        entries = payload.get("jobs", []) if isinstance(payload, dict) else []
        return [self._to_raw_job(entry) for entry in entries if isinstance(entry, dict)][:limit]

    def _to_raw_job(self, entry: dict) -> RawJob:
        description = sanitize_description(entry.get("description"))
        salary_raw = str(entry.get("salary") or "").strip()
        # Remotive quotes salaries free-text and usually in USD.
        salary_min, salary_max = parse_salary(strip_currency_symbols(salary_raw), currency="USD")
        exp_min, exp_max = parse_experience(description)
        url = str(entry.get("url") or "")

        return RawJob(
            external_id=str(entry.get("id") or url),
            title=str(entry.get("title") or "").strip(),
            company=str(entry.get("company_name") or "").strip(),
            location=str(entry.get("candidate_required_location") or "Remote").strip(),
            is_remote=True,
            url=url,
            apply_url=url,
            description=description,
            salary_min_lpa=salary_min,
            salary_max_lpa=salary_max,
            salary_raw=salary_raw,
            currency="USD",
            employment_type=normalize_employment_type(entry.get("job_type")),
            industry=str(entry.get("category") or "").strip(),
            experience_min_years=exp_min,
            experience_max_years=exp_max,
            posted_at=parse_iso_datetime(entry.get("publication_date")),
            raw=entry,
        )


_SENIORITY_WORDS = {"senior", "sr", "junior", "jr", "lead", "staff", "principal", "mid", "level"}
_GENERIC_WORDS = _SENIORITY_WORDS | {"developer", "engineer", "remote", "india", "the", "and", "of"}


def _core_phrase(text: str) -> str:
    """'Senior React Developer' -> 'react developer' (seniority words dropped)."""
    words = [w for w in norm_text(text).split() if w not in _SENIORITY_WORDS]
    return " ".join(words)


def _title_matches(title: str, phrase: str) -> bool:
    """Phrase containment, or every distinctive word of it in the title."""
    title_norm = norm_text(title)
    if phrase in title_norm:
        return True
    distinctive = [w for w in phrase.split() if w not in _GENERIC_WORDS]
    title_words = set(title_norm.split())
    return bool(distinctive) and all(w in title_words for w in distinctive)

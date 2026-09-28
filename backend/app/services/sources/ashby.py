"""Ashby job board adapter.

https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true
Public per-company board, no credential. Ashby is the only board API of the
three that returns structured compensation, so it is requested explicitly.
"""
from __future__ import annotations

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
    parse_iso_datetime,
    register_adapter,
    sanitize_description,
    strip_currency_symbols,
)

API_BASE = "https://api.ashbyhq.com/posting-api/job-board"

# Ashby reports the pay interval as a phrase, not a unit.
_INTERVAL_TO_PERIOD = {
    "1 year": "year", "year": "year", "annual": "year", "yearly": "year",
    "1 month": "month", "month": "month", "monthly": "month",
    "1 hour": "hour", "hour": "hour", "hourly": "hour",
    "1 day": "day", "day": "day", "daily": "day",
}


@register_adapter
class AshbyAdapter(JobSourceAdapter):
    adapter_type = "ashby"
    display_name = "Ashby board"
    requires_credential = False
    config_schema = [
        {
            "key": "board_name",
            "label": "Board name",
            "type": "text",
            "required": True,
            "help": "The slug in jobs.ashbyhq.com/<board-name>.",
            "placeholder": "acme",
        },
        {
            "key": "company_name",
            "label": "Company name",
            "type": "text",
            "required": False,
            "help": "Display name for postings; defaults to the board name.",
            "placeholder": "Acme Inc",
        },
    ]

    def _board_url(self) -> str:
        return f"{API_BASE}/{self.require_config('board_name')}"

    def _company(self, payload: dict | None = None) -> str:
        configured = self.config_value("company_name")
        if configured:
            return configured
        if payload and payload.get("name"):
            return str(payload["name"]).strip()
        return self.config_value("board_name")

    def test_connection(self) -> SourceTestResult:
        try:
            payload = http_get_json(self._board_url())
        except SourceError as exc:
            return SourceTestResult(ok=False, message=str(exc))
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        return SourceTestResult(
            ok=True,
            message=f"Ashby board '{self.config_value('board_name')}' reachable.",
            details={"open_roles": len(jobs)},
        )

    def search(self, query: SourceQuery) -> list[RawJob]:
        payload = http_get_json(self._board_url(), params={"includeCompensation": "true"})
        if not isinstance(payload, dict):
            return []
        company = self._company(payload)

        jobs: list[RawJob] = []
        limit = self._limit(query)
        for entry in payload.get("jobs", []):
            if not isinstance(entry, dict):
                continue
            # Unlisted postings are drafts or internal roles.
            if entry.get("isListed") is False:
                continue
            raw_job = self._to_raw_job(entry, company)
            if not self._matches_keywords(query, raw_job.title, raw_job.description):
                continue
            if query.remote_only and not raw_job.is_remote:
                continue
            jobs.append(raw_job)
            if len(jobs) >= limit:
                break
        return jobs

    def _to_raw_job(self, entry: dict, company: str) -> RawJob:
        description = sanitize_description(
            entry.get("descriptionPlain") or entry.get("descriptionHtml")
        )
        location = str(entry.get("location") or "").strip()
        title = str(entry.get("title") or "").strip()
        url = str(entry.get("jobUrl") or "")

        salary_min, salary_max, salary_raw, currency = self._compensation(entry)
        exp_min, exp_max = parse_experience(description)

        return RawJob(
            external_id=str(entry.get("id") or url),
            title=title,
            company=company,
            location=location,
            is_remote=bool(entry.get("isRemote")) or is_remote_text(location, title),
            url=url,
            apply_url=str(entry.get("applyUrl") or url),
            description=description,
            salary_min_lpa=salary_min,
            salary_max_lpa=salary_max,
            salary_raw=salary_raw,
            currency=currency,
            employment_type=normalize_employment_type(entry.get("employmentType")),
            industry=str(entry.get("department") or entry.get("team") or "").strip(),
            experience_min_years=exp_min,
            experience_max_years=exp_max,
            posted_at=parse_iso_datetime(entry.get("publishedAt")),
            source_updated_at=parse_iso_datetime(entry.get("updatedAt")),
            raw=entry,
        )

    def _compensation(self, entry: dict) -> tuple[float | None, float | None, str, str]:
        """Prefer the structured salary component over the display summary.

        ``compensationTierSummary`` is a human string like "$150K – $200K";
        ``summaryComponents`` carries the same numbers with a currency and an
        interval, which converts to LPA without guessing.
        """
        comp = entry.get("compensation")
        if not isinstance(comp, dict):
            return None, None, "", "INR"

        summary = str(comp.get("compensationTierSummary") or "").strip()[:200]

        for component in comp.get("summaryComponents") or []:
            if not isinstance(component, dict):
                continue
            if str(component.get("compensationType") or "").lower() not in ("salary", ""):
                continue
            currency = str(component.get("currencyCode") or "INR").upper()
            period = _INTERVAL_TO_PERIOD.get(
                str(component.get("interval") or "").strip().lower(), "year"
            )
            low, high = salary_from_numbers(
                component.get("minValue"), component.get("maxValue"), currency=currency, period=period
            )
            if low is not None or high is not None:
                return low, high, summary or str(component.get("summary") or "")[:200], currency

        if summary:
            currency = "USD" if "$" in summary else "INR"
            low, high = parse_salary(strip_currency_symbols(summary), currency=currency)
            return low, high, summary, currency
        return None, None, "", "INR"

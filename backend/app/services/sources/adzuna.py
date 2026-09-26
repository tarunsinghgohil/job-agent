"""Adzuna aggregator adapter.

https://developer.adzuna.com/ -- requires an app id (config, not secret) plus
an app key (stored encrypted and passed in as the credential).
"""
from __future__ import annotations

from typing import Any

from app.services.normalize import is_remote_text, parse_experience, salary_from_numbers
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

API_BASE = "https://api.adzuna.com/v1/api/jobs"

# Adzuna quotes salaries in the country's own currency, so the country code
# decides how salary_from_numbers converts to LPA.
_COUNTRY_CURRENCY = {
    "in": "INR", "us": "USD", "gb": "GBP", "de": "EUR", "fr": "EUR",
    "nl": "EUR", "at": "EUR", "it": "EUR", "es": "EUR", "au": "USD",
    "ca": "USD", "sg": "USD", "za": "USD", "nz": "USD", "br": "USD",
    "mx": "USD", "pl": "EUR", "ru": "USD", "ch": "EUR", "be": "EUR",
}


@register_adapter
class AdzunaAdapter(JobSourceAdapter):
    adapter_type = "adzuna"
    display_name = "Adzuna"
    requires_credential = True
    config_schema = [
        {
            "key": "app_id",
            "label": "Application ID",
            "type": "text",
            "required": True,
            "help": "Your Adzuna app_id from developer.adzuna.com. Not a secret.",
            "placeholder": "a1b2c3d4",
        },
        {
            "key": "country",
            "label": "Country code",
            "type": "text",
            "required": False,
            "help": "Two-letter Adzuna country code. Defaults to 'in' (India).",
            "placeholder": "in",
        },
        {
            "key": "max_days_old",
            "label": "Max age (days)",
            "type": "number",
            "required": False,
            "help": "Only return postings newer than this many days.",
            "placeholder": "30",
        },
    ]

    def _country(self) -> str:
        return (self.config_value("country") or "in").lower()

    def _auth_params(self) -> dict[str, str]:
        return {"app_id": self.require_config("app_id"), "app_key": self.require_credential()}

    def _search_url(self, page: int = 1) -> str:
        return f"{API_BASE}/{self._country()}/search/{page}"

    def test_connection(self) -> SourceTestResult:
        try:
            params = self._auth_params() | {"results_per_page": 1}
            payload = http_get_json(self._search_url(), params=params)
        except SourceError as exc:
            return SourceTestResult(ok=False, message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return SourceTestResult(ok=False, message=f"{type(exc).__name__}: {exc}")
        return SourceTestResult(
            ok=True,
            message=f"Adzuna '{self._country()}' reachable.",
            details={"count": payload.get("count") if isinstance(payload, dict) else None},
        )

    def search(self, query: SourceQuery) -> list[RawJob]:
        limit = self._limit(query, ceiling=50)
        params: dict[str, Any] = self._auth_params() | {"results_per_page": limit}
        if query.keyword_text():
            params["what"] = query.keyword_text()
        if query.primary_location():
            params["where"] = query.primary_location()
        if query.remote_only:
            # Adzuna has no remote flag; the keyword is the documented workaround.
            params["what_or"] = f"{query.keyword_text()} remote".strip()
        if self.config_value("max_days_old"):
            params["max_days_old"] = self.config_value("max_days_old")
        if query.employment_types:
            if "full_time" in query.employment_types:
                params["full_time"] = 1
            elif "part_time" in query.employment_types:
                params["part_time"] = 1
            elif "contract" in query.employment_types:
                params["contract"] = 1

        payload = http_get_json(self._search_url(), params=params)
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return [self._to_raw_job(entry) for entry in results if isinstance(entry, dict)][:limit]

    def _to_raw_job(self, entry: dict) -> RawJob:
        currency = _COUNTRY_CURRENCY.get(self._country(), "INR")
        description = sanitize_description(entry.get("description"))
        location = str((entry.get("location") or {}).get("display_name") or "").strip()

        salary_min, salary_max = salary_from_numbers(
            entry.get("salary_min"), entry.get("salary_max"), currency=currency
        )
        salary_raw = ""
        if entry.get("salary_min") or entry.get("salary_max"):
            salary_raw = f"{entry.get('salary_min') or ''}-{entry.get('salary_max') or ''} {currency}".strip()

        exp_min, exp_max = parse_experience(description)
        title = str(entry.get("title") or "").strip()
        url = str(entry.get("redirect_url") or "")

        # Adzuna exposes contract_time (full/part) and contract_type (permanent
        # vs contract); contract_type is the more specific of the two.
        employment = entry.get("contract_type") or entry.get("contract_time")

        return RawJob(
            external_id=str(entry.get("id") or url),
            title=title,
            company=str((entry.get("company") or {}).get("display_name") or "").strip(),
            location=location,
            is_remote=is_remote_text(location, title, description[:2000]),
            url=url,
            apply_url=url,
            description=description,
            salary_min_lpa=salary_min,
            salary_max_lpa=salary_max,
            salary_raw=salary_raw,
            currency=currency,
            employment_type=normalize_employment_type(employment),
            industry=str((entry.get("category") or {}).get("label") or "").strip(),
            experience_min_years=exp_min,
            experience_max_years=exp_max,
            posted_at=parse_iso_datetime(entry.get("created")),
            raw=entry,
        )

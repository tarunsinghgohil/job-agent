"""Job source adapter contract, registry, and untrusted-input sanitization.

A "source" is configuration, never code: the dashboard picks an
``adapter_type``, fills in the fields described by that adapter's
``config_schema``, and optionally stores one credential. Everything the API
layer needs to render that UI comes from :func:`list_adapters`, so adding a
provider means adding one module here and nothing else.
"""
from __future__ import annotations

import html
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

import httpx

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10.0
MAX_DESCRIPTION_CHARS = 20_000

USER_AGENT = "job-agent/2.0 (+https://github.com/job-agent)"


class SourceError(RuntimeError):
    """Raised when an adapter cannot complete a request."""


class UnknownAdapterError(SourceError):
    """Raised when an adapter_type has no registered implementation."""


# ---------------------------------------------------------------------------
# Transfer objects
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class RawJob:
    """One posting as an adapter saw it, already normalized to our units.

    Salary is always LPA and experience always years, so downstream code never
    has to know which provider a job came from.
    """

    external_id: str
    title: str
    company: str
    location: str = ""
    is_remote: bool = False
    url: str = ""
    apply_url: str = ""
    description: str = ""
    salary_min_lpa: float | None = None
    salary_max_lpa: float | None = None
    salary_raw: str = ""
    currency: str = "INR"
    employment_type: str = "full_time"
    industry: str = ""
    experience_min_years: float | None = None
    experience_max_years: float | None = None
    posted_at: datetime | None = None
    # Provider's last-modified time; distinct from the original posting date.
    source_updated_at: datetime | None = None
    raw: dict = field(default_factory=dict)


@dataclass(slots=True)
class SourceQuery:
    """Provider-agnostic search intent built from user preferences."""

    keywords: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remote_only: bool = False
    min_salary_lpa: float | None = None
    employment_types: list[str] = field(default_factory=list)
    limit: int = 50

    def primary_keyword(self) -> str:
        return self.keywords[0] if self.keywords else ""

    def keyword_text(self) -> str:
        return " ".join(k.strip() for k in self.keywords if k and k.strip())

    def primary_location(self) -> str:
        return self.locations[0] if self.locations else ""


@dataclass(slots=True)
class SourceTestResult:
    ok: bool
    message: str
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Untrusted input handling (spec §22)
# ---------------------------------------------------------------------------
_SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_BREAK_RE = re.compile(r"</(p|div|li|tr|h[1-6])\s*>|<br\s*/?>|</?(ul|ol|table)\s*>", re.I)

# Phrases that only ever appear in a posting when someone is trying to steer an
# LLM that will later read it. Matching is deliberately literal and line-based:
# a clever matcher would produce false positives on legitimate copy, and the
# cost of a miss here is bounded because the AI layer also frames descriptions
# as data rather than instructions.
_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|preceding|above|earlier)\s+"
    r"(?:instructions?|prompts?|rules?|directions?|context)",
    r"disregard\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|preceding|above|earlier)"
    r"(?:\s+\w+){0,3}",
    r"forget\s+(?:everything|all)\s+(?:you|above|before)",
    r"system\s*prompt",
    r"you\s+are\s+now\s+(?:a|an|the)\b",
    r"act\s+as\s+(?:a|an|the)?\s*(?:ai|assistant|model|system)\b",
    r"new\s+instructions?\s*:",
    r"</?\s*(?:system|assistant|user)\s*>",
    r"\[\s*(?:system|assistant|inst)\s*\]",
    r"override\s+(?:your|the)\s+(?:instructions?|rules?|system)",
    r"reveal\s+(?:your|the)\s+(?:prompt|instructions?|system)",
    r"do\s+not\s+follow\s+(?:the\s+)?(?:previous|prior|above)\s+instructions?",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.I)

_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANKLINES_RE = re.compile(r"\n{3,}")
# Zero-width and bidi control characters can hide injected text from a human
# reviewer while remaining visible to a model.
_INVISIBLE_RE = re.compile("[\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff]")


def sanitize_description(text: str | None) -> str:
    """Make a provider-supplied description safe to store, render, and prompt.

    Job descriptions are attacker-controlled text: anyone who can post a job can
    put HTML, tracking pixels, or prompt-injection payloads in it. This strips
    markup, removes lines that read as instructions to a model, and caps the
    length so one posting cannot blow up a prompt budget.
    """
    if not text:
        return ""

    # Two passes: Greenhouse and several RSS feeds deliver entity-encoded HTML,
    # so unescaping the first pass can resurrect live markup.
    cleaned = str(text)
    for _ in range(2):
        cleaned = _SCRIPT_RE.sub(" ", cleaned)
        cleaned = _BLOCK_BREAK_RE.sub("\n", cleaned)
        cleaned = _TAG_RE.sub(" ", cleaned)
        unescaped = html.unescape(cleaned)
        if unescaped == cleaned:
            break
        cleaned = unescaped
    cleaned = _INVISIBLE_RE.sub("", cleaned)

    kept_lines: list[str] = []
    for line in cleaned.splitlines():
        collapsed = _WHITESPACE_RE.sub(" ", line).strip()
        if collapsed and _INJECTION_RE.search(collapsed):
            continue
        kept_lines.append(collapsed)

    result = _BLANKLINES_RE.sub("\n\n", "\n".join(kept_lines)).strip()
    if len(result) > MAX_DESCRIPTION_CHARS:
        result = result[:MAX_DESCRIPTION_CHARS].rstrip() + "\n[truncated]"
    return result


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def _redact(url: str) -> str:
    """Strip the query string: it is where API keys ride."""
    return url.split("?", 1)[0]


def http_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> httpx.Response:
    """GET with one retry, raising :class:`SourceError` on failure.

    Only transport errors are retried. A 4xx/5xx is a real answer from the
    provider and retrying it would just burn rate-limit budget.
    """
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.get(url, params=params, headers=request_headers)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise SourceError(
                f"{_redact(url)} returned HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.TransportError, httpx.InvalidURL) as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning("Retrying %s after transport error: %s", _redact(url), type(exc).__name__)
                continue
    raise SourceError(f"{_redact(url)} unreachable: {type(last_exc).__name__}") from last_exc


def http_get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> Any:
    response = http_get(url, params=params, headers=headers, timeout=timeout)
    try:
        return response.json()
    except ValueError as exc:
        raise SourceError(f"{_redact(url)} returned a non-JSON body") from exc


_EMPLOYMENT_TYPE_ALIASES = {
    "full_time": "full_time", "fulltime": "full_time", "full time": "full_time",
    "permanent": "full_time", "regular": "full_time", "salaried": "full_time",
    "part_time": "part_time", "parttime": "part_time", "part time": "part_time",
    "contract": "contract", "contractor": "contract", "contract_time": "contract",
    "fixed term": "contract", "fixed_term": "contract", "b2b": "contract",
    "temporary": "temporary", "temp": "temporary", "seasonal": "temporary",
    "internship": "internship", "intern": "internship", "trainee": "internship",
    "apprenticeship": "internship", "apprentice": "internship",
    "freelance": "freelance", "freelancer": "freelance",
}


_CURRENCY_GLYPH_RE = re.compile(r"[$€£₹¥]")


def strip_currency_symbols(text: str | None) -> str:
    """Drop currency glyphs from a free-text salary.

    ``parse_salary`` recognises ``120,000 - 150,000`` but not
    ``$120,000 - $150,000``: the glyph sits between the dash and the second
    number and breaks the range match, so the parser falls back to the single
    leading figure. Removing the glyph here keeps all salary logic in
    ``normalize`` while letting it see the range.
    """
    if not text:
        return ""
    return re.sub(r"\s+", " ", _CURRENCY_GLYPH_RE.sub(" ", str(text))).strip()


def normalize_employment_type(value: str | None, default: str = "full_time") -> str:
    """Fold a provider's employment-type vocabulary onto ours.

    Providers spell the same concept as ``Full-time``, ``FULL_TIME``,
    ``fullTime`` and ``permanent``; the matching engine compares this field
    against user preferences, so it has to be one closed set of values.
    """
    if not value:
        return default
    key = re.sub(r"[^a-z]+", " ", str(value).lower()).strip()
    if not key:
        return default
    if key in _EMPLOYMENT_TYPE_ALIASES:
        return _EMPLOYMENT_TYPE_ALIASES[key]
    collapsed = key.replace(" ", "_")
    if collapsed in _EMPLOYMENT_TYPE_ALIASES:
        return _EMPLOYMENT_TYPE_ALIASES[collapsed]
    for alias, canonical in _EMPLOYMENT_TYPE_ALIASES.items():
        if alias in key:
            return canonical
    return default


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Best-effort ISO-8601 parse; providers disagree on the trailing ``Z``."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Adapter contract
# ---------------------------------------------------------------------------
class JobSourceAdapter(ABC):
    """Base class every provider implements.

    Subclasses declare their configuration as data (``config_schema``) so the
    dashboard can render a form for a provider it has never heard of.
    """

    adapter_type: ClassVar[str]
    display_name: ClassVar[str]
    requires_credential: ClassVar[bool] = False
    config_schema: ClassVar[list[dict]] = []
    # True for providers with a real search endpoint, which is what makes
    # running several query variations worthwhile. Board adapters return a
    # company's whole board, so they run once per discovery pass instead.
    supports_search: ClassVar[bool] = False

    def __init__(self, config: dict | None = None, credential: str | None = None) -> None:
        self.config: dict = dict(config or {})
        self._credential = credential

    @property
    def credential(self) -> str | None:
        """Accessor kept explicit so grepping for credential use is easy."""
        return self._credential

    def config_value(self, key: str, default: str = "") -> str:
        value = self.config.get(key, default)
        return str(value).strip() if value is not None else default

    def require_config(self, key: str) -> str:
        value = self.config_value(key)
        if not value:
            raise SourceError(f"{self.display_name} requires the '{key}' setting.")
        return value

    def require_credential(self) -> str:
        if not self._credential:
            raise SourceError(f"{self.display_name} requires a stored credential.")
        return self._credential

    @abstractmethod
    def test_connection(self) -> SourceTestResult:
        """Cheapest possible call that proves config + credential work."""

    @abstractmethod
    def search(self, query: SourceQuery) -> list[RawJob]:
        """Return postings matching ``query``; never raise for 'no results'."""

    def fetch_job(self, external_id: str) -> RawJob | None:
        """Re-fetch one posting. Providers without a detail endpoint return None."""
        return None

    def health(self) -> SourceTestResult:
        """Health probe; by default the same call as ``test_connection``."""
        return self.test_connection()

    def search_many(self, queries: list[SourceQuery]) -> list[RawJob] | None:
        """Answer several query variations at once, or return None.

        Providers with strict request limits override this to make a single
        request and filter locally, instead of one request per variation.
        The default (None) makes discovery run each query separately.
        """
        return None

    def query_signature(self, query: SourceQuery) -> tuple:
        """What makes two queries different *to this provider*.

        Discovery skips a query whose signature it already ran, so a provider
        that ignores location is not asked the same question once per city.
        """
        return (
            query.keyword_text().lower(),
            query.primary_location().lower(),
            bool(query.remote_only),
        )

    # -- shared helpers -----------------------------------------------------
    def _limit(self, query: SourceQuery, ceiling: int = 200) -> int:
        return max(1, min(int(query.limit or 50), ceiling))

    def _matches_keywords(self, query: SourceQuery, *fields: str) -> bool:
        """Client-side keyword filter for providers with no search parameter.

        Board APIs (Greenhouse, Lever, Ashby, RSS) return a company's whole
        board, so filtering has to happen here or every job on the board would
        be ingested.
        """
        if not query.keywords:
            return True
        blob = " ".join(f or "" for f in fields).lower()
        return any(kw.lower().strip() in blob for kw in query.keywords if kw and kw.strip())


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, type[JobSourceAdapter]] = {}


def register_adapter(cls: type[JobSourceAdapter]) -> type[JobSourceAdapter]:
    """Class decorator that makes an adapter discoverable by ``adapter_type``."""
    adapter_type = getattr(cls, "adapter_type", "")
    if not adapter_type:
        raise ValueError(f"{cls.__name__} must define a non-empty adapter_type.")
    _REGISTRY[adapter_type] = cls
    return cls


def get_adapter_class(adapter_type: str) -> type[JobSourceAdapter]:
    try:
        return _REGISTRY[str(adapter_type).strip().lower()]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise UnknownAdapterError(
            f"Unknown adapter type '{adapter_type}'. Registered adapters: {known}."
        ) from exc


def get_adapter(
    adapter_type: str,
    config: dict | None = None,
    credential: str | None = None,
) -> JobSourceAdapter:
    return get_adapter_class(adapter_type)(config or {}, credential)


def list_adapters() -> list[dict]:
    """Descriptors for the ``/sources/adapters`` endpoint."""
    return [
        {
            "adapter_type": cls.adapter_type,
            "display_name": cls.display_name,
            "requires_credential": cls.requires_credential,
            "config_schema": [dict(f) for f in cls.config_schema],
        }
        for _, cls in sorted(_REGISTRY.items())
    ]


def registered_adapter_types() -> list[str]:
    return sorted(_REGISTRY)


__all__ = [
    "HTTP_TIMEOUT_SECONDS",
    "MAX_DESCRIPTION_CHARS",
    "JobSourceAdapter",
    "RawJob",
    "SourceError",
    "SourceQuery",
    "SourceTestResult",
    "UnknownAdapterError",
    "get_adapter",
    "get_adapter_class",
    "http_get",
    "http_get_json",
    "list_adapters",
    "normalize_employment_type",
    "parse_iso_datetime",
    "register_adapter",
    "registered_adapter_types",
    "sanitize_description",
    "strip_currency_symbols",
]

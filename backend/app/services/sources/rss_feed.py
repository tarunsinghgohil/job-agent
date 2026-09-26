"""Generic RSS 2.0 / Atom job-feed adapter.

Parsed with the stdlib ``xml.etree.ElementTree`` rather than a third-party
feed library: the subset of RSS that job boards emit is small, and one fewer
dependency is one fewer supply-chain risk on untrusted input.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from app.services.normalize import is_remote_text, parse_experience, parse_salary
from app.services.sources.base import (
    JobSourceAdapter,
    RawJob,
    SourceError,
    SourceQuery,
    SourceTestResult,
    http_get,
    normalize_employment_type,
    parse_iso_datetime,
    register_adapter,
    sanitize_description,
)

ATOM_NS = "http://www.w3.org/2005/Atom"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
DC_NS = "http://purl.org/dc/elements/1.1/"

# "Senior Engineer at Acme" / "Acme: Senior Engineer" -- the two title shapes
# job feeds use when they have no dedicated company element.
_TITLE_AT_RE = re.compile(r"^(?P<title>.+?)\s+(?:at|@)\s+(?P<company>.+?)\s*$", re.I)
_TITLE_COLON_RE = re.compile(r"^(?P<company>[^:]{2,60}):\s*(?P<title>.+)$")


@register_adapter
class RssFeedAdapter(JobSourceAdapter):
    adapter_type = "rss"
    display_name = "RSS / Atom feed"
    requires_credential = False
    config_schema = [
        {
            "key": "feed_url",
            "label": "Feed URL",
            "type": "url",
            "required": True,
            "help": "An RSS 2.0 or Atom job feed. Must be https.",
            "placeholder": "https://example.com/jobs.rss",
        },
        {
            "key": "company_name",
            "label": "Company name",
            "type": "text",
            "required": False,
            "help": "Use when the feed is a single company's board and omits the employer.",
            "placeholder": "Acme Inc",
        },
        {
            "key": "default_location",
            "label": "Default location",
            "type": "text",
            "required": False,
            "help": "Applied when a feed item carries no location.",
            "placeholder": "Bengaluru, India",
        },
    ]

    def _feed_url(self) -> str:
        url = self.require_config("feed_url")
        if not url.lower().startswith(("http://", "https://")):
            raise SourceError("Feed URL must be an http(s) URL.")
        return url

    def _fetch_root(self) -> ET.Element:
        response = http_get(self._feed_url(), headers={"Accept": "application/rss+xml, application/xml, text/xml, */*"})
        try:
            return ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise SourceError(f"Feed is not well-formed XML: {exc}") from exc

    def test_connection(self) -> SourceTestResult:
        try:
            root = self._fetch_root()
        except SourceError as exc:
            return SourceTestResult(ok=False, message=str(exc))
        items = self._items(root)
        if not items:
            return SourceTestResult(
                ok=False, message="Feed parsed but contained no <item> or <entry> elements."
            )
        return SourceTestResult(
            ok=True, message="Feed reachable and parseable.", details={"items": len(items)}
        )

    def search(self, query: SourceQuery) -> list[RawJob]:
        root = self._fetch_root()
        jobs: list[RawJob] = []
        limit = self._limit(query)
        for item in self._items(root):
            raw_job = self._to_raw_job(item)
            if not raw_job.title:
                continue
            if not self._matches_keywords(query, raw_job.title, raw_job.description, raw_job.company):
                continue
            if query.remote_only and not raw_job.is_remote:
                continue
            jobs.append(raw_job)
            if len(jobs) >= limit:
                break
        return jobs

    # -- parsing ------------------------------------------------------------
    @staticmethod
    def _items(root: ET.Element) -> list[ET.Element]:
        items = root.findall(".//item")
        if items:
            return items
        return root.findall(f".//{{{ATOM_NS}}}entry")

    @staticmethod
    def _text(item: ET.Element, *paths: str) -> str:
        for path in paths:
            node = item.find(path)
            if node is not None:
                value = "".join(node.itertext()) if len(node) else (node.text or "")
                if value and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _link(item: ET.Element) -> str:
        link = item.find("link")
        if link is not None and (link.text or "").strip():
            return (link.text or "").strip()
        for node in item.findall(f"{{{ATOM_NS}}}link"):
            rel = node.get("rel", "alternate")
            if rel == "alternate" and node.get("href"):
                return node.get("href", "").strip()
        node = item.find(f"{{{ATOM_NS}}}link")
        return node.get("href", "").strip() if node is not None else ""

    def _to_raw_job(self, item: ET.Element) -> RawJob:
        raw_title = self._text(item, "title", f"{{{ATOM_NS}}}title")
        description = sanitize_description(
            self._text(
                item,
                f"{{{CONTENT_NS}}}encoded",
                "description",
                f"{{{ATOM_NS}}}content",
                f"{{{ATOM_NS}}}summary",
            )
        )
        url = self._link(item)

        company = (
            self.config_value("company_name")
            or self._text(item, "company", f"{{{DC_NS}}}creator", "author/name")
        )
        title = raw_title
        if not company:
            title, company = _split_title_and_company(raw_title)

        location = self._text(item, "location", "job_location") or self.config_value(
            "default_location"
        )
        employment_type = normalize_employment_type(self._text(item, "job_type", "type"))

        salary_raw = self._text(item, "salary")[:200]
        salary_min, salary_max = parse_salary(salary_raw) if salary_raw else (None, None)
        exp_min, exp_max = parse_experience(description)

        guid = self._text(item, "guid", f"{{{ATOM_NS}}}id") or url

        return RawJob(
            external_id=guid,
            title=title.strip(),
            company=company.strip(),
            location=location.strip(),
            is_remote=is_remote_text(location, title, description[:2000]),
            url=url,
            apply_url=url,
            description=description,
            salary_min_lpa=salary_min,
            salary_max_lpa=salary_max,
            salary_raw=salary_raw,
            currency="INR",
            employment_type=employment_type,
            industry=self._text(item, "category", f"{{{ATOM_NS}}}category"),
            experience_min_years=exp_min,
            experience_max_years=exp_max,
            posted_at=_parse_feed_date(
                self._text(item, "pubDate", f"{{{DC_NS}}}date", f"{{{ATOM_NS}}}updated",
                           f"{{{ATOM_NS}}}published")
            ),
            raw={"title": raw_title, "link": url, "guid": guid},
        )


def _split_title_and_company(raw_title: str) -> tuple[str, str]:
    """Recover the employer from a combined feed title, or give up cleanly."""
    if not raw_title:
        return "", ""
    match = _TITLE_AT_RE.match(raw_title)
    if match:
        return match.group("title"), match.group("company")
    match = _TITLE_COLON_RE.match(raw_title)
    if match:
        return match.group("title"), match.group("company")
    return raw_title, ""


def _parse_feed_date(value: str) -> datetime | None:
    """RSS uses RFC 822 dates, Atom uses ISO 8601."""
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    return parse_iso_datetime(value)

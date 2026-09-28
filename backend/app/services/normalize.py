"""Text, salary, location, and experience normalization.

Shared by the source adapters (on ingest), the deduplicator, and the matching
engine, so that all three agree on what a "company name" or "14 LPA" is.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

# Suffixes stripped when canonicalizing a company name for dedupe.
_COMPANY_SUFFIXES = {
    "inc", "inc.", "llc", "ltd", "ltd.", "limited", "pvt", "pvt.", "private",
    "plc", "corp", "corp.", "corporation", "co", "co.", "company", "gmbh",
    "llp", "technologies", "technology", "tech", "solutions", "systems",
    "labs", "software", "services", "consulting", "group", "holdings",
    "india", "global", "international",
}

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "ref", "referrer", "source", "src", "trk", "trackingid",
}

_REMOTE_TOKENS = ("remote", "work from home", "wfh", "anywhere", "distributed", "telecommute")

_WORD_RE = re.compile(r"[a-z0-9+#.]+")


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def norm_text(text: str | None) -> str:
    """Lowercase, strip accents, collapse punctuation to spaces.

    Keeps ``+``, ``#`` and ``.`` so that C++, C# and Node.js survive.
    """
    if not text:
        return ""
    lowered = strip_accents(str(text)).lower()
    cleaned = re.sub(r"[^a-z0-9+#.\s]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def tokens(text: str | None) -> set[str]:
    return set(_WORD_RE.findall(norm_text(text)))


def slugify(text: str | None) -> str:
    base = norm_text(text).replace(".", "").replace("+", "plus").replace("#", "sharp")
    return re.sub(r"\s+", "-", base).strip("-")


def normalize_company(name: str | None) -> str:
    """Canonical company key: 'Acme Technologies Pvt. Ltd.' -> 'acme'."""
    words = norm_text(name).split()
    kept = [w for w in words if w.strip(".") not in _COMPANY_SUFFIXES]
    return " ".join(kept or words).strip()


def canonical_url(url: str | None) -> str:
    """Drop scheme case, tracking params, fragments and trailing slashes."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    if not parts.netloc:
        return url.strip()

    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    query_pairs = []
    for pair in parts.query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].lower()
        if key not in _TRACKING_PARAMS:
            query_pairs.append(pair)

    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", netloc, path, "&".join(sorted(query_pairs)), ""))


def is_remote_text(*values: str | None) -> bool:
    blob = norm_text(" ".join(v or "" for v in values))
    return any(token in blob for token in _REMOTE_TOKENS)


def normalize_location(location: str | None) -> str:
    loc = norm_text(location)
    loc = re.sub(r"\b(india|in)\b", "", loc).strip()
    return re.sub(r"\s+", " ", loc).strip(" ,-")


def text_hash(text: str | None) -> str:
    return hashlib.sha256(norm_text(text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Salary
# ---------------------------------------------------------------------------
# Indian salaries are quoted in lakhs per annum (LPA). Everything is converted
# to LPA so a single numeric comparison works across sources.
_LPA_PER_USD_YEAR = 1.0 / 120_000.0 * 100.0  # ~1 lakh INR per 1200 USD/yr at 83 INR/USD

_CURRENCY_TO_LPA_YEARLY = {
    "INR": 1.0 / 100_000.0,
    "USD": 83.0 / 100_000.0,
    "EUR": 90.0 / 100_000.0,
    "GBP": 105.0 / 100_000.0,
}

_NUM = r"(\d+(?:[.,]\d+)?)"
_SALARY_RANGE_RE = re.compile(
    rf"{_NUM}\s*(?:-|to|–|—)\s*{_NUM}\s*(lpa|lakhs?|lacs?|l|k|cr|crores?)?", re.I
)
_SALARY_SINGLE_RE = re.compile(rf"{_NUM}\s*(lpa|lakhs?|lacs?|k|cr|crores?)", re.I)


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _unit_to_lpa(value: float, unit: str | None, currency: str) -> float | None:
    unit = (unit or "").lower()
    if unit in ("lpa", "lakh", "lakhs", "lac", "lacs", "l"):
        return value
    if unit in ("cr", "crore", "crores"):
        return value * 100.0
    if unit == "k":
        # 'k' means thousands of the quoted currency, per year.
        return _absolute_to_lpa(value * 1_000, currency)
    return None


def _absolute_to_lpa(amount: float, currency: str) -> float | None:
    rate = _CURRENCY_TO_LPA_YEARLY.get((currency or "INR").upper())
    if rate is None:
        return None
    return round(amount * rate, 2)


def parse_salary(
    raw: str | None,
    *,
    currency: str = "INR",
    period: str = "year",
) -> tuple[float | None, float | None]:
    """Parse a free-text salary into ``(min_lpa, max_lpa)``.

    Returns ``(None, None)`` when nothing reliable can be extracted -- an
    unparseable salary must never be silently treated as zero, because the
    minimum-salary hard filter would then reject every such job.
    """
    if not raw:
        return (None, None)

    text = str(raw).strip()
    if not text:
        return (None, None)

    multiplier = {"year": 1.0, "annual": 1.0, "month": 12.0, "hour": 2080.0, "day": 260.0}.get(
        (period or "year").lower(), 1.0
    )

    match = _SALARY_RANGE_RE.search(text)
    if match:
        low, high, unit = _to_float(match.group(1)), _to_float(match.group(2)), match.group(3)
        if low is not None and high is not None:
            lo = _unit_to_lpa(low, unit, currency)
            hi = _unit_to_lpa(high, unit, currency)
            if lo is None or hi is None:
                lo = _absolute_to_lpa(low * multiplier, currency)
                hi = _absolute_to_lpa(high * multiplier, currency)
            if lo is not None and hi is not None and hi >= lo:
                return (round(lo, 2), round(hi, 2))

    match = _SALARY_SINGLE_RE.search(text)
    if match:
        value, unit = _to_float(match.group(1)), match.group(2)
        if value is not None:
            lpa = _unit_to_lpa(value, unit, currency)
            if lpa is not None:
                return (round(lpa, 2), round(lpa, 2))

    # Bare number: only trust it when it is large enough to be an actual salary.
    bare = re.search(r"(\d[\d,]{4,})", text)
    if bare:
        value = _to_float(bare.group(1))
        if value is not None:
            lpa = _absolute_to_lpa(value * multiplier, currency)
            if lpa is not None and lpa >= 0.5:
                return (round(lpa, 2), round(lpa, 2))

    return (None, None)


def salary_from_numbers(
    minimum: float | None,
    maximum: float | None,
    currency: str = "INR",
    period: str = "year",
) -> tuple[float | None, float | None]:
    """Convert numeric provider salary fields to LPA."""
    multiplier = {"year": 1.0, "month": 12.0, "hour": 2080.0, "day": 260.0}.get(
        (period or "year").lower(), 1.0
    )
    lo = _absolute_to_lpa(minimum * multiplier, currency) if minimum else None
    hi = _absolute_to_lpa(maximum * multiplier, currency) if maximum else None
    if lo is not None and hi is not None and hi < lo:
        lo, hi = hi, lo
    return (lo, hi)


# ---------------------------------------------------------------------------
# Experience
# ---------------------------------------------------------------------------
_EXP_RANGE_RE = re.compile(rf"{_NUM}\s*(?:-|to|–|—)\s*{_NUM}\s*\+?\s*(?:years?|yrs?)", re.I)
_EXP_MIN_RE = re.compile(rf"{_NUM}\s*\+\s*(?:years?|yrs?)", re.I)
_EXP_SINGLE_RE = re.compile(rf"(?:minimum|min|at least|over)?\s*{_NUM}\s*(?:years?|yrs?)", re.I)


def parse_experience(text: str | None) -> tuple[float | None, float | None]:
    """Extract ``(min_years, max_years)`` from a job description."""
    if not text:
        return (None, None)

    match = _EXP_RANGE_RE.search(text)
    if match:
        lo, hi = _to_float(match.group(1)), _to_float(match.group(2))
        if lo is not None and hi is not None and hi >= lo and hi <= 50:
            return (lo, hi)

    match = _EXP_MIN_RE.search(text)
    if match:
        lo = _to_float(match.group(1))
        if lo is not None and lo <= 50:
            return (lo, None)

    match = _EXP_SINGLE_RE.search(text)
    if match:
        lo = _to_float(match.group(1))
        if lo is not None and 0 < lo <= 50:
            return (lo, None)

    return (None, None)


# Addresses that are published for reasons other than receiving applications.
_NON_APPLICATION_MAILBOXES = {
    "support", "help", "info", "sales", "marketing", "press", "media",
    "privacy", "legal", "security", "abuse", "billing", "accounts",
    "noreply", "no-reply", "donotreply", "webmaster", "postmaster",
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Wording that signals the address on this line is where applications go.
_APPLY_CONTEXT = (
    "apply", "application", "send your", "send us", "email your", "submit your",
    "resume to", "cv to", "reach out to", "get in touch", "write to",
)


def extract_application_email(text: str | None) -> str:
    """Find the address a posting asks applicants to write to.

    Returns "" when nothing is confidently an application mailbox. Being
    conservative matters here: this address is what an automated submission
    would be sent to, and mailing the wrong inbox is worse than not mailing.
    """
    if not text:
        return ""

    candidates: list[tuple[int, str]] = []
    for line in str(text).splitlines():
        found = _EMAIL_RE.findall(line)
        if not found:
            continue
        lowered = line.lower()
        has_context = any(marker in lowered for marker in _APPLY_CONTEXT)
        for address in found:
            mailbox = address.split("@", 1)[0].lower()
            # A mailbox literally named for applications is trusted on its own.
            is_apply_mailbox = any(
                token in mailbox for token in ("job", "career", "hiring", "recruit", "apply", "hr", "talent")
            )
            if mailbox in _NON_APPLICATION_MAILBOXES and not is_apply_mailbox:
                continue
            if is_apply_mailbox:
                candidates.append((0, address))
            elif has_context:
                candidates.append((1, address))

    if not candidates:
        return ""
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


# ---------------------------------------------------------------------------
# Application link quality
# ---------------------------------------------------------------------------
# Hosts of applicant-tracking systems. A link here is the employer's own
# application form, which is what an applicant actually wants.
_ATS_HOSTS: dict[str, str] = {
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "ashbyhq.com": "Ashby",
    "myworkdayjobs.com": "Workday",
    "myworkdaysite.com": "Workday",
    "workday.com": "Workday",
    "smartrecruiters.com": "SmartRecruiters",
    "workable.com": "Workable",
    "bamboohr.com": "BambooHR",
    "recruitee.com": "Recruitee",
    "keka.com": "Keka",
    "darwinbox.in": "Darwinbox",
    "darwinbox.com": "Darwinbox",
    "freshteam.com": "Freshteam",
    "zohorecruit.com": "Zoho Recruit",
    "zohorecruit.in": "Zoho Recruit",
    "icims.com": "iCIMS",
    "jobvite.com": "Jobvite",
    "teamtailor.com": "Teamtailor",
    "breezy.hr": "Breezy HR",
    "personio.de": "Personio",
    "personio.com": "Personio",
    "rippling.com": "Rippling",
    "taleo.net": "Taleo",
    "successfactors.com": "SuccessFactors",
    "oraclecloud.com": "Oracle Recruiting",
    "jazzhr.com": "JazzHR",
    "applytojob.com": "JazzHR",
    "turbohire.co": "TurboHire",
    "superset.com": "Superset",
}

# Job boards and aggregators. Useful for discovery, but the link usually
# leads to a copy of the posting rather than the employer's form.
_AGGREGATOR_HOSTS: dict[str, str] = {
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "indeed.co.in": "Indeed",
    "naukri.com": "Naukri",
    "glassdoor.com": "Glassdoor",
    "glassdoor.co.in": "Glassdoor",
    "adzuna.com": "Adzuna",
    "adzuna.in": "Adzuna",
    "remotive.com": "Remotive",
    "wellfound.com": "Wellfound",
    "angel.co": "Wellfound",
    "instahyre.com": "Instahyre",
    "foundit.in": "Foundit",
    "monsterindia.com": "Foundit",
    "cutshort.io": "Cutshort",
    "iimjobs.com": "iimjobs",
    "hirist.tech": "Hirist",
    "hirist.com": "Hirist",
    "weworkremotely.com": "We Work Remotely",
    "remoteok.com": "Remote OK",
    "remoteok.io": "Remote OK",
    "shine.com": "Shine",
    "timesjobs.com": "TimesJobs",
    "apna.co": "Apna",
    "simplyhired.com": "SimplyHired",
    "ziprecruiter.com": "ZipRecruiter",
    "jooble.org": "Jooble",
    "talent.com": "Talent.com",
    "google.com": "Google Jobs",
}

# Ordered from most to least useful to an applicant.
APPLY_LINK_QUALITY: dict[str, float] = {
    "ats": 1.0,
    "company": 0.9,
    "email": 0.8,
    "aggregator": 0.5,
    "none": 0.2,
}


def _host_of(url: str) -> str:
    try:
        host = urlsplit(url.strip()).netloc.lower()
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _match_host(host: str, table: dict[str, str]) -> str | None:
    for suffix, label in table.items():
        if host == suffix or host.endswith("." + suffix):
            return label
    return None


def classify_apply_url(url: str | None) -> tuple[str, str]:
    """Return ``(link_type, label)`` for an application link.

    ``link_type`` is one of ``ats``, ``company``, ``aggregator`` or ``none``.
    Anything that is neither a known ATS nor a known aggregator is treated as
    the employer's own site, which is the common case for career pages.
    """
    if not url or not str(url).strip():
        return ("none", "")
    host = _host_of(str(url))
    if not host:
        return ("none", "")
    ats = _match_host(host, _ATS_HOSTS)
    if ats:
        return ("ats", ats)
    aggregator = _match_host(host, _AGGREGATOR_HOSTS)
    if aggregator:
        return ("aggregator", aggregator)
    return ("company", host)


def apply_link_quality(url: str | None) -> float:
    return APPLY_LINK_QUALITY[classify_apply_url(url)[0]]


def best_apply_link(*urls: str | None) -> tuple[str, str, str]:
    """Pick the most direct link among candidates: ``(url, link_type, label)``.

    Ties keep the earliest candidate, so callers pass the preferred field first.
    """
    best: tuple[float, str, str, str] = (-1.0, "", "none", "")
    for url in urls:
        if not url or not str(url).strip():
            continue
        link_type, label = classify_apply_url(url)
        quality = APPLY_LINK_QUALITY[link_type]
        if quality > best[0]:
            best = (quality, str(url).strip(), link_type, label)
    return (best[1], best[2], best[3])


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def title_similarity(a: str | None, b: str | None) -> float:
    return jaccard(tokens(a), tokens(b))

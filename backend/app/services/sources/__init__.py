"""Job source adapters.

Importing this package imports every adapter module, which is what populates
the registry. Anything that resolves an adapter by type must import from here
(or from a module that does) or the registry will look empty.
"""
from __future__ import annotations

from app.services.sources.base import (
    HTTP_TIMEOUT_SECONDS,
    MAX_DESCRIPTION_CHARS,
    JobSourceAdapter,
    RawJob,
    SourceError,
    SourceQuery,
    SourceTestResult,
    UnknownAdapterError,
    get_adapter,
    get_adapter_class,
    list_adapters,
    normalize_employment_type,
    register_adapter,
    registered_adapter_types,
    sanitize_description,
    strip_currency_symbols,
)

# Imported for their registration side effect; order is irrelevant.
from app.services.sources.adzuna import AdzunaAdapter
from app.services.sources.ashby import AshbyAdapter
from app.services.sources.greenhouse import GreenhouseAdapter
from app.services.sources.lever import LeverAdapter
from app.services.sources.manual import ManualAdapter
from app.services.sources.remotive import RemotiveAdapter
from app.services.sources.rss_feed import RssFeedAdapter

__all__ = [
    "HTTP_TIMEOUT_SECONDS",
    "MAX_DESCRIPTION_CHARS",
    "AdzunaAdapter",
    "AshbyAdapter",
    "GreenhouseAdapter",
    "JobSourceAdapter",
    "LeverAdapter",
    "ManualAdapter",
    "RawJob",
    "RemotiveAdapter",
    "RssFeedAdapter",
    "SourceError",
    "SourceQuery",
    "SourceTestResult",
    "UnknownAdapterError",
    "get_adapter",
    "get_adapter_class",
    "list_adapters",
    "normalize_employment_type",
    "register_adapter",
    "registered_adapter_types",
    "sanitize_description",
    "strip_currency_symbols",
]

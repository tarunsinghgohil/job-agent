"""No-op adapter backing hand-entered jobs.

Manually added jobs still need a ``JobSource`` row so that dedupe, health
reporting, and the jobs list treat them like any other origin. This adapter
exists so nothing downstream has to special-case ``source_name == "manual"``.
"""
from __future__ import annotations

from app.services.sources.base import (
    JobSourceAdapter,
    RawJob,
    SourceQuery,
    SourceTestResult,
    register_adapter,
)


@register_adapter
class ManualAdapter(JobSourceAdapter):
    adapter_type = "manual"
    display_name = "Manual entry"
    requires_credential = False
    config_schema: list[dict] = []

    def test_connection(self) -> SourceTestResult:
        return SourceTestResult(
            ok=True,
            message="Manual entry needs no connection.",
            details={"adapter": self.adapter_type},
        )

    def search(self, query: SourceQuery) -> list[RawJob]:
        """Always empty: discovery never invents manual jobs, the user adds them."""
        return []

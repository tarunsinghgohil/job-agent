"""Structured JSON logging with secret redaction."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

# Anything resembling a credential is scrubbed before a line is emitted.
_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8})[A-Za-z0-9_\-]+"),
    re.compile(r"(bot\d+:)[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)(authorization\"?\s*[:=]\s*\"?(?:bearer\s+)?)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)(password\"?\s*[:=]\s*\"?)[^\s\",}]+"),
    re.compile(r"(https://hooks\.slack\.com/services/)\S+"),
]


def scrub(message: str) -> str:
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(r"\1***redacted***", message)
    return message


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": scrub(record.getMessage()),
        }
        for attr in ("request_id", "user_id", "path", "method", "status_code", "duration_ms"):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value
        if record.exc_info:
            payload["exception"] = scrub(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


class PlainFormatter(logging.Formatter):
    """Human-readable output for local development."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{record.levelname:<8} {record.name}: {scrub(record.getMessage())}"
        if record.exc_info:
            base = f"{base}\n{scrub(self.formatException(record.exc_info))}"
        return base


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter() if settings.is_production else PlainFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    # These are noisy at INFO and say nothing the access log does not.
    for noisy in ("httpx", "httpcore", "openai", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

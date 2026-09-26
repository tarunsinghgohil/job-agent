"""Notification channel contract and registry.

Adapters are registered rather than hard-coded so that the Settings UI can be
generated from ``list_channels()`` and a new channel becomes a single new
module instead of an edit to the dispatch service.

Two invariants every adapter must uphold:
  * a misconfigured channel returns ``DeliveryResult(ok=False, ...)`` -- it never
    raises, because one broken channel must not abort a dispatch fan-out;
  * no credential, webhook URL or bot token ever reaches a result, a log line or
    an exception message (use :func:`scrub`).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.core.security import mask_secret

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10.0


class UnknownChannelError(LookupError):
    """Raised when a channel_type has no registered adapter."""


@dataclass(slots=True)
class NotificationMessage:
    subject: str
    body: str
    event_type: str
    payload: dict = field(default_factory=dict)
    url: str | None = None


@dataclass(slots=True)
class DeliveryResult:
    ok: bool
    message: str
    details: dict = field(default_factory=dict)


def scrub(text: str, *secrets: str | None) -> str:
    """Replace any credential that leaked into an error string with a mask.

    HTTP libraries habitually echo the full request URL back in their exception
    messages, which for Telegram and Slack embeds the token itself.
    """
    cleaned = text or ""
    for secret in secrets:
        if secret and len(secret) >= 6:
            cleaned = cleaned.replace(secret, mask_secret(secret))
    return cleaned


def first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, "", {}, []) and not isinstance(value, str):
            return str(value)
    return ""


class NotificationAdapter(ABC):
    """Base class for every delivery channel."""

    channel_type: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    requires_credential: ClassVar[bool] = True
    config_schema: ClassVar[list[dict]] = []

    def __init__(self, config: dict | None = None, credential: str | None = None) -> None:
        self.config: dict = dict(config or {})
        self._credential = credential or ""

    @property
    def credential(self) -> str:
        return self._credential

    def get(self, key: str, default: str = "") -> str:
        value = self.config.get(key, default)
        if value is None:
            return default
        return str(value).strip() if isinstance(value, str) else value

    def scrub(self, text: str) -> str:
        return scrub(text, self._credential)

    def missing_config(self) -> list[str]:
        """Names of required schema keys that the stored config does not supply."""
        missing = [
            spec["key"]
            for spec in self.config_schema
            if spec.get("required") and not str(self.config.get(spec["key"], "") or "").strip()
        ]
        if self.requires_credential and not self._credential:
            missing.append("credential")
        return missing

    def not_configured(self, missing: list[str]) -> DeliveryResult:
        return DeliveryResult(
            ok=False,
            message=f"{self.display_name} is not configured: missing {', '.join(missing)}.",
            details={"missing": missing, "configured": False},
        )

    @abstractmethod
    def send(self, message: NotificationMessage) -> DeliveryResult:
        """Deliver one message. Must not raise."""

    @abstractmethod
    def test(self) -> DeliveryResult:
        """Verify the configuration end to end. Must not raise."""

    def describe(self) -> dict:
        return {
            "channel_type": self.channel_type,
            "display_name": self.display_name,
            "requires_credential": self.requires_credential,
            "config_schema": list(self.config_schema),
        }


_REGISTRY: dict[str, type[NotificationAdapter]] = {}
_builtins_loaded = False


def register_channel(adapter_cls: type[NotificationAdapter]) -> type[NotificationAdapter]:
    if not adapter_cls.channel_type:
        raise ValueError("A notification adapter must declare a channel_type.")
    _REGISTRY[adapter_cls.channel_type] = adapter_cls
    return adapter_cls


def _load_builtins() -> None:
    """Import the shipped adapters on first use.

    Done lazily so adapter modules can import this one without a cycle.
    """
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True
    from app.services.notifications import (  # noqa: F401
        email_channel,
        slack_channel,
        telegram_channel,
        whatsapp_channel,
    )


def get_channel_adapter(
    channel_type: str, config: dict | None = None, credential: str | None = None
) -> NotificationAdapter:
    _load_builtins()
    try:
        adapter_cls = _REGISTRY[channel_type]
    except KeyError as exc:
        raise UnknownChannelError(f"No notification adapter registered for '{channel_type}'.") from exc
    return adapter_cls(config or {}, credential)


def list_channels() -> list[dict]:
    """Channel metadata for the Settings UI, including the config form schema."""
    _load_builtins()
    return [
        {
            "channel_type": cls.channel_type,
            "display_name": cls.display_name,
            "requires_credential": cls.requires_credential,
            "config_schema": list(cls.config_schema),
        }
        for cls in sorted(_REGISTRY.values(), key=lambda c: c.channel_type)
    ]


def registered_channel_types() -> list[str]:
    _load_builtins()
    return sorted(_REGISTRY)

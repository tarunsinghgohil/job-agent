"""Telegram bot channel.

The bot token is part of the request URL, and HTTP libraries echo that URL back
in their exception text, so every outbound string is run through
:meth:`scrub` before it can reach a log line, a result, or the database.
"""
from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.notifications.base import (
    HTTP_TIMEOUT_SECONDS,
    DeliveryResult,
    NotificationAdapter,
    NotificationMessage,
    register_channel,
    scrub,
)

API_BASE = "https://api.telegram.org"
MAX_TELEGRAM_CHARS = 4096


@register_channel
class TelegramChannel(NotificationAdapter):
    channel_type = "telegram"
    display_name = "Telegram"
    requires_credential = True
    config_schema = [
        {
            "key": "chat_id",
            "label": "Chat ID",
            "type": "text",
            "required": True,
            "help": "Numeric chat id from @userinfobot, or @channelname for a channel.",
        },
        {
            "key": "disable_preview",
            "label": "Disable link previews",
            "type": "boolean",
            "required": False,
            "help": "Keeps digests compact when they contain job links.",
        },
    ]

    @property
    def token(self) -> str:
        return self.credential or settings.telegram_bot_token or ""

    @property
    def chat_id(self) -> str:
        return str(self.config.get("chat_id") or "").strip()

    def scrub(self, text: str) -> str:
        return scrub(text, self.token)

    def missing_config(self) -> list[str]:
        missing: list[str] = []
        if not self.chat_id:
            missing.append("chat_id")
        if not self.token:
            missing.append("bot_token")
        return missing

    def _post(self, text: str) -> DeliveryResult:
        payload = {
            "chat_id": self.chat_id,
            "text": text[:MAX_TELEGRAM_CHARS],
            "disable_web_page_preview": bool(self.config.get("disable_preview", True)),
        }
        try:
            response = httpx.post(
                f"{API_BASE}/bot{self.token}/sendMessage",
                json=payload,
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 - a dead endpoint must not break dispatch
            return DeliveryResult(
                ok=False,
                message=self.scrub(f"Telegram request failed: {type(exc).__name__}: {exc}"),
                details={"chat_id": self.chat_id},
            )

        if response.status_code >= 400:
            return DeliveryResult(
                ok=False,
                message=self.scrub(
                    f"Telegram rejected the message (HTTP {response.status_code}): "
                    f"{response.text[:300]}"
                ),
                details={"status_code": response.status_code, "chat_id": self.chat_id},
            )
        return DeliveryResult(
            ok=True,
            message="Telegram message delivered.",
            details={"status_code": response.status_code, "chat_id": self.chat_id},
        )

    def send(self, message: NotificationMessage) -> DeliveryResult:
        missing = self.missing_config()
        if missing:
            return self.not_configured(missing)
        text = f"{message.subject}\n\n{message.body}" if message.subject else message.body
        if message.url:
            text = f"{text}\n\n{message.url}"
        return self._post(text)

    def test(self) -> DeliveryResult:
        missing = self.missing_config()
        if missing:
            return self.not_configured(missing)
        return self._post("Job Agent test notification - Telegram alerts are working.")

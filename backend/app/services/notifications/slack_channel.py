"""Slack incoming-webhook channel.

The webhook URL is itself the credential -- anyone holding it can post to the
channel -- so it is stored encrypted, never echoed in a result, and scrubbed out
of any error text before it is persisted.
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


@register_channel
class SlackChannel(NotificationAdapter):
    channel_type = "slack"
    display_name = "Slack"
    requires_credential = True
    config_schema = [
        {
            "key": "username",
            "label": "Bot display name",
            "type": "text",
            "required": False,
            "help": "Optional override for the name shown on posts.",
        },
        {
            "key": "icon_emoji",
            "label": "Icon emoji",
            "type": "text",
            "required": False,
            "help": "Optional, for example :briefcase:.",
        },
    ]

    @property
    def webhook_url(self) -> str:
        return self.credential or settings.slack_webhook_url or ""

    def scrub(self, text: str) -> str:
        return scrub(text, self.webhook_url)

    def missing_config(self) -> list[str]:
        return [] if self.webhook_url.startswith("http") else ["webhook_url"]

    def _post(self, text: str) -> DeliveryResult:
        payload: dict = {"text": text}
        if self.config.get("username"):
            payload["username"] = str(self.config["username"])
        if self.config.get("icon_emoji"):
            payload["icon_emoji"] = str(self.config["icon_emoji"])
        try:
            response = httpx.post(self.webhook_url, json=payload, timeout=HTTP_TIMEOUT_SECONDS)
        except Exception as exc:  # noqa: BLE001 - a dead webhook must not break dispatch
            return DeliveryResult(
                ok=False,
                message=self.scrub(f"Slack request failed: {type(exc).__name__}: {exc}"),
                details={},
            )
        if response.status_code >= 400:
            return DeliveryResult(
                ok=False,
                message=self.scrub(
                    f"Slack webhook rejected the message (HTTP {response.status_code}): "
                    f"{response.text[:300]}"
                ),
                details={"status_code": response.status_code},
            )
        return DeliveryResult(
            ok=True,
            message="Slack message delivered.",
            details={"status_code": response.status_code},
        )

    def send(self, message: NotificationMessage) -> DeliveryResult:
        missing = self.missing_config()
        if missing:
            return self.not_configured(missing)
        text = f"*{message.subject}*\n{message.body}" if message.subject else message.body
        if message.url:
            text = f"{text}\n{message.url}"
        return self._post(text)

    def test(self) -> DeliveryResult:
        missing = self.missing_config()
        if missing:
            return self.not_configured(missing)
        return self._post("Job Agent test notification - Slack alerts are working.")

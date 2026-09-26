"""Provider-agnostic WhatsApp channel.

WhatsApp has no single API: Meta Cloud, Twilio, Gupshup, 360dialog and the
various Indian resellers all expect a different JSON body at a different URL.
Rather than bless one vendor, this adapter posts a caller-supplied
``payload_template`` with ``{{message}}``, ``{{to}}``, ``{{subject}}`` and
``{{api_key}}`` placeholders, so a new provider is a settings change instead of
a code change. The rendered payload is never echoed back, because a template may
legitimately place the API key inside the body.
"""
from __future__ import annotations

import json
from typing import Any

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

DEFAULT_PAYLOAD_TEMPLATE: dict[str, Any] = {
    "to": "{{to}}",
    "type": "text",
    "message": "{{message}}",
}


def render_template(node: Any, values: dict[str, str]) -> Any:
    """Substitute ``{{placeholder}}`` tokens through a nested JSON structure."""
    if isinstance(node, str):
        rendered = node
        for key, value in values.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        return rendered
    if isinstance(node, dict):
        return {key: render_template(value, values) for key, value in node.items()}
    if isinstance(node, list):
        return [render_template(item, values) for item in node]
    return node


@register_channel
class WhatsAppChannel(NotificationAdapter):
    channel_type = "whatsapp"
    display_name = "WhatsApp"
    requires_credential = True
    config_schema = [
        {
            "key": "provider",
            "label": "Provider",
            "type": "text",
            "required": True,
            "help": "Free-text label, e.g. meta_cloud, twilio, gupshup.",
        },
        {
            "key": "api_url",
            "label": "API endpoint",
            "type": "url",
            "required": True,
            "help": "Full POST URL supplied by your WhatsApp provider.",
        },
        {
            "key": "to_number",
            "label": "Recipient number",
            "type": "text",
            "required": True,
            "help": "Destination in international format, e.g. 919876543210.",
        },
        {
            "key": "payload_template",
            "label": "Request body template",
            "type": "json",
            "required": False,
            "help": (
                "JSON body for your provider. Use {{message}}, {{to}}, {{subject}} "
                "and {{api_key}} placeholders. Defaults to a simple to/message body."
            ),
        },
        {
            "key": "auth_header",
            "label": "Auth header name",
            "type": "text",
            "required": False,
            "help": "Defaults to Authorization. Set to an empty value for body-only auth.",
        },
        {
            "key": "auth_scheme",
            "label": "Auth scheme",
            "type": "text",
            "required": False,
            "help": "Defaults to Bearer. Leave empty to send the raw key.",
        },
    ]

    @property
    def api_key(self) -> str:
        return self.credential or settings.whatsapp_api_key or ""

    @property
    def provider(self) -> str:
        return str(self.config.get("provider") or settings.whatsapp_provider or "").strip()

    @property
    def api_url(self) -> str:
        return str(self.config.get("api_url") or "").strip()

    @property
    def to_number(self) -> str:
        return str(self.config.get("to_number") or "").strip()

    def scrub(self, text: str) -> str:
        return scrub(text, self.api_key)

    def missing_config(self) -> list[str]:
        missing: list[str] = []
        if not self.provider:
            missing.append("provider")
        if not self.api_url.startswith("http"):
            missing.append("api_url")
        if not self.to_number:
            missing.append("to_number")
        if not self.api_key:
            missing.append("api_key")
        return missing

    def _template(self) -> tuple[Any, str]:
        """Return the parsed template and an error string if it is unusable."""
        raw = self.config.get("payload_template")
        if not raw:
            return DEFAULT_PAYLOAD_TEMPLATE, ""
        if isinstance(raw, (dict, list)):
            return raw, ""
        try:
            return json.loads(str(raw)), ""
        except (TypeError, ValueError) as exc:
            return None, f"payload_template is not valid JSON: {exc}"

    def _headers(self) -> dict[str, str]:
        header_name = self.config.get("auth_header", "Authorization")
        if header_name is None or str(header_name).strip() == "":
            return {}
        scheme = str(self.config.get("auth_scheme", "Bearer") or "").strip()
        value = f"{scheme} {self.api_key}".strip() if scheme else self.api_key
        return {str(header_name).strip(): value}

    def _post(self, subject: str, body: str) -> DeliveryResult:
        template, error = self._template()
        if error:
            return DeliveryResult(ok=False, message=error, details={"provider": self.provider})

        payload = render_template(
            template,
            {
                "message": body,
                "to": self.to_number,
                "subject": subject,
                "api_key": self.api_key,
            },
        )
        try:
            response = httpx.post(
                self.api_url,
                json=payload,
                headers=self._headers(),
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 - a dead provider must not break dispatch
            return DeliveryResult(
                ok=False,
                message=self.scrub(f"WhatsApp request failed: {type(exc).__name__}: {exc}"),
                details={"provider": self.provider},
            )
        if response.status_code >= 400:
            return DeliveryResult(
                ok=False,
                message=self.scrub(
                    f"WhatsApp provider rejected the message (HTTP {response.status_code}): "
                    f"{response.text[:300]}"
                ),
                details={"provider": self.provider, "status_code": response.status_code},
            )
        return DeliveryResult(
            ok=True,
            message=f"WhatsApp message delivered via {self.provider}.",
            details={"provider": self.provider, "status_code": response.status_code},
        )

    def send(self, message: NotificationMessage) -> DeliveryResult:
        missing = self.missing_config()
        if missing:
            return self.not_configured(missing)
        body = message.body
        if message.url:
            body = f"{body}\n\n{message.url}"
        return self._post(message.subject, body)

    def test(self) -> DeliveryResult:
        missing = self.missing_config()
        if missing:
            return self.not_configured(missing)
        return self._post(
            "Job Agent test notification",
            "Job Agent test notification - WhatsApp alerts are working.",
        )

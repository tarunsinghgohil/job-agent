"""SMTP email channel.

Uses the stdlib rather than a provider SDK so the single self-hosted user can
point this at any mailbox (Gmail app password, Zoho, a company relay) without
adding another dependency or third-party account.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.services.notifications.base import (
    HTTP_TIMEOUT_SECONDS,
    DeliveryResult,
    NotificationAdapter,
    NotificationMessage,
    register_channel,
)


@register_channel
class EmailChannel(NotificationAdapter):
    channel_type = "email"
    display_name = "Email (SMTP)"
    requires_credential = True
    config_schema = [
        {
            "key": "to_address",
            "label": "Send to",
            "type": "email",
            "required": True,
            "help": "Inbox that receives digests and alerts.",
        },
        {
            "key": "host",
            "label": "SMTP host",
            "type": "text",
            "required": False,
            "help": "Defaults to the SMTP_HOST environment setting.",
        },
        {
            "key": "port",
            "label": "SMTP port",
            "type": "number",
            "required": False,
            "help": "Defaults to SMTP_PORT (587 for STARTTLS).",
        },
        {
            "key": "username",
            "label": "SMTP username",
            "type": "text",
            "required": False,
            "help": "Defaults to SMTP_USER. Leave blank for an unauthenticated relay.",
        },
        {
            "key": "from_address",
            "label": "From address",
            "type": "email",
            "required": False,
            "help": "Defaults to SMTP_FROM, then the username.",
        },
    ]

    @property
    def host(self) -> str:
        return str(self.config.get("host") or settings.smtp_host or "").strip()

    @property
    def port(self) -> int:
        raw = self.config.get("port") or settings.smtp_port or 587
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 587

    @property
    def username(self) -> str:
        return str(self.config.get("username") or settings.smtp_user or "").strip()

    @property
    def from_address(self) -> str:
        return str(
            self.config.get("from_address") or settings.smtp_from or self.username or ""
        ).strip()

    @property
    def to_address(self) -> str:
        return str(self.config.get("to_address") or "").strip()

    @property
    def password(self) -> str:
        return self.credential or settings.smtp_password or ""

    def scrub(self, text: str) -> str:
        from app.services.notifications.base import scrub

        return scrub(text, self.password)

    def missing_config(self) -> list[str]:
        missing: list[str] = []
        if not self.to_address:
            missing.append("to_address")
        if not self.host:
            missing.append("host")
        if not self.from_address:
            missing.append("from_address")
        if self.username and not self.password:
            missing.append("password")
        return missing

    def _build(self, subject: str, body: str, url: str | None = None) -> EmailMessage:
        mail = EmailMessage()
        mail["Subject"] = subject or "(no subject)"
        mail["From"] = self.from_address
        mail["To"] = self.to_address
        text = body or ""
        if url:
            text = f"{text}\n\n{url}"
        mail.set_content(text)
        return mail

    def _deliver(self, mail: EmailMessage) -> DeliveryResult:
        try:
            with smtplib.SMTP(self.host, self.port, timeout=HTTP_TIMEOUT_SECONDS) as client:
                client.ehlo()
                try:
                    client.starttls()
                    client.ehlo()
                except smtplib.SMTPNotSupportedError:
                    # Plaintext-only relays (internal port 25) still deliver; refusing
                    # here would silently disable notifications on such a setup.
                    pass
                if self.username:
                    client.login(self.username, self.password)
                client.send_message(mail)
        except Exception as exc:  # noqa: BLE001 - a bad mail server must not break dispatch
            return DeliveryResult(
                ok=False,
                message=self.scrub(f"SMTP delivery failed: {type(exc).__name__}: {exc}"),
                details={"host": self.host, "port": self.port},
            )
        return DeliveryResult(
            ok=True,
            message=f"Email sent to {self.to_address}.",
            details={"host": self.host, "port": self.port, "to": self.to_address},
        )

    def send(self, message: NotificationMessage) -> DeliveryResult:
        missing = self.missing_config()
        if missing:
            return self.not_configured(missing)
        return self._deliver(self._build(message.subject, message.body, message.url))

    def test(self) -> DeliveryResult:
        missing = self.missing_config()
        if missing:
            return self.not_configured(missing)
        return self._deliver(
            self._build(
                "Job Agent test notification",
                "This is a test message from your job application agent. "
                "If you can read it, email alerts are working.",
            )
        )

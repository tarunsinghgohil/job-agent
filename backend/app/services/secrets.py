"""Encrypted credential storage (spec section 16).

Credentials never live in ordinary application tables and are never returned
to the client in plaintext. The API only ever exposes a masked hint.

Resolution order for any credential: the database (user-managed, encrypted)
first, then the environment (deployment-managed). That lets the dashboard
override a deployment default without editing the environment.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.db.models.ops import EncryptedSecret

logger = logging.getLogger(__name__)

# The credential catalogue the Integrations screen renders.
SECRET_CATALOGUE: dict[str, dict[str, str]] = {
    "openai_api_key": {
        "label": "OpenAI API key",
        "provider": "openai",
        "env": "openai_api_key",
    },
    "job_search_api_key": {
        "label": "Generic job search provider key",
        "provider": "job_source",
        "env": "job_search_api_key",
    },
    "adzuna_app_key": {
        "label": "Adzuna application key",
        "provider": "adzuna",
        "env": "adzuna_app_key",
    },
    "smtp_password": {
        "label": "SMTP password",
        "provider": "email",
        "env": "smtp_password",
    },
    "telegram_bot_token": {
        "label": "Telegram bot token",
        "provider": "telegram",
        "env": "telegram_bot_token",
    },
    "slack_webhook_url": {
        "label": "Slack webhook URL",
        "provider": "slack",
        "env": "slack_webhook_url",
    },
    "whatsapp_api_key": {
        "label": "WhatsApp provider API key",
        "provider": "whatsapp",
        "env": "whatsapp_api_key",
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_row(db: Session, user_id: str, key: str) -> EncryptedSecret | None:
    return db.execute(
        select(EncryptedSecret).where(
            EncryptedSecret.user_id == user_id, EncryptedSecret.key == key
        )
    ).scalar_one_or_none()


def get_by_id(db: Session, secret_id: str) -> EncryptedSecret | None:
    return db.get(EncryptedSecret, secret_id)


def resolve(db: Session, user_id: str, key: str) -> str | None:
    """Return the plaintext credential, database first, environment second."""
    row = get_row(db, user_id, key)
    if row is not None:
        try:
            return decrypt_secret(row.ciphertext)
        except ValueError:
            logger.error("Stored secret %r could not be decrypted; check APP_SECRET_KEY.", key)
            return None

    env_attr = SECRET_CATALOGUE.get(key, {}).get("env", key)
    value = getattr(settings, env_attr, "") or ""
    return value.strip() or None


def resolve_by_ref(db: Session, credential_ref: str | None) -> str | None:
    """Resolve a credential referenced by row id, used by sources and channels."""
    if not credential_ref:
        return None
    row = get_by_id(db, credential_ref)
    if row is None:
        return None
    try:
        return decrypt_secret(row.ciphertext)
    except ValueError:
        logger.error("Secret %s could not be decrypted; check APP_SECRET_KEY.", credential_ref)
        return None


def put(
    db: Session, user_id: str, key: str, value: str, *, label: str = "", provider: str = ""
) -> EncryptedSecret:
    """Create or rotate a credential. The plaintext is never persisted."""
    value = (value or "").strip()
    if not value:
        raise ValueError("A credential value is required.")

    meta = SECRET_CATALOGUE.get(key, {})
    row = get_row(db, user_id, key)
    is_rotation = row is not None

    if row is None:
        row = EncryptedSecret(user_id=user_id, key=key)
        db.add(row)

    row.ciphertext = encrypt_secret(value)
    row.hint = mask_secret(value)
    row.label = label or meta.get("label", key)
    row.provider = provider or meta.get("provider", "")
    if is_rotation:
        row.rotated_at = _now()
    # A new value invalidates any previous test result.
    row.last_test_ok = None
    row.last_test_error = ""
    db.flush()
    return row


def delete(db: Session, user_id: str, key: str) -> bool:
    row = get_row(db, user_id, key)
    if row is None:
        return False
    db.delete(row)
    return True


def record_test(
    db: Session, user_id: str, key: str, ok: bool, error: str = ""
) -> EncryptedSecret | None:
    row = get_row(db, user_id, key)
    if row is None:
        return None
    row.last_tested_at = _now()
    row.last_test_ok = ok
    row.last_test_error = error[:2000] if not ok else ""
    return row


def describe_all(db: Session, user_id: str) -> list[dict[str, Any]]:
    """Masked view of every catalogued credential, for the settings screen."""
    rows = {
        r.key: r
        for r in db.execute(
            select(EncryptedSecret).where(EncryptedSecret.user_id == user_id)
        ).scalars().all()
    }

    out: list[dict[str, Any]] = []
    for key, meta in SECRET_CATALOGUE.items():
        row = rows.get(key)
        env_value = (getattr(settings, meta.get("env", key), "") or "").strip()

        if row is not None:
            out.append(
                {
                    "key": key,
                    "label": row.label or meta["label"],
                    "provider": row.provider or meta.get("provider", ""),
                    "connected": True,
                    "masked_value": row.hint,
                    "source": "database",
                    "last_tested_at": row.last_tested_at,
                    "last_test_ok": row.last_test_ok,
                    "last_test_error": row.last_test_error,
                    "rotated_at": row.rotated_at,
                }
            )
        elif env_value:
            out.append(
                {
                    "key": key,
                    "label": meta["label"],
                    "provider": meta.get("provider", ""),
                    "connected": True,
                    "masked_value": mask_secret(env_value),
                    "source": "environment",
                    "last_tested_at": None,
                    "last_test_ok": None,
                    "last_test_error": "",
                    "rotated_at": None,
                }
            )
        else:
            out.append(
                {
                    "key": key,
                    "label": meta["label"],
                    "provider": meta.get("provider", ""),
                    "connected": False,
                    "masked_value": "",
                    "source": "none",
                    "last_tested_at": None,
                    "last_test_ok": None,
                    "last_test_error": "",
                    "rotated_at": None,
                }
            )
    return out


def test_credential(db: Session, user_id: str, key: str) -> tuple[bool, str]:
    """Attempt a real, cheap call against the provider the credential belongs to."""
    value = resolve(db, user_id, key)
    if not value:
        return (False, "No credential is configured.")

    try:
        if key == "openai_api_key":
            from openai import OpenAI

            OpenAI(api_key=value, timeout=15.0, max_retries=0).models.list()
            return (True, "Connected to OpenAI.")

        if key == "telegram_bot_token":
            import httpx

            response = httpx.get(
                f"https://api.telegram.org/bot{value}/getMe", timeout=10.0
            )
            if response.status_code == 200 and response.json().get("ok"):
                return (True, "Telegram bot token is valid.")
            return (False, f"Telegram rejected the token (HTTP {response.status_code}).")

        if key == "slack_webhook_url":
            # A webhook cannot be validated without posting, so only the shape
            # is checked here; the channel Test button sends a real message.
            if value.startswith("https://hooks.slack.com/"):
                return (True, "Webhook URL looks valid. Use the channel test to send a message.")
            return (False, "That does not look like a Slack webhook URL.")

        if key == "smtp_password":
            import smtplib

            if not settings.smtp_host:
                return (False, "SMTP_HOST is not configured.")
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                server.starttls()
                server.login(settings.smtp_user, value)
            return (True, "SMTP authentication succeeded.")

        return (True, "Stored. This provider has no connection test.")
    except Exception as exc:
        # The message can contain the endpoint but never the credential itself.
        return (False, f"{type(exc).__name__}: {exc}"[:400])

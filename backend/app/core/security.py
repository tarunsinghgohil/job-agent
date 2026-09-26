"""Password hashing, JWT issuance/verification, and secret encryption.

Rules enforced here:
  * passwords are only ever stored as bcrypt hashes;
  * provider credentials are only ever stored Fernet-encrypted;
  * nothing in this module logs or returns a plaintext secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]

# bcrypt silently truncates input beyond 72 bytes; pre-hash so long passphrases
# keep their full entropy instead of being cut off.
_BCRYPT_MAX_BYTES = 72


def _prepare_password(password: str) -> bytes:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        return base64.b64encode(hashlib.sha256(raw).digest())
    return raw


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare_password(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare_password(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_problems(password: str) -> list[str]:
    """Minimum strength policy, applied on registration and password change."""
    issues: list[str] = []
    if len(password) < 12:
        issues.append("Password must be at least 12 characters long.")
    if not any(c.isalpha() for c in password):
        issues.append("Password must contain at least one letter.")
    if not any(c.isdigit() for c in password):
        issues.append("Password must contain at least one digit.")
    return issues


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def create_token(
    subject: str,
    token_type: TokenType,
    *,
    extra: dict[str, Any] | None = None,
    jti: str | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    if token_type == "access":
        expires = now + timedelta(minutes=settings.access_token_ttl_minutes)
    else:
        expires = now + timedelta(days=settings.refresh_token_ttl_days)

    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": jti or secrets.token_urlsafe(16),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM), expires


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Raises jwt.PyJWTError subclasses on any problem."""
    payload = jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected a {expected_type} token.")
    return payload


def hash_token(token: str) -> str:
    """Refresh tokens are stored as hashes so a DB leak cannot replay sessions."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# --------------------------------------------------------------------------
# Secret encryption (provider credentials)
# --------------------------------------------------------------------------
def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.app_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Stored secret could not be decrypted. This usually means APP_SECRET_KEY changed."
        ) from exc


def mask_secret(plaintext: str) -> str:
    """Render a credential for display: never return more than the last 4 chars."""
    if not plaintext:
        return ""
    tail = plaintext[-4:] if len(plaintext) >= 8 else ""
    return f"{'*' * 8}{tail}"


def generate_secret_key() -> str:
    return secrets.token_urlsafe(48)

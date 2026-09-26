"""Authentication service: login, refresh, session revocation, lockout."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AuthError, ValidationError
from app.core.security import (
    create_token,
    hash_password,
    hash_token,
    password_problems,
    verify_password,
)
from app.db.models.identity import User, UserSession

logger = logging.getLogger(__name__)

MAX_FAILED_LOGINS = 8
LOCKOUT_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite loses tzinfo on round-trip; treat naive timestamps as UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(
        select(User).where(User.email == email.strip().lower(), User.deleted_at.is_(None))
    ).scalar_one_or_none()


def create_user(
    db: Session, email: str, password: str, *, full_name: str = "", is_owner: bool = False
) -> User:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise ValidationError("A valid email address is required.")
    if get_user_by_email(db, email) is not None:
        raise ValidationError("An account with that email already exists.")

    problems = password_problems(password)
    if problems:
        raise ValidationError("The password is not strong enough.", details={"problems": problems})

    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        is_owner=is_owner,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    """Verify credentials. Raises AuthError with a deliberately vague message."""
    user = get_user_by_email(db, email)
    generic = AuthError("Email or password is incorrect.")

    if user is None:
        # Hash anyway so a missing account is not detectably faster.
        verify_password(password, "$2b$12$" + "x" * 53)
        raise generic

    locked_until = _as_aware(user.locked_until)
    if locked_until and locked_until > _now():
        remaining = int((locked_until - _now()).total_seconds() // 60) + 1
        raise AuthError(
            f"This account is temporarily locked after repeated failed sign-ins. "
            f"Try again in {remaining} minute(s)."
        )

    if not user.is_active:
        raise AuthError("This account is disabled.")

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_login_count = 0
            logger.warning("Account locked after repeated failures: user_id=%s", user.id)
        raise generic

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = _now()
    return user


def issue_tokens(
    db: Session, user: User, *, user_agent: str = "", ip_address: str = ""
) -> tuple[str, str, datetime]:
    """Return ``(access_token, refresh_token, access_expires_at)``.

    Only the hash of the refresh token is stored, so a database leak cannot be
    replayed into a live session.
    """
    access_token, access_expires = create_token(user.id, "access")
    refresh_token, refresh_expires = create_token(user.id, "refresh")

    db.add(
        UserSession(
            user_id=user.id,
            refresh_token_hash=hash_token(refresh_token),
            expires_at=refresh_expires,
            user_agent=(user_agent or "")[:400],
            ip_address=(ip_address or "")[:64],
        )
    )
    return access_token, refresh_token, access_expires


def rotate_refresh_token(
    db: Session, refresh_token: str, *, user_agent: str = "", ip_address: str = ""
) -> tuple[User, str, str, datetime]:
    """Validate a refresh token and swap it for a fresh pair.

    Rotation on every use means a stolen refresh token stops working as soon as
    the legitimate client refreshes.
    """
    try:
        payload = jwt.decode(
            refresh_token, settings.app_secret_key, algorithms=["HS256"]
        )
    except jwt.PyJWTError as exc:
        raise AuthError("The session has expired. Sign in again.") from exc

    if payload.get("type") != "refresh":
        raise AuthError("Invalid session token.")

    token_hash = hash_token(refresh_token)
    session = db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == token_hash)
    ).scalar_one_or_none()

    if session is None:
        raise AuthError("The session is no longer valid. Sign in again.")
    if session.revoked_at is not None:
        # A revoked token being presented suggests theft; drop every session.
        logger.warning("Revoked refresh token replayed for user_id=%s", session.user_id)
        revoke_all_sessions(db, session.user_id)
        raise AuthError("The session was revoked. Sign in again.")

    expires_at = _as_aware(session.expires_at)
    if expires_at and expires_at < _now():
        raise AuthError("The session has expired. Sign in again.")

    user = db.get(User, session.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthError("This account is no longer active.")

    session.revoked_at = _now()
    access_token, new_refresh, access_expires = issue_tokens(
        db, user, user_agent=user_agent, ip_address=ip_address
    )
    return user, access_token, new_refresh, access_expires


def revoke_session_by_token(db: Session, refresh_token: str) -> bool:
    session = db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == hash_token(refresh_token))
    ).scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        return False
    session.revoked_at = _now()
    return True


def revoke_session(db: Session, user_id: str, session_id: str) -> bool:
    session = db.get(UserSession, session_id)
    if session is None or session.user_id != user_id:
        return False
    session.revoked_at = _now()
    return True


def revoke_all_sessions(db: Session, user_id: str, *, except_id: str | None = None) -> int:
    sessions = db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
        )
    ).scalars().all()
    count = 0
    for session in sessions:
        if except_id and session.id == except_id:
            continue
        session.revoked_at = _now()
        count += 1
    return count


def active_sessions(db: Session, user_id: str) -> list[UserSession]:
    rows = db.execute(
        select(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.created_at.desc())
    ).scalars().all()
    now = _now()
    return [s for s in rows if (_as_aware(s.expires_at) or now) > now]


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise AuthError("The current password is incorrect.")
    problems = password_problems(new_password)
    if problems:
        raise ValidationError("The new password is not strong enough.", details={"problems": problems})
    if verify_password(new_password, user.password_hash):
        raise ValidationError("The new password must differ from the current one.")

    user.password_hash = hash_password(new_password)
    # Every other session is invalidated: a password change should log out
    # anything that might have been using the old credentials.
    revoke_all_sessions(db, user.id)

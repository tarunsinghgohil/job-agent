"""Shared FastAPI dependencies: authentication, context, rate limiting."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AuthError, ForbiddenError, RateLimitError
from app.core.security import decode_token
from app.db.models.identity import CareerProfile, User
from app.db.models.preferences import JobPreference
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


@dataclass(slots=True)
class RequestContext:
    """Everything an audit entry needs about who did what, from where."""

    user: User
    ip_address: str
    user_agent: str

    @property
    def user_id(self) -> str:
        return self.user.id

    @property
    def actor(self) -> str:
        return self.user.email


def client_ip(request: Request) -> str:
    # Trust a proxy header only when explicitly running behind one.
    if settings.is_production:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def get_current_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthError("Sign in to continue.")

    try:
        payload = decode_token(credentials.credentials, "access")
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("The session has expired. Refresh and try again.", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid credentials.") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("Invalid credentials.")

    user = db.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthError("This account is no longer active.")

    request.state.user_id = user.id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_context(request: Request, user: CurrentUser) -> RequestContext:
    return RequestContext(
        user=user,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:400],
    )


Context = Annotated[RequestContext, Depends(get_context)]


def require_owner(user: CurrentUser) -> User:
    if not user.is_owner:
        raise ForbiddenError("This action requires the account owner.")
    return user


def get_profile(db: DbSession, user: CurrentUser) -> CareerProfile:
    """Return the user's profile, creating an empty one on first access."""
    profile = db.execute(
        select(CareerProfile).where(CareerProfile.user_id == user.id)
    ).scalar_one_or_none()
    if profile is None:
        profile = CareerProfile(user_id=user.id, full_name=user.full_name, email=user.email)
        db.add(profile)
        db.flush()
    return profile


CurrentProfile = Annotated[CareerProfile, Depends(get_profile)]


def get_preferences(db: DbSession, user: CurrentUser) -> JobPreference:
    """Return the user's preferences, creating defaults on first access.

    Defaults are neutral, never a guess at someone's job search.
    """
    prefs = db.execute(
        select(JobPreference).where(JobPreference.user_id == user.id)
    ).scalar_one_or_none()
    if prefs is None:
        prefs = JobPreference(
            user_id=user.id,
            scoring_weights=JobPreference.default_weights(),
            employment_types=["full_time"],
            timezone=settings.timezone,
        )
        db.add(prefs)
        db.flush()
    return prefs


CurrentPreferences = Annotated[JobPreference, Depends(get_preferences)]


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------
class SlidingWindowLimiter:
    """In-process limiter.

    Adequate for this single-user deployment. A multi-instance deployment
    should move this to Redis so the window is shared across workers.
    """

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_in = int(self.window - (now - bucket[0])) + 1
            raise RateLimitError(
                f"Too many requests. Try again in {retry_in} second(s).",
                details={"retry_after_seconds": retry_in},
            )
        bucket.append(now)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


login_limiter = SlidingWindowLimiter(limit=10, window_seconds=300)
ai_limiter = SlidingWindowLimiter(limit=30, window_seconds=60)
general_limiter = SlidingWindowLimiter(limit=settings.rate_limit_per_minute, window_seconds=60)


def rate_limit_login(request: Request) -> None:
    login_limiter.check(f"login:{client_ip(request)}")


def rate_limit_ai(user: CurrentUser) -> None:
    ai_limiter.check(f"ai:{user.id}")

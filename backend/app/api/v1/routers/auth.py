"""Authentication endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.config import settings
from app.core.deps import Context, CurrentUser, DbSession, client_ip, rate_limit_login
from app.core.errors import AuthError
from app.schemas.common import MessageResponse
from app.schemas.identity import (
    ChangePasswordRequest,
    LoginRequest,
    SessionOut,
    TokenResponse,
    UserOut,
)
from app.services import audit, auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    """httpOnly so JavaScript cannot read it; SameSite=lax to blunt CSRF."""
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    _: Annotated[None, Depends(rate_limit_login)] = None,
) -> TokenResponse:
    ip = client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    try:
        user = auth_service.authenticate(db, payload.email, payload.password)
    except AuthError:
        audit.record(
            db,
            action="auth.login",
            actor=payload.email[:80],
            summary="Failed sign-in attempt",
            ip_address=ip,
            user_agent=user_agent,
            success=False,
        )
        raise

    access_token, refresh_token, expires_at = auth_service.issue_tokens(
        db, user, user_agent=user_agent, ip_address=ip
    )
    _set_refresh_cookie(response, refresh_token)

    audit.record(
        db,
        action="auth.login",
        user_id=user.id,
        actor=user.email,
        summary="Signed in",
        ip_address=ip,
        user_agent=user_agent,
    )
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.access_token_ttl_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, db: DbSession) -> TokenResponse:
    token = request.cookies.get(REFRESH_COOKIE, "")
    if not token:
        raise AuthError("No active session.")

    user, access_token, new_refresh, _ = auth_service.rotate_refresh_token(
        db,
        token,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=client_ip(request),
    )
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.access_token_ttl_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(request: Request, response: Response, db: DbSession, user: CurrentUser) -> MessageResponse:
    token = request.cookies.get(REFRESH_COOKIE, "")
    if token:
        auth_service.revoke_session_by_token(db, token)
    _clear_refresh_cookie(response)
    audit.record(db, action="auth.logout", user_id=user.id, actor=user.email, summary="Signed out")
    return MessageResponse(message="Signed out.")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest, response: Response, db: DbSession, ctx: Context
) -> MessageResponse:
    auth_service.change_password(db, ctx.user, payload.current_password, payload.new_password)
    _clear_refresh_cookie(response)
    audit.record(
        db,
        action="auth.change_password",
        user_id=ctx.user_id,
        actor=ctx.actor,
        summary="Password changed; all sessions revoked",
        ip_address=ctx.ip_address,
        user_agent=ctx.user_agent,
    )
    return MessageResponse(message="Password changed. Sign in again on your other devices.")


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(db: DbSession, user: CurrentUser) -> list[SessionOut]:
    return [SessionOut.model_validate(s) for s in auth_service.active_sessions(db, user.id)]


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
def revoke_session(session_id: str, db: DbSession, ctx: Context) -> MessageResponse:
    revoked = auth_service.revoke_session(db, ctx.user_id, session_id)
    if not revoked:
        return MessageResponse(message="That session was already inactive.", ok=False)
    audit.record(
        db,
        action="auth.revoke_session",
        user_id=ctx.user_id,
        actor=ctx.actor,
        entity_type="user_session",
        entity_id=session_id,
        summary="Session revoked",
    )
    return MessageResponse(message="Session revoked.")

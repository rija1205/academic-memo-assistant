from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyCookie, APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import (
    InvalidCsrfToken,
    constant_time_equal,
    load_csrf_token,
)
from app.auth.service import AuthenticatedSession, get_authenticated_session
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.auth import AuthSession
from app.models.user import User

_startup_settings = get_settings()
session_cookie_scheme = APIKeyCookie(
    name=_startup_settings.session_cookie_name,
    auto_error=False,
)
csrf_header_scheme = APIKeyHeader(name="X-CSRF-Token", auto_error=False)


@dataclass(frozen=True)
class CurrentAuth:
    user: User
    session: AuthSession


async def get_current_auth(
    raw_token: str | None = Security(session_cookie_scheme),
    db: AsyncSession = Depends(get_session),
) -> CurrentAuth:
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Session"},
        )

    context: AuthenticatedSession | None = await get_authenticated_session(
        db,
        raw_token=raw_token,
    )
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid.",
            headers={"WWW-Authenticate": "Session"},
        )
    # A suspended account is refused even when its session is still valid: suspension has to
    # take effect immediately, not at the next sign-in.
    if getattr(context.user, "is_suspended", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is suspended.",
        )
    if not getattr(context.user, "is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is disabled.",
        )
    return CurrentAuth(user=context.user, session=context.session)


async def get_current_user(current_auth: CurrentAuth = Depends(get_current_auth)) -> User:
    return current_auth.user


async def require_csrf(
    request: Request,
    header_token: str | None = Security(csrf_header_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    try:
        if cookie_token:
            load_csrf_token(
                cookie_token,
                max_age_seconds=settings.session_ttl_days * 24 * 60 * 60,
                settings=settings,
            )
    except InvalidCsrfToken as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        ) from exc
    if not header_token or not cookie_token or not constant_time_equal(header_token, cookie_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )

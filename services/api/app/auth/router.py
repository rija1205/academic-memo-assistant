import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cookies import (
    clear_auth_cookies,
    clear_oauth_state_cookie,
    issue_csrf_token,
    set_csrf_cookie,
    set_oauth_state_cookie,
    set_session_cookie,
)
from app.auth.dependencies import CurrentAuth, get_current_auth, require_csrf
from app.auth.google_oauth import (
    GoogleOAuthError,
    build_google_authorization_url,
    exchange_google_code,
    get_google_status,
    verify_google_id_token_async,
)
from app.auth.rate_limit import enforce_auth_rate_limit
from app.auth.schemas import (
    AuthResponse,
    CsrfResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    GoogleStartResponse,
    GoogleStatusResponse,
    LoginRequest,
    MessageResponse,
    ProfileUpdateRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    UserResponse,
)
from app.auth.security import (
    InvalidCsrfToken,
    InvalidOAuthState,
    constant_time_equal,
    create_pkce_pair,
    dump_oauth_state,
    load_csrf_token,
    load_oauth_state,
)
from app.auth.service import (
    EmailAlreadyExistsError,
    InvalidResetTokenError,
    authenticate_password,
    create_password_reset_token,
    create_password_user,
    create_session,
    get_or_create_google_user,
    list_user_sessions,
    reset_password,
    revoke_session,
    revoke_user_session,
    user_response,
)
from app.core.config import Settings, get_settings
from app.db.session import get_session

router = APIRouter(prefix="/api/auth", tags=["authentication"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/dashboard"
    return value


def _set_session_response(
    response: Response,
    *,
    raw_token: str,
    csrf_token: str,
    settings: Settings,
) -> None:
    set_session_cookie(response, raw_token, settings)
    set_csrf_cookie(response, csrf_token, settings)


def _csrf_for_request(
    request: Request,
    response: Response,
    settings: Settings,
) -> str:
    existing_token = request.cookies.get(settings.csrf_cookie_name)
    if existing_token:
        try:
            load_csrf_token(
                existing_token,
                max_age_seconds=settings.session_ttl_days * 24 * 60 * 60,
                settings=settings,
            )
        except InvalidCsrfToken:
            existing_token = None
    if existing_token:
        set_csrf_cookie(response, existing_token, settings)
        return existing_token
    return issue_csrf_token(response, settings)


@router.get("/csrf", response_model=CsrfResponse)
async def csrf_token(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> CsrfResponse:
    existing_token = request.cookies.get(settings.csrf_cookie_name)
    if existing_token:
        try:
            load_csrf_token(
                existing_token,
                max_age_seconds=settings.session_ttl_days * 24 * 60 * 60,
                settings=settings,
            )
        except InvalidCsrfToken:
            existing_token = None
    if existing_token:
        return CsrfResponse(csrf_token=existing_token)
    token = issue_csrf_token(response, settings)
    return CsrfResponse(csrf_token=token)


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> AuthResponse:
    await enforce_auth_rate_limit(request, identity=payload.email, settings=settings)
    try:
        user = await create_password_user(
            db,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session_pair = await create_session(
        db,
        user=user,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
        ttl_days=settings.session_ttl_days,
    )
    csrf = _csrf_for_request(request, response, settings)
    _set_session_response(
        response,
        raw_token=session_pair.raw_token,
        csrf_token=csrf,
        settings=settings,
    )
    return AuthResponse(user=user_response(user), csrf_token=csrf)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> AuthResponse:
    await enforce_auth_rate_limit(request, identity=payload.email, settings=settings)
    user = await authenticate_password(db, email=payload.email, password=payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Session"},
        )

    session_pair = await create_session(
        db,
        user=user,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
        ttl_days=settings.session_ttl_days,
    )
    csrf = _csrf_for_request(request, response, settings)
    _set_session_response(
        response,
        raw_token=session_pair.raw_token,
        csrf_token=csrf,
        settings=settings,
    )
    return AuthResponse(user=user_response(user), csrf_token=csrf)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> MessageResponse:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if raw_token:
        await revoke_session(db, raw_token=raw_token)
    clear_auth_cookies(response, settings)
    return MessageResponse(message="Logged out.")


@router.get("/me", response_model=UserResponse)
async def me(current_auth: CurrentAuth = Depends(get_current_auth)) -> UserResponse:
    return user_response(current_auth.user)


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
) -> list[SessionResponse]:
    sessions = await list_user_sessions(db, user_id=current_auth.user.id)
    return [
        SessionResponse(
            id=session.id,
            current=session.id == current_auth.session.id,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            expires_at=session.expires_at,
            user_agent=session.user_agent,
        )
        for session in sessions
    ]


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
async def revoke_one_session(
    session_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> MessageResponse:
    revoked = await revoke_user_session(
        db,
        user_id=current_auth.user.id,
        session_id=session_id,
    )
    if not revoked:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session_id == current_auth.session.id:
        clear_auth_cookies(response, settings)
    return MessageResponse(message="Session revoked.")


@router.patch("/profile", response_model=UserResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_session),
    current_auth: CurrentAuth = Depends(get_current_auth),
    _: None = Depends(require_csrf),
) -> UserResponse:
    user = current_auth.user
    user.display_name = payload.display_name.strip() if payload.display_name else None
    await db.commit()
    await db.refresh(user)
    return user_response(user)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> ForgotPasswordResponse:
    await enforce_auth_rate_limit(request, identity=payload.email, settings=settings)
    reset_token = await create_password_reset_token(db, email=payload.email)
    response = ForgotPasswordResponse(
        message="If an account exists, a password reset link has been prepared."
    )
    if reset_token and settings.auth_expose_reset_token:
        response.reset_token = reset_token
    return response


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password_endpoint(
    payload: ResetPasswordRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> MessageResponse:
    try:
        await reset_password(
            db,
            raw_token=payload.token,
            new_password=payload.password,
        )
    except InvalidResetTokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    clear_auth_cookies(response, settings)
    return MessageResponse(message="Password updated. You can sign in again.")


@router.get("/google/status", response_model=GoogleStatusResponse)
async def google_status(settings: Settings = Depends(get_settings)) -> GoogleStatusResponse:
    return GoogleStatusResponse(enabled=get_google_status(settings))


@router.post("/google/start", response_model=GoogleStartResponse)
async def google_start(
    response: Response,
    next: str | None = Query(default=None, max_length=2048),
    settings: Settings = Depends(get_settings),
    _: None = Depends(require_csrf),
) -> GoogleStartResponse:
    if not get_google_status(settings):
        raise HTTPException(status_code=503, detail="Google OAuth is not configured.")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = create_pkce_pair()
    next_url = _safe_next(next)
    serialized_state = dump_oauth_state(
        {"state": state, "nonce": nonce, "verifier": verifier, "next": next_url},
        settings,
    )
    authorization_url = build_google_authorization_url(
        settings,
        state=state,
        nonce=nonce,
        code_challenge=challenge,
    )
    set_oauth_state_cookie(response, serialized_state, settings)
    return GoogleStartResponse(authorization_url=authorization_url)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    error = request.query_params.get("error")
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    serialized_state = request.cookies.get(settings.oauth_state_cookie_name)
    failure_url = f"{settings.frontend_url.rstrip('/')}/login?error=oauth"

    if error or not code or not state or not serialized_state:
        response = RedirectResponse(failure_url, status_code=303)
        clear_oauth_state_cookie(response, settings)
        return response

    try:
        state_payload = load_oauth_state(
            serialized_state,
            max_age_seconds=settings.oauth_state_ttl_seconds,
            settings=settings,
        )
        if not constant_time_equal(str(state_payload.get("state", "")), state):
            raise InvalidOAuthState("OAuth state mismatch.")
        token_data = await exchange_google_code(
            settings,
            code=code,
            code_verifier=str(state_payload["verifier"]),
        )
        claims = await verify_google_id_token_async(
            settings,
            id_token_value=str(token_data["id_token"]),
            nonce=str(state_payload["nonce"]),
        )
        subject_claim = claims.get("sub")
        email_claim = claims.get("email")
        email_verified = claims.get("email_verified") is True
        display_name_claim = claims.get("name")
        if not isinstance(subject_claim, str) or not subject_claim:
            raise GoogleOAuthError("Google identity claims are incomplete.")
        if (
            not isinstance(email_claim, str)
            or not email_claim
            or len(email_claim) > 320
            or "@" not in email_claim
        ):
            raise GoogleOAuthError("Google identity claims are incomplete.")
        if not email_verified:
            raise GoogleOAuthError("Google email is not verified.")
        display_name = (
            display_name_claim[:200]
            if isinstance(display_name_claim, str)
            else None
        )
        user = await get_or_create_google_user(
            db,
            provider_account_id=subject_claim,
            email=email_claim,
            display_name=display_name,
            email_verified=email_verified,
            scopes=str(token_data.get("scope", settings.google_oauth_scopes)).split(),
            provider_metadata={"name": display_name},
        )
        if user is None:
            raise GoogleOAuthError("Google account is not eligible for sign-in.")
    except (GoogleOAuthError, InvalidOAuthState, KeyError):
        response = RedirectResponse(failure_url, status_code=303)
        clear_oauth_state_cookie(response, settings)
        return response

    session_pair = await create_session(
        db,
        user=user,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
        ttl_days=settings.session_ttl_days,
    )
    destination = f"{settings.frontend_url.rstrip('/')}{_safe_next(str(state_payload.get('next')))}"
    response = RedirectResponse(destination, status_code=303)
    set_session_cookie(response, session_pair.raw_token, settings)
    _csrf_for_request(request, response, settings)
    clear_oauth_state_cookie(response, settings)
    return response

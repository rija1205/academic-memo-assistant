import asyncio
from urllib.parse import urlencode

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token

from app.auth.security import constant_time_equal
from app.core.config import Settings

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleOAuthError(ValueError):
    """Raised when Google OAuth cannot be completed safely."""


def google_oauth_enabled(settings: Settings) -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def get_google_status(settings: Settings) -> bool:
    return google_oauth_enabled(settings)


def build_google_authorization_url(
    settings: Settings,
    *,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    if not google_oauth_enabled(settings):
        raise GoogleOAuthError("Google OAuth is not configured.")

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": settings.google_oauth_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
    }
    return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


async def exchange_google_code(
    settings: Settings,
    *,
    code: str,
    code_verifier: str,
) -> dict[str, object]:
    if not google_oauth_enabled(settings):
        raise GoogleOAuthError("Google OAuth is not configured.")

    payload = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": settings.google_redirect_uri,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(GOOGLE_TOKEN_ENDPOINT, data=payload)
            response.raise_for_status()
            token_data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GoogleOAuthError("Google token exchange failed.") from exc

    if not isinstance(token_data, dict) or not token_data.get("id_token"):
        raise GoogleOAuthError("Google did not return a valid ID token.")
    return token_data


def verify_google_id_token(
    settings: Settings,
    *,
    id_token_value: str,
    nonce: str,
) -> dict[str, object]:
    if not google_oauth_enabled(settings):
        raise GoogleOAuthError("Google OAuth is not configured.")

    try:
        claims = google_id_token.verify_oauth2_token(
            id_token_value,
            GoogleAuthRequest(),
            settings.google_client_id,
        )
    except (GoogleAuthError, ValueError) as exc:
        raise GoogleOAuthError("Google identity verification failed.") from exc

    if not isinstance(claims, dict):
        raise GoogleOAuthError("Google returned invalid identity claims.")
    claim_nonce = claims.get("nonce")
    if not isinstance(claim_nonce, str) or not constant_time_equal(claim_nonce, nonce):
        raise GoogleOAuthError("Google OAuth nonce validation failed.")
    return claims


async def verify_google_id_token_async(
    settings: Settings,
    *,
    id_token_value: str,
    nonce: str,
) -> dict[str, object]:
    return await asyncio.to_thread(
        verify_google_id_token,
        settings,
        id_token_value=id_token_value,
        nonce=nonce,
    )

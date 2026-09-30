import asyncio
import base64
import hashlib
import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import Settings, get_settings

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
DUMMY_PASSWORD_HASH = password_hasher.hash("not-a-real-user-password")
OAUTH_SERIALIZER_SALT = "academic-memo-google-oauth-v1"
CSRF_SERIALIZER_SALT = "academic-memo-csrf-v1"


class InvalidOAuthState(ValueError):
    """Raised when an OAuth state cookie is missing, invalid, or expired."""


class InvalidCsrfToken(ValueError):
    """Raised when a CSRF token is invalid or expired."""


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def verify_dummy_password(password: str) -> None:
    """Consume a hash for unknown accounts to reduce account-enumeration timing leaks."""
    try:
        password_hasher.verify(DUMMY_PASSWORD_HASH, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    return await asyncio.to_thread(verify_password, password_hash, password)


async def verify_dummy_password_async(password: str) -> None:
    await asyncio.to_thread(verify_dummy_password, password)


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    return secrets.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def oauth_serializer(settings: Settings | None = None) -> URLSafeTimedSerializer:
    active_settings = settings or get_settings()
    return URLSafeTimedSerializer(active_settings.secret_key, salt=OAUTH_SERIALIZER_SALT)


def dump_oauth_state(payload: dict[str, Any], settings: Settings | None = None) -> str:
    return oauth_serializer(settings).dumps(payload)


def dump_csrf_token(token: str, settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    return URLSafeTimedSerializer(
        active_settings.secret_key,
        salt=CSRF_SERIALIZER_SALT,
    ).dumps(token)


def load_csrf_token(
    serialized: str,
    max_age_seconds: int,
    settings: Settings | None = None,
) -> str:
    active_settings = settings or get_settings()
    try:
        token = URLSafeTimedSerializer(
            active_settings.secret_key,
            salt=CSRF_SERIALIZER_SALT,
        ).loads(serialized, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired) as exc:
        raise InvalidCsrfToken("CSRF token is invalid or expired.") from exc
    if not isinstance(token, str) or not token:
        raise InvalidCsrfToken("CSRF token has an invalid shape.")
    return token


def load_oauth_state(
    serialized: str,
    max_age_seconds: int,
    settings: Settings | None = None,
) -> dict[str, Any]:
    try:
        payload = oauth_serializer(settings).loads(
            serialized,
            max_age=max_age_seconds,
        )
    except (BadSignature, SignatureExpired) as exc:
        raise InvalidOAuthState("OAuth state is invalid or expired.") from exc

    if not isinstance(payload, dict):
        raise InvalidOAuthState("OAuth state has an invalid shape.")
    return payload

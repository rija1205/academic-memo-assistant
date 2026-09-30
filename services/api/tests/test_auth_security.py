import base64
import hashlib

import pytest

from app.auth.google_oauth import (
    GoogleOAuthError,
    build_google_authorization_url,
    verify_google_id_token,
)
from app.auth.security import (
    InvalidCsrfToken,
    InvalidOAuthState,
    create_pkce_pair,
    dump_csrf_token,
    dump_oauth_state,
    hash_password,
    hash_token,
    load_csrf_token,
    load_oauth_state,
    verify_dummy_password,
    verify_password,
)
from app.core.config import Settings


def test_passwords_are_hashed_with_a_one_way_hash() -> None:
    password_hash = hash_password("a-strong-password")

    assert password_hash != "a-strong-password"
    assert password_hash.startswith("$argon2")
    assert verify_password(password_hash, "a-strong-password")
    assert not verify_password(password_hash, "wrong-password")


def test_dummy_password_verification_does_not_raise_for_wrong_input() -> None:
    verify_dummy_password("wrong-password")


def test_csrf_token_is_signed_and_validated() -> None:
    settings = Settings(secret_key="test-secret-that-is-long-enough")
    serialized = dump_csrf_token("csrf-value", settings)

    assert load_csrf_token(serialized, 600, settings) == "csrf-value"
    with pytest.raises(InvalidCsrfToken):
        load_csrf_token(f"{serialized}tampered", 600, settings)


def test_session_and_reset_tokens_are_hashed() -> None:
    assert hash_token("raw-token") == hash_token("raw-token")
    assert len(hash_token("raw-token")) == 64
    assert hash_token("raw-token") != "raw-token"


def test_pkce_challenge_matches_verifier() -> None:
    verifier, challenge = create_pkce_pair()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")

    assert challenge == expected


def test_oauth_state_round_trip_and_expiry_validation() -> None:
    settings = Settings(secret_key="test-secret-that-is-long-enough")
    serialized = dump_oauth_state(
        {"state": "state-value", "nonce": "nonce-value", "verifier": "verifier"},
        settings,
    )

    assert load_oauth_state(serialized, 600, settings)["state"] == "state-value"

    try:
        load_oauth_state(serialized, -1, settings)
    except InvalidOAuthState:
        pass
    else:
        raise AssertionError("An expired OAuth state must be rejected.")


def test_google_authorization_url_contains_state_nonce_and_pkce() -> None:
    settings = Settings(
        secret_key="test-secret-that-is-long-enough",
        google_client_id="client-id",
        google_client_secret="client-secret",
    )

    url = build_google_authorization_url(
        settings,
        state="state-value",
        nonce="nonce-value",
        code_challenge="challenge-value",
    )

    assert "client-id" in url
    assert "state=state-value" in url
    assert "nonce=nonce-value" in url
    assert "code_challenge=challenge-value" in url
    assert "code_challenge_method=S256" in url
    assert "client-secret" not in url


def test_google_id_token_nonce_is_checked_after_library_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        secret_key="test-secret-that-is-long-enough",
        google_client_id="client-id",
        google_client_secret="client-secret",
    )

    def fake_verify(id_token_value, request, audience):
        assert id_token_value == "signed-id-token"
        assert audience == "client-id"
        return {"nonce": "expected-nonce", "sub": "subject"}

    monkeypatch.setattr(
        "app.auth.google_oauth.google_id_token.verify_oauth2_token",
        fake_verify,
    )

    claims = verify_google_id_token(
        settings,
        id_token_value="signed-id-token",
        nonce="expected-nonce",
    )
    assert claims["sub"] == "subject"

    with pytest.raises(GoogleOAuthError):
        verify_google_id_token(
            settings,
            id_token_value="signed-id-token",
            nonce="wrong-nonce",
        )

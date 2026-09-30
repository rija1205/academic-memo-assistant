import pytest

from app.core.config import Settings


def test_cors_origins_are_parsed() -> None:
    settings = Settings(cors_origins="http://localhost:3000, http://localhost:3001")

    assert settings.cors_origin_list == ["http://localhost:3000", "http://localhost:3001"]


def test_production_enables_secure_cookies() -> None:
    settings = Settings(
        app_env="production",
        secret_key="test-secret-that-is-long-enough-and-randomized",
        frontend_url="https://app.example.com",
        cors_origins="https://app.example.com",
        source_worker_token="test-worker-token",
        embedding_provider="openai",
        embedding_api_key="production-test-key",
        embedding_model="text-embedding-3-small",
        llm_provider="openai",
        llm_api_key="production-test-key",
    )

    assert settings.cookie_secure is True


def test_production_rejects_insecure_auth_configuration() -> None:
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            secret_key="replace-this-development-secret",
            frontend_url="https://app.example.com",
            cors_origins="https://app.example.com",
        )


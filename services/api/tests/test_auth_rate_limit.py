from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth.rate_limit import enforce_auth_rate_limit
from app.core.config import Settings


class FakeRedis:
    values: dict[str, int] = {}

    @classmethod
    def from_url(cls, *args, **kwargs):
        return cls()

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_auth_rate_limit_blocks_after_configured_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeRedis.values = {}
    monkeypatch.setattr("app.auth.rate_limit.Redis", FakeRedis)
    settings = Settings(
        secret_key="test-secret-that-is-long-enough",
        auth_rate_limit_enabled=True,
        auth_rate_limit_max_attempts=1,
        auth_rate_limit_window_seconds=600,
    )
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    await enforce_auth_rate_limit(request, identity="student@example.com", settings=settings)
    assert all("student@example.com" not in key for key in FakeRedis.values)
    with pytest.raises(HTTPException) as error:
        await enforce_auth_rate_limit(request, identity="student@example.com", settings=settings)

    assert error.value.status_code == 429

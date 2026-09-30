import hashlib

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def enforce_auth_rate_limit(
    request: Request,
    *,
    identity: str,
    settings: Settings,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return

    client_ip = request.client.host if request.client else "unknown"
    key = f"ama:auth:limit:{_fingerprint(f'{client_ip}:{identity.casefold()}')}"
    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, settings.auth_rate_limit_window_seconds)
        if count > settings.auth_rate_limit_max_attempts:
            retry_after = settings.auth_rate_limit_window_seconds
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many authentication attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
    except (RedisError, TimeoutError) as exc:
        if settings.app_env.casefold() == "production":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication protection is temporarily unavailable.",
            ) from exc
    finally:
        await redis.aclose()

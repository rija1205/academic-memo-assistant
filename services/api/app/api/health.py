import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine

router = APIRouter(tags=["health"])
settings = get_settings()


async def check_database() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def check_redis() -> bool:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        return bool(await client.ping())
    except Exception:
        return False
    finally:
        await client.aclose()


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.version,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get(
    "/health/ready",
    responses={503: {"description": "Une dépendance est indisponible."}},
)
async def health_ready() -> JSONResponse:
    try:
        database_ok, redis_ok = await asyncio.wait_for(
            asyncio.gather(check_database(), check_redis()),
            timeout=3,
        )
    except TimeoutError:
        database_ok, redis_ok = False, False
    ready = database_ok and redis_ok

    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "degraded",
            "service": settings.app_name,
            "dependencies": {
                "postgres": "ok" if database_ok else "unavailable",
                "redis": "ok" if redis_ok else "unavailable",
            },
        },
    )

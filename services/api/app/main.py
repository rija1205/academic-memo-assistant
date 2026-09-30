from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.observability.middleware import ObservabilityMiddleware

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Fondation API de l'assistant de mémoire académique.",
    docs_url="/docs" if settings.app_env.casefold() != "production" else None,
    redoc_url=None,
    # The schema itself is not published in production: an operator should not hand out a map
    # of the administrative surface.
    openapi_url="/openapi.json" if settings.app_env.casefold() != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "Retry-After"],
)

# Registered after CORS so it wraps it: the security headers must be present on the response
# even when the browser preflight is answered by the CORS middleware.
app.add_middleware(ObservabilityMiddleware, settings=settings)

app.include_router(api_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": settings.version,
        "status": "ok",
        "docs": "/docs",
        "health": "/health/ready",
        "metrics": "/api/observability/metrics",
    }

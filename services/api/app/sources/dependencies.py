from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings
from app.storage import StorageProvider, build_storage_provider


def get_source_storage(settings: Settings = Depends(get_settings)) -> StorageProvider:
    try:
        return build_storage_provider(settings)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Le stockage des sources est indisponible.",
        ) from exc


async def require_worker_token(
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.source_worker_token or x_worker_token != settings.source_worker_token:
        raise HTTPException(status_code=401, detail="Invalid worker token.")

from __future__ import annotations

from app.core.config import Settings
from app.storage.base import StorageError, StorageProvider
from app.storage.local import LocalStorageProvider
from app.storage.object_storage import ObjectStorageProvider


def build_storage_provider(settings: Settings) -> StorageProvider:
    if settings.source_storage_provider == "local":
        return LocalStorageProvider(settings.source_local_storage_path)
    if settings.source_storage_provider == "s3":
        if not settings.s3_endpoint_url:
            raise StorageError("S3_ENDPOINT_URL is required for the s3 provider.")
        return ObjectStorageProvider(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key=settings.s3_access_key or None,
            secret_key=settings.s3_secret_key or None,
        )
    raise StorageError("Unsupported storage provider.")

from __future__ import annotations

from typing import Any

from app.storage.base import StorageError, StoredObject


class ObjectStorageProvider:
    """S3-compatible provider for production (AWS S3, MinIO, and similar)."""

    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - dependency is declared in pyproject
            raise StorageError("boto3 is required for object storage.") from exc
        client_kwargs: dict[str, Any] = {"region_name": region}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key
        self._client = boto3.client("s3", **client_kwargs)

    def save(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except Exception as exc:  # pragma: no cover - provider-specific errors
            raise StorageError("Unable to write the source object.") from exc
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    def read(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except Exception as exc:  # pragma: no cover - provider-specific errors
            raise StorageError("Unable to read the source object.") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # pragma: no cover - provider-specific errors
            raise StorageError("Unable to delete the source object.") from exc

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:  # pragma: no cover - provider-specific errors
            return False

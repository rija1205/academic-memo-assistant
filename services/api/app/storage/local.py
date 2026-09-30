from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.storage.base import StorageError, StoredObject


class LocalStorageProvider:
    """Development storage provider that never trusts a caller-provided path."""

    name = "local"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        normalized = key.replace("\\", "/")
        candidate = (self._root / normalized).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise StorageError("Invalid storage key.") from exc
        return candidate

    def save(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        destination = self._path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent, delete=False
            ) as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            temporary_path.replace(destination)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise StorageError("Unable to write the source file.") from exc
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    def read(self, key: str) -> bytes:
        try:
            return self._path_for(key).read_bytes()
        except OSError as exc:
            raise StorageError("Unable to read the source file.") from exc

    def delete(self, key: str) -> None:
        try:
            self._path_for(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("Unable to delete the source file.") from exc

    def exists(self, key: str) -> bool:
        return self._path_for(key).is_file()

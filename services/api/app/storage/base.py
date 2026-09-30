from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class StorageError(RuntimeError):
    """Raised when a storage provider cannot complete an operation."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str


class StorageProvider(Protocol):
    """Provider-neutral contract for source binaries."""

    name: str

    def save(self, key: str, data: bytes, *, content_type: str) -> StoredObject: ...

    def read(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

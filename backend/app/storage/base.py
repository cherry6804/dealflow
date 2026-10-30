
"""Provider-neutral interface for private object storage."""

from __future__ import annotations

from typing import BinaryIO, Protocol, runtime_checkable


class StorageError(Exception):
    """Base exception for object storage failures."""


class InvalidStorageKeyError(StorageError, ValueError):
    """Raised when an object key is unsafe or invalid."""


class ObjectNotFoundError(StorageError, FileNotFoundError):
    """Raised when a requested object does not exist."""


@runtime_checkable
class ObjectStorage(Protocol):
    """Interface implemented by private object storage providers."""

    def put(self, key: str, source: BinaryIO) -> None:
        """Store the contents of a binary stream at the supplied key."""
        ...

    def open_read(self, key: str) -> BinaryIO:
        """Open an existing object for binary reading."""
        ...

    def exists(self, key: str) -> bool:
        """Return whether an object exists."""
        ...

    def delete(self, key: str) -> None:
        """Delete an object, raising ObjectNotFoundError if absent."""
        ...

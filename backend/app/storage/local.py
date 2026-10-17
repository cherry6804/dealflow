
"""Private local-filesystem implementation of object storage."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from app.storage.base import (
    InvalidStorageKeyError,
    ObjectNotFoundError,
    StorageError,
)


class LocalObjectStorage:
    """Store objects below a private root directory."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve_key(self, key: str) -> Path:
        """Resolve a relative POSIX-style key inside the storage root."""
        if not isinstance(key, str) or not key or "\x00" in key:
            raise InvalidStorageKeyError("A valid storage key is required.")

        # Keys are provider-neutral and always use forward slashes.
        if "\\" in key or key.startswith("/") or re.match(r"^[A-Za-z]:", key):
            raise InvalidStorageKeyError("The storage key must be relative.")

        parts = key.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise InvalidStorageKeyError("The storage key contains an unsafe path.")

        candidate = self._root.joinpath(*parts).resolve()

        if candidate == self._root or self._root not in candidate.parents:
            raise InvalidStorageKeyError("The storage key escapes the storage root.")

        return candidate

    def put(self, key: str, source: BinaryIO) -> None:
        """Write an object atomically without overwriting existing objects."""
        destination = self._resolve_key(key)
        destination.parent.mkdir(parents=True, exist_ok=True)

        # Recheck after creating directories to catch symlink-based escapes.
        destination = self._resolve_key(key)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=".object-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                shutil.copyfileobj(source, temporary, length=64 * 1024)
                temporary.flush()
                os.fsync(temporary.fileno())

            # "xb" semantics: do not silently overwrite an existing object.
            # A hard link publishes the complete temporary file atomically.
            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                raise StorageError("An object already exists at this key.")
            except OSError as exc:
                raise StorageError("The object could not be stored.") from exc

        except StorageError:
            raise
        except OSError as exc:
            raise StorageError("The object could not be stored.") from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def open_read(self, key: str) -> BinaryIO:
        """Open an object for reading."""
        path = self._resolve_key(key)

        try:
            return path.open("rb")
        except FileNotFoundError as exc:
            raise ObjectNotFoundError("The requested object does not exist.") from exc
        except IsADirectoryError as exc:
            raise ObjectNotFoundError("The requested object does not exist.") from exc
        except OSError as exc:
            raise StorageError("The object could not be read.") from exc

    def exists(self, key: str) -> bool:
        """Check for an existing regular file."""
        path = self._resolve_key(key)
        return path.is_file()

    def delete(self, key: str) -> None:
        """Delete an existing object without following an unsafe key."""
        path = self._resolve_key(key)

        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError("The requested object does not exist.") from exc
        except IsADirectoryError as exc:
            raise ObjectNotFoundError("The requested object does not exist.") from exc
        except OSError as exc:
            raise StorageError("The object could not be deleted.") from exc

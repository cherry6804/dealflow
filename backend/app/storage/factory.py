
"""Factory for configured object storage providers."""

from app.config import get_settings
from app.storage.base import StorageError
from app.storage.local import LocalObjectStorage


def get_object_storage() -> LocalObjectStorage:
    """Build the configured storage provider.

    The local provider is the first supported implementation. Future cloud
    providers can be selected here without changing business services.
    """
    settings = get_settings()
    backend = settings.object_storage_backend.strip().lower()

    if backend == "local":
        return LocalObjectStorage(settings.object_storage_dir)

    raise StorageError(
        f"Unsupported object storage backend: {backend!r}."
    )

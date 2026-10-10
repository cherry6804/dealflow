
"""Service-layer operations for DealFlow data imports."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.import_batch import ImportBatch
from app.imports.storage import (
    UploadTooLargeError,
    UploadValidationError,
    delete_stored_upload,
    store_upload,
)

logger = logging.getLogger(__name__)


def _cleanup_upload(storage_key: str) -> None:
    """Remove a stored file after its database transaction fails."""
    try:
        delete_stored_upload(storage_key)
    except Exception:
        # Preserve the original database error and report the cleanup failure.
        logger.exception(
            "Failed to clean up an import upload after a database error."
        )


async def upload_import_source(
    db: Session,
    *,
    organization_id: UUID,
    file: UploadFile,
) -> ImportBatch:
    """Store a validated source file and persist its import batch metadata.

    The organization ID must come from the verified tenant context.
    This operation stores the source file only; it does not process rows.
    """
    stored_upload = await store_upload(
        file,
        organization_id=organization_id,
    )

    import_batch = ImportBatch(
        organization_id=organization_id,
        source_filename=stored_upload.source_filename,
        source_format=stored_upload.source_format,
        content_type=stored_upload.content_type,
        file_size_bytes=stored_upload.file_size_bytes,
        status="pending",
        storage_backend=stored_upload.storage_backend,
        storage_key=stored_upload.storage_key,
    )

    try:
        db.add(import_batch)
        db.flush()
        db.refresh(import_batch)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        _cleanup_upload(stored_upload.storage_key)

        logger.exception(
            "Failed to persist an import batch for organization %s.",
            organization_id,
        )
        raise

    return import_batch


__all__ = [
    "UploadTooLargeError",
    "UploadValidationError",
    "upload_import_source",
]

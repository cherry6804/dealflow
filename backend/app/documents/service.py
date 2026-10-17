
"""Service-layer operations for private business document uploads."""

from __future__ import annotations

import hashlib
import logging
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import BinaryIO
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.document import Document
from app.storage import StorageError, get_object_storage

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024
SPOOL_MEMORY_LIMIT = 2 * 1024 * 1024

# Limits for ZIP-based Office documents (DOCX and XLSX).
MAX_OFFICE_ARCHIVE_ENTRIES = 5_000
MAX_OFFICE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_OFFICE_ENTRY_BYTES = 25 * 1024 * 1024
MAX_OFFICE_COMPRESSION_RATIO = 1_000

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".txt",
    ".csv",
    ".docx",
    ".xlsx",
}

PDF_SIGNATURE = b"%PDF-"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


class DocumentUploadError(Exception):
    """Base exception for document upload failures."""


class DocumentUploadValidationError(DocumentUploadError):
    """Raised when an uploaded document is invalid."""


class DocumentUploadTooLargeError(DocumentUploadError):
    """Raised when an uploaded document exceeds the configured size limit."""


def _sanitize_filename(filename: str | None) -> str:
    """Extract a bounded filename without path components or control characters."""
    if not filename:
        raise DocumentUploadValidationError("A filename is required.")

    normalized = filename.replace("\\", "/")
    basename = normalized.rsplit("/", maxsplit=1)[-1]
    basename = "".join(
        character
        for character in basename
        if character.isprintable() and character not in {"/", "\\"}
    ).strip()

    if not basename or basename in {".", ".."}:
        raise DocumentUploadValidationError("A valid filename is required.")

    if len(basename) > 255:
        raise DocumentUploadValidationError(
            "The filename must not exceed 255 characters."
        )

    extension = PurePosixPath(basename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise DocumentUploadValidationError(
            "Supported document formats are PDF, PNG, JPEG, TXT, CSV, DOCX, and XLSX."
        )

    return basename


def _validate_content(source: BinaryIO, extension: str) -> None:
    """Validate basic file signatures or structure without trusting the MIME header."""
    source.seek(0)
    prefix = source.read(16)
    source.seek(0)

    if extension == ".pdf":
        valid = prefix.startswith(PDF_SIGNATURE)

    elif extension == ".png":
        valid = prefix.startswith(PNG_SIGNATURE)

    elif extension in {".jpg", ".jpeg"}:
        valid = prefix.startswith(JPEG_SIGNATURE)

    elif extension in {".txt", ".csv"}:
        try:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break

                if b"\x00" in chunk:
                    raise DocumentUploadValidationError(
                        "Text documents must not contain binary null bytes."
                    )

                chunk.decode("utf-8-sig", errors="strict")

        except UnicodeDecodeError as exc:
            raise DocumentUploadValidationError(
                "Text documents must use UTF-8 encoding."
            ) from exc

        finally:
            source.seek(0)

        return

    elif extension in {".docx", ".xlsx"}:
        try:
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()

                if len(entries) > MAX_OFFICE_ARCHIVE_ENTRIES:
                    raise DocumentUploadValidationError(
                        "The Office document contains too many archive entries."
                    )

                total_uncompressed_size = 0
                names: set[str] = set()

                for entry in entries:
                    names.add(entry.filename)

                    if entry.flag_bits & 0x1:
                        raise DocumentUploadValidationError(
                            "Encrypted Office documents are not supported."
                        )

                    if entry.file_size < 0 or entry.compress_size < 0:
                        raise DocumentUploadValidationError(
                            "The Office document contains invalid archive metadata."
                        )

                    if entry.file_size > MAX_OFFICE_ENTRY_BYTES:
                        raise DocumentUploadValidationError(
                            "An Office document archive entry exceeds the size limit."
                        )

                    total_uncompressed_size += entry.file_size

                    if total_uncompressed_size > MAX_OFFICE_UNCOMPRESSED_BYTES:
                        raise DocumentUploadValidationError(
                            "The Office document expands beyond the permitted size."
                        )

                    if entry.file_size > 0:
                        if entry.compress_size == 0:
                            raise DocumentUploadValidationError(
                                "The Office document contains suspicious compressed data."
                            )

                        compression_ratio = (
                            entry.file_size / entry.compress_size
                        )

                        if compression_ratio > MAX_OFFICE_COMPRESSION_RATIO:
                            raise DocumentUploadValidationError(
                                "The Office document compression ratio exceeds the limit."
                            )

                if extension == ".docx":
                    valid = (
                        "[Content_Types].xml" in names
                        and "word/document.xml" in names
                    )
                else:
                    valid = (
                        "[Content_Types].xml" in names
                        and "xl/workbook.xml" in names
                    )

        except DocumentUploadValidationError:
            raise

        except (
            zipfile.BadZipFile,
            OSError,
            ValueError,
            RuntimeError,
        ) as exc:
            raise DocumentUploadValidationError(
                "The uploaded Office document is not a valid package."
            ) from exc

        finally:
            source.seek(0)

    else:
        valid = False

    if not valid:
        raise DocumentUploadValidationError(
            "The file content does not match its filename extension."
        )

    source.seek(0)


def _cleanup_stored_object(storage_key: str) -> None:
    """Attempt to remove a stored object without hiding the original failure."""
    try:
        get_object_storage().delete(storage_key)
    except Exception:
        logger.exception(
            "Failed to clean up document storage object %s after a database failure.",
            storage_key,
        )


async def upload_document(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    file: UploadFile,
    display_name: str | None = None,
    description: str | None = None,
    category: str = Document.CATEGORY_OTHER,
    document_type: str,
    access_classification: str = Document.CLASSIFICATION_INTERNAL,
) -> Document:
    """Validate, privately store, and persist a tenant-scoped document."""
    settings = get_settings()
    max_size = settings.upload_max_file_size_bytes

    if category not in Document.CATEGORIES:
        raise DocumentUploadValidationError("Unsupported document category.")

    if access_classification not in Document.ACCESS_CLASSIFICATIONS:
        raise DocumentUploadValidationError(
            "Unsupported document access classification."
        )

    normalized_type = document_type.strip()
    if not normalized_type or len(normalized_type) > 100:
        raise DocumentUploadValidationError(
            "Document type must contain 1 to 100 characters."
        )

    safe_filename = _sanitize_filename(file.filename)
    extension = PurePosixPath(safe_filename).suffix.lower()

    resolved_display_name = (display_name or "").strip() or safe_filename
    if len(resolved_display_name) > 255:
        raise DocumentUploadValidationError(
            "Display name must not exceed 255 characters."
        )

    if description is not None and not description.strip():
        description = None

    if description is not None and len(description) > 20_000:
        raise DocumentUploadValidationError(
            "Description must not exceed 20000 characters."
        )

    digest = hashlib.sha256()
    total_size = 0
    document_id = uuid.uuid4()

    # Spool large uploads to disk rather than retaining the whole file in RAM.
    with tempfile.SpooledTemporaryFile(
        max_size=SPOOL_MEMORY_LIMIT,
        mode="w+b",
    ) as staged_file:
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break

            total_size += len(chunk)

            if total_size > max_size:
                raise DocumentUploadTooLargeError(
                    f"The file exceeds the {max_size}-byte upload limit."
                )

            digest.update(chunk)
            staged_file.write(chunk)

        if total_size == 0:
            raise DocumentUploadValidationError("The uploaded file is empty.")

        staged_file.seek(0)
        _validate_content(staged_file, extension)
        staged_file.seek(0)

        # Keys are generated by the server; client filenames never become keys.
        storage_key = (
            f"{organization_id}/{document_id.hex}/{uuid.uuid4().hex}{extension}"
        )

        storage = get_object_storage()

        try:
            storage.put(storage_key, staged_file)

        except StorageError:
            logger.exception(
                "Document storage failed for organization %s.",
                organization_id,
            )
            raise DocumentUploadError(
                "The document could not be stored."
            ) from None

    content_type = (file.content_type or "").strip()[:255] or None
    now = datetime.now(timezone.utc)

    document = Document(
        id=document_id,
        organization_id=organization_id,
        original_filename=safe_filename,
        display_name=resolved_display_name,
        description=description,
        category=category,
        document_type=normalized_type,
        content_type=content_type,
        file_extension=extension,
        file_size_bytes=total_size,
        checksum_sha256=digest.hexdigest(),
        storage_backend=settings.object_storage_backend.strip().lower(),
        storage_key=storage_key,
        access_classification=access_classification,
        status=Document.STATUS_AVAILABLE,
        uploaded_by_user_id=user_id,
        created_by_user_id=user_id,
        uploaded_at=now,
    )

    try:
        db.add(document)
        db.flush()
        db.refresh(document)
        db.commit()

    except SQLAlchemyError:
        db.rollback()
        _cleanup_stored_object(storage_key)

        logger.exception(
            "Failed to persist document metadata for organization %s.",
            organization_id,
        )
        raise

    return document

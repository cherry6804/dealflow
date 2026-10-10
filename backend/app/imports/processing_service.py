"""Transactional processing for contact import batches."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.contacts.schemas import ContactCreateRequest
from app.contacts.service import create_contact
from app.db.models.import_batch import ImportBatch
from app.imports.preview import (
    ImportPreviewFileError,
    ImportPreviewNotFoundError,
    _safe_storage_path,
)
from app.imports.storage import UploadValidationError, validate_source_file
from app.imports.validation import validate_contact_rows
from app.imports.validation_service import (
    MAX_VALIDATION_ERRORS,
    ImportValidationFileError,
    ImportValidationMappingError,
    _iter_csv_rows,
    _iter_xlsx_rows,
    _normalize_source_row,
    _read_csv_headers,
    _resolve_column_mapping,
)

logger = logging.getLogger(__name__)


class ImportProcessingError(Exception):
    """Base exception for import-processing failures."""


class ImportProcessingNotFoundError(ImportProcessingError):
    """The requested batch is unavailable to this tenant."""


class ImportProcessingConflictError(ImportProcessingError):
    """The batch is not eligible for processing."""


class ImportProcessingFileError(ImportProcessingError):
    """The stored source file cannot be safely processed."""


class ImportProcessingMappingError(ImportProcessingError):
    """The source headers cannot be mapped to contact fields."""


def _resolve_source(
    batch: ImportBatch,
    organization_id: UUID,
) -> tuple[Path, str]:
    """Resolve and validate a batch's tenant-scoped source file."""
    try:
        path = _safe_storage_path(batch, organization_id)
    except ImportPreviewNotFoundError as exc:
        raise ImportProcessingNotFoundError(
            "Import batch not found."
        ) from exc
    except ImportPreviewFileError as exc:
        raise ImportProcessingFileError(str(exc)) from exc

    try:
        source_format = validate_source_file(path, batch.source_filename)
    except UploadValidationError as exc:
        raise ImportProcessingFileError(
            "The stored source file failed its format checks."
        ) from exc

    if source_format != batch.source_format:
        raise ImportProcessingFileError(
            "The stored file format does not match its import metadata."
        )

    return path, source_format


def _record_error(
    errors: list[dict[str, Any]],
    *,
    row_number: int,
    field: str,
    code: str,
    message: str,
    state: dict[str, bool],
) -> None:
    """Keep at most the configured number of error details."""
    if len(errors) < MAX_VALIDATION_ERRORS:
        errors.append(
            {
                "row_number": row_number,
                "field": field,
                "code": code,
                "message": message,
            }
        )
    else:
        state["truncated"] = True


def _process_rows(
    db: Session,
    *,
    organization_id: UUID,
    rows,
    mapping: dict[str, int],
) -> dict[str, Any]:
    """Create contacts for valid rows and retain bounded row errors."""
    total_rows = 0
    successful_rows = 0
    failed_rows = 0
    errors: list[dict[str, Any]] = []
    error_state = {"truncated": False}

    for row_number, raw_row in rows:
        total_rows += 1
        normalized_row = _normalize_source_row(raw_row, mapping)
        validation = validate_contact_rows([normalized_row])

        if validation["invalid_rows"]:
            failed_rows += 1
            for error in validation["errors"]:
                error["row_number"] = row_number
                _record_error(
                    errors,
                    row_number=row_number,
                    field=error["field"],
                    code=error["code"],
                    message=error["message"],
                    state=error_state,
                )
            continue

        payload = ContactCreateRequest(
            first_name=str(normalized_row["first_name"]).strip(),
            last_name=(
                str(normalized_row["last_name"]).strip() or None
                if normalized_row.get("last_name") is not None
                else None
            ),
            email=(
                str(normalized_row["email"]).strip() or None
                if normalized_row.get("email") is not None
                else None
            ),
            phone=(
                str(normalized_row["phone"]).strip() or None
                if normalized_row.get("phone") is not None
                else None
            ),
        )

        create_contact(
            db,
            organization_id=organization_id,
            payload=payload,
        )
        successful_rows += 1

    return {
        "total_rows": total_rows,
        "processed_rows": total_rows,
        "successful_rows": successful_rows,
        "failed_rows": failed_rows,
        "skipped_rows": failed_rows,
        "contacts_created": successful_rows,
        "errors": errors,
        "error_limit": MAX_VALIDATION_ERRORS,
        "errors_truncated": error_state["truncated"],
    }

def _read_and_process_source(
    db: Session,
    *,
    organization_id: UUID,
    path: Path,
    source_format: str,
) -> tuple[dict[str, Any], str | None]:
    """Read the complete source and process rows incrementally."""
    worksheet_name: str | None = None

    try:
        if source_format == "csv":
            headers = _read_csv_headers(path)
            mapping = _resolve_column_mapping(headers)
            rows = _iter_csv_rows(path)
            return (
                _process_rows(
                    db,
                    organization_id=organization_id,
                    rows=rows,
                    mapping=mapping,
                ),
                worksheet_name,
            )

        if source_format == "xlsx":
            workbook_rows = _iter_xlsx_rows(path)
            try:
                worksheet_name, headers, rows = next(workbook_rows)
                mapping = _resolve_column_mapping(headers)
                result = _process_rows(
                    db,
                    organization_id=organization_id,
                    rows=rows,
                    mapping=mapping,
                )
                return result, worksheet_name
            except StopIteration as exc:
                raise ImportProcessingFileError(
                    "The workbook has no worksheets."
                ) from exc
            finally:
                workbook_rows.close()

        raise ImportProcessingFileError(
            "This source file format is not supported."
        )

    except ImportValidationFileError as exc:
        raise ImportProcessingFileError(str(exc)) from exc
    except ImportValidationMappingError as exc:
        raise ImportProcessingMappingError(str(exc)) from exc


def process_import_batch(
    db: Session,
    *,
    organization_id: UUID,
    import_batch_id: UUID,
) -> dict[str, Any]:
    """Process one pending batch in a single database transaction.

    Valid rows create Contact records only. No Lead records or lead workflows
    are created or activated by this operation.
    """
    batch = db.scalar(
        select(ImportBatch)
        .where(
            ImportBatch.id == import_batch_id,
            ImportBatch.organization_id == organization_id,
        )
        .with_for_update()
    )

    if batch is None:
        raise ImportProcessingNotFoundError("Import batch not found.")

    if batch.status != "pending":
        raise ImportProcessingConflictError(
            "Only pending import batches can be processed."
        )

    batch.status = "processing"
    batch.started_at = datetime.now(UTC)
    batch.completed_at = None
    batch.total_rows = 0
    batch.processed_rows = 0
    batch.successful_rows = 0
    batch.failed_rows = 0
    batch.skipped_rows = 0
    batch.error_summary = None

    try:
        path, source_format = _resolve_source(batch, organization_id)
        result, worksheet_name = _read_and_process_source(
            db,
            organization_id=organization_id,
            path=path,
            source_format=source_format,
        )

        batch.total_rows = result["total_rows"]
        batch.processed_rows = result["processed_rows"]
        batch.successful_rows = result["successful_rows"]
        batch.failed_rows = result["failed_rows"]
        batch.skipped_rows = result["skipped_rows"]
        batch.status = (
            "completed_with_errors"
            if result["failed_rows"]
            else "completed"
        )
        batch.completed_at = datetime.now(UTC)

        if result["errors"]:
            batch.error_summary = json.dumps(
                {
                    "errors": result["errors"],
                    "error_limit": result["error_limit"],
                    "errors_truncated": result["errors_truncated"],
                }
            )

        db.flush()
        response = {
            "import_batch_id": batch.id,
            "source_filename": batch.source_filename,
            "source_format": source_format,
            "worksheet_name": worksheet_name,
            **result,
            "status": batch.status,
        }
        db.commit()
        return response

    except (
        ImportProcessingNotFoundError,
        ImportProcessingConflictError,
    ):
        db.rollback()
        raise
    except (
        ImportProcessingFileError,
        ImportProcessingMappingError,
        ImportValidationFileError,
        ImportValidationMappingError,
    ):
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception(
            "Database error while processing import batch %s.",
            import_batch_id,
        )
        raise
    except Exception:
        db.rollback()
        logger.exception(
            "Unexpected error while processing import batch %s.",
            import_batch_id,
        )
        raise


__all__ = [
    "ImportProcessingConflictError",
    "ImportProcessingError",
    "ImportProcessingFileError",
    "ImportProcessingMappingError",
    "ImportProcessingNotFoundError",
    "process_import_batch",
]
"""Retrieve persisted data-import results."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.import_batch import ImportBatch
from app.imports.schemas import ImportValidationErrorDetail
from app.imports.validation_service import MAX_VALIDATION_ERRORS


class ImportResultNotFoundError(Exception):
    """Raised when an import batch does not belong to the requested tenant."""


class ImportResultDataError(Exception):
    """Raised when persisted import-result details cannot be validated."""


def get_import_result(
    db: Session,
    *,
    organization_id: UUID,
    import_batch_id: UUID,
) -> dict[str, Any]:
    """Return persisted counts and row-level errors for a tenant's batch."""
    batch = db.scalar(
        select(ImportBatch).where(
            ImportBatch.id == import_batch_id,
            ImportBatch.organization_id == organization_id,
        )
    )

    if batch is None:
        raise ImportResultNotFoundError

    errors: list[dict[str, Any]] = []
    error_limit = MAX_VALIDATION_ERRORS
    errors_truncated = False

    if batch.error_summary:
        try:
            summary = json.loads(batch.error_summary)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ImportResultDataError(
                "The stored import error summary is invalid."
            ) from exc

        if not isinstance(summary, dict):
            raise ImportResultDataError(
                "The stored import error summary has an invalid structure."
            )

        stored_errors = summary.get("errors", [])
        if not isinstance(stored_errors, list):
            raise ImportResultDataError(
                "The stored import errors have an invalid structure."
            )

        try:
            errors = [
                ImportValidationErrorDetail.model_validate(error).model_dump()
                for error in stored_errors
            ]
        except (ValidationError, TypeError, ValueError) as exc:
            raise ImportResultDataError(
                "The stored import error entries are invalid."
            ) from exc

        stored_error_limit = summary.get(
            "error_limit",
            MAX_VALIDATION_ERRORS,
        )
        if (
            type(stored_error_limit) is not int
            or stored_error_limit < 0
        ):
            raise ImportResultDataError(
                "The stored import error limit is invalid."
            )
        error_limit = stored_error_limit

        stored_truncated = summary.get("errors_truncated", False)
        if not isinstance(stored_truncated, bool):
            raise ImportResultDataError(
                "The stored import truncation flag is invalid."
            )
        errors_truncated = stored_truncated

    return {
        "import_batch_id": batch.id,
        "source_filename": batch.source_filename,
        "source_format": batch.source_format,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "processed_rows": batch.processed_rows,
        "successful_rows": batch.successful_rows,
        "failed_rows": batch.failed_rows,
        "skipped_rows": batch.skipped_rows,
        "contacts_created": batch.successful_rows,
        "errors": errors,
        "error_limit": error_limit,
        "errors_truncated": errors_truncated,
    }
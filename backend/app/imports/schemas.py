"""Pydantic schemas for data import APIs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ImportBatchResponse(BaseModel):
    """Safe public representation of an import batch."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    source_filename: str
    source_format: str
    content_type: str | None
    file_size_bytes: int | None
    status: str
    total_rows: int
    processed_rows: int
    successful_rows: int
    failed_rows: int
    skipped_rows: int
    created_at: datetime
    updated_at: datetime


class ImportPreviewColumn(BaseModel):
    """A detected source column and its optional mapping suggestion."""

    index: int
    source_name: str
    display_name: str
    suggested_field: str | None


class ImportPreviewTargetField(BaseModel):
    """A supported destination field for mapping."""

    value: str
    label: str


class ImportPreviewResponse(BaseModel):
    """Read-only preview of an uploaded import source."""

    import_batch_id: UUID
    source_filename: str
    source_format: str
    worksheet_name: str | None
    columns: list[ImportPreviewColumn]
    suggested_target_fields: list[ImportPreviewTargetField]
    preview_rows: list[dict[str, Any]]
    preview_row_limit: int
    has_more_rows: bool
    contacts_created: int


class ImportValidationErrorDetail(BaseModel):
    """A single source-row validation error."""

    row_number: int
    field: str
    code: str
    message: str


class ImportValidationResponse(BaseModel):
    """Read-only validation results for an uploaded import source."""

    import_batch_id: UUID
    source_filename: str
    source_format: str
    worksheet_name: str | None
    total_rows: int
    valid_rows: int
    invalid_rows: int
    errors: list[ImportValidationErrorDetail]
    error_limit: int
    errors_truncated: bool
    contacts_created: int

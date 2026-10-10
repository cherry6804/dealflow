"""Pydantic schemas for data import APIs."""

from datetime import datetime
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
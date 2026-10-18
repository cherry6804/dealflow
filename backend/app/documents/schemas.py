
"""Pydantic schemas for document upload responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """Safe metadata returned after a document upload."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    original_filename: str
    display_name: str
    description: str | None
    category: str
    document_type: str
    content_type: str | None
    file_extension: str | None
    file_size_bytes: int | None
    checksum_sha256: str | None
    access_classification: str
    status: str
    uploaded_by_user_id: UUID | None
    uploaded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    """Paginated document metadata for the current organization."""

    items: list[DocumentResponse]
    page: int
    page_size: int
    total: int
    total_pages: int

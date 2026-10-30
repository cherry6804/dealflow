
"""Pydantic schemas for business document APIs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class DocumentResponse(BaseModel):
    """Safe metadata returned for a business document."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    lead_id: UUID | None
    property_id: UUID | None
    deal_id: UUID | None
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


class DocumentAssociationRequest(BaseModel):
    """Link a document to one business record, or unlink it."""

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["lead", "property", "deal"] | None
    record_id: UUID | None

    @model_validator(mode="after")
    def validate_record_pair(self) -> "DocumentAssociationRequest":
        """Require both association values or neither."""
        if (self.record_type is None) != (self.record_id is None):
            raise ValueError(
                "record_type and record_id must both be provided or both be null."
            )
        return self

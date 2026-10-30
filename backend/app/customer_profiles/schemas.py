"""Pydantic schemas for the DealFlow Customer Profile API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CustomerProfileCreateRequest(BaseModel):
    """Register an existing Contact as a Customer."""

    contact_id: UUID
    customer_notes: str | None = Field(default=None, max_length=2000)


class CustomerProfileUpdateRequest(BaseModel):
    """Partially update a Customer Profile."""

    customer_notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class CustomerProfileReplaceRequest(BaseModel):
    """Replace the editable fields of a Customer Profile."""

    customer_notes: str | None = Field(max_length=2000)
    is_active: bool


class CustomerProfileContactResponse(BaseModel):
    """Contact information associated with a Customer Profile."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str | None
    email: str | None
    phone: str | None
    is_active: bool


class CustomerProfileResponse(BaseModel):
    """Response representation of a Customer Profile."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    contact_id: UUID
    is_active: bool
    customer_notes: str | None
    created_at: datetime
    updated_at: datetime
    contact: CustomerProfileContactResponse


class CustomerProfileListResponse(BaseModel):
    """Paginated response representation of Customer Profiles."""

    items: list[CustomerProfileResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
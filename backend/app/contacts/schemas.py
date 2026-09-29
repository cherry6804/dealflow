"""Pydantic schemas for the DealFlow Contact API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContactCreateRequest(BaseModel):
    """Request payload for creating a Contact."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)


class ContactUpdateRequest(BaseModel):
    """Request payload for partially updating a Contact."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None


class ContactResponse(BaseModel):
    """Response representation of a Contact."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    first_name: str
    last_name: str | None
    email: str | None
    phone: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ContactListQuery(BaseModel):
    """Query parameters for listing and searching Contacts."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    search: str | None = Field(default=None, min_length=1, max_length=320)
    is_active: bool | None = None


class ContactListResponse(BaseModel):
    """Paginated response representation of Contacts."""

    items: list[ContactResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
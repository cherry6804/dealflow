"""Pydantic schemas for the DealFlow Contact API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContactCreateRequest(BaseModel):
    """Request payload for creating a Contact."""

    first_name: str = Field(
        min_length=1,
        max_length=100,
    )
    last_name: str | None = Field(
        default=None,
        max_length=100,
    )
    email: str | None = Field(
        default=None,
        max_length=320,
    )
    phone: str | None = Field(
        default=None,
        max_length=50,
    )


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
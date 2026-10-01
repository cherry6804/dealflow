"""Pydantic schemas for Lead APIs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


LeadStatus = Literal[
    "NEW",
    "CONTACTED",
    "QUALIFIED",
    "MATCHING",
    "VISIT",
    "NEGOTIATION",
    "WON",
    "LOST",
    "ON_HOLD",
]

LeadInterest = Literal["LOW", "MEDIUM", "HIGH"]

LeadOutcome = Literal["SUCCESSFUL", "UNSUCCESSFUL"]


class LeadCreateRequest(BaseModel):
    """Request payload for creating a Lead."""

    contact_id: UUID
    interest: LeadInterest | None = None
    outcome: LeadOutcome | None = None
    next_action: str | None = Field(default=None, max_length=500)
    next_action_at: datetime | None = None


class LeadResponse(BaseModel):
    """API response representation of a Lead."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    contact_id: UUID
    status: LeadStatus
    interest: LeadInterest | None
    outcome: LeadOutcome | None
    owner_user_id: UUID | None
    next_action: str | None
    next_action_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LeadListQuery(BaseModel):
    """Query parameters for listing, searching, and filtering Leads."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    search: str | None = Field(default=None, min_length=1, max_length=320)
    status: LeadStatus | None = None
    interest: LeadInterest | None = None
    outcome: LeadOutcome | None = None
    owner_user_id: UUID | None = None
    is_active: bool | None = None


class LeadListResponse(BaseModel):
    """Paginated response representation of Leads."""

    items: list[LeadResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
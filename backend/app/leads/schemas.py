"""Pydantic schemas for Lead APIs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    status: str
    interest: LeadInterest | None
    outcome: LeadOutcome | None
    owner_user_id: UUID | None
    next_action: str | None
    next_action_at: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
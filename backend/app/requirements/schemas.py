"""Customer requirement API schemas for DealFlow."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


RequirementStatus = Literal["ACTIVE", "INACTIVE"]


class CustomerRequirementCreateRequest(BaseModel):
    """Request body for creating a customer requirement."""

    model_config = ConfigDict(extra="forbid")


class CustomerRequirementResponse(BaseModel):
    """Response representation of a customer requirement."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    status: RequirementStatus
    is_active: bool
    created_at: datetime
    updated_at: datetime
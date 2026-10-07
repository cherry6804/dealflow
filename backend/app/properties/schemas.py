"""Pydantic schemas for DealFlow Property APIs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PropertyCreateRequest(BaseModel):
    """Request payload for creating a Property.

    Organization ownership is intentionally excluded. The tenant context
    determines the organization that owns the Property.
    """


class PropertyResponse(BaseModel):
    """API response representation of a Property."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime
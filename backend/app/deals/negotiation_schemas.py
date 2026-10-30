
"""Pydantic schemas for deal negotiation state and history."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NegotiationState(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_ON_CUSTOMER = "WAITING_ON_CUSTOMER"
    WAITING_ON_SELLER = "WAITING_ON_SELLER"
    TERMS_AGREED = "TERMS_AGREED"
    STALLED = "STALLED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class NegotiationCreateRequest(BaseModel):
    """Create the initial negotiation state."""

    model_config = ConfigDict(extra="forbid")

    state: NegotiationState = NegotiationState.IN_PROGRESS
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class NegotiationUpdateRequest(BaseModel):
    """Change the current negotiation state."""

    model_config = ConfigDict(extra="forbid")

    state: NegotiationState
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class NegotiationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    deal_id: UUID
    state: NegotiationState
    updated_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class NegotiationHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    negotiation_id: UUID
    from_state: NegotiationState | None
    to_state: NegotiationState
    actor_user_id: UUID
    note: str | None
    created_at: datetime


class NegotiationHistoryListResponse(BaseModel):
    items: list[NegotiationHistoryResponse]
    total: int

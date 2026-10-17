
"""Pydantic schemas for DealFlow deals."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DealStage(str, Enum):
    NEW = "NEW"
    QUALIFICATION = "QUALIFICATION"
    NEGOTIATION = "NEGOTIATION"
    BOOKING = "BOOKING"
    CLOSED_WON = "CLOSED_WON"
    CLOSED_LOST = "CLOSED_LOST"


class DealCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_profile_id: UUID
    property_id: UUID
    lead_id: UUID | None = None
    owner_user_id: UUID | None = None
    stage: DealStage = DealStage.NEW
    expected_value: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter currency code.")
        return normalized

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class DealStageTransitionRequest(BaseModel):
    """Request to progress a deal to its next permitted workflow stage."""

    model_config = ConfigDict(extra="forbid")

    stage: DealStage
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class DealStageHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    deal_id: UUID
    from_stage: str
    to_stage: str
    actor_user_id: UUID | None
    reason: str | None
    created_at: datetime


class DealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    customer_profile_id: UUID
    property_id: UUID
    lead_id: UUID | None
    owner_user_id: UUID
    owner_name: str | None = None
    stage: str
    expected_value: Decimal | None
    currency: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DealListResponse(BaseModel):
    items: list[DealResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

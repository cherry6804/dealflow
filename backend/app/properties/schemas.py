"""Pydantic schemas for DealFlow Property APIs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PropertyCreateRequest(BaseModel):
    """Request payload for creating a Property.

    Organization ownership is intentionally excluded. The tenant context
    determines the organization that owns the Property.
    """


class PropertyCommercialUpdateRequest(BaseModel):
    """Request payload for updating Property commercial fields."""

    transaction_type: Literal["SALE", "RENT", "LEASE"]
    price: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(min_length=3, max_length=3)
    rent: Decimal | None = Field(default=None, ge=0)
    security_deposit: Decimal | None = Field(default=None, ge=0)
    maintenance_charge: Decimal | None = Field(default=None, ge=0)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        """Normalize and validate the three-character currency code."""

        normalized = value.strip().upper()

        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Currency must be a three-letter alphabetic code.")

        return normalized


class PropertyResponse(BaseModel):
    """API response representation of a Property."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime


class PropertyCommercialResponse(PropertyResponse):
    """API response representation including commercial fields."""

    transaction_type: str | None
    price: Decimal | None
    currency: str | None
    rent: Decimal | None
    security_deposit: Decimal | None
    maintenance_charge: Decimal | None
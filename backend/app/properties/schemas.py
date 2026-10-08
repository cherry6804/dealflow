"""Pydantic schemas for DealFlow Property APIs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


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


class PropertyLocationAttributesUpdateRequest(BaseModel):
    """Request payload for updating Property location and attributes.

    The endpoint is a PATCH operation. Fields omitted from the request are
    left unchanged. Explicit null values clear the corresponding nullable
    property field.
    """

    address_line_1: str | None = None
    address_line_2: str | None = None
    locality: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None

    property_type: Literal[
        "APARTMENT",
        "VILLA",
        "INDEPENDENT_HOUSE",
        "PLOT",
        "COMMERCIAL",
        "OTHER",
    ] | None = None

    bhk: int | None = Field(
        default=None,
        ge=1,
    )

    built_up_area: Decimal | None = Field(
        default=None,
        ge=0,
    )

    carpet_area: Decimal | None = Field(
        default=None,
        ge=0,
    )

    floor_number: int | None = Field(
        default=None,
        ge=0,
    )

    total_floors: int | None = Field(
        default=None,
        gt=0,
    )

    @field_validator(
        "address_line_1",
        "address_line_2",
        "locality",
        "city",
        "state",
        "postal_code",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """Trim optional location text values."""

        if value is None:
            return None

        normalized = value.strip()

        return normalized or None

    @model_validator(mode="after")
    def validate_floor_relationship(
        self,
    ) -> "PropertyLocationAttributesUpdateRequest":
        """Validate floor relationship when both values are supplied."""

        if (
            self.floor_number is not None
            and self.total_floors is not None
            and self.floor_number > self.total_floors
        ):
            raise ValueError(
                "Floor number cannot be greater than total floors."
            )

        return self


# ------------------------------------------------------------------
# DF-154: Availability and status
# ------------------------------------------------------------------


class PropertyStatusUpdateRequest(BaseModel):
    """Request payload for updating Property availability status."""

    status: Literal[
        "AVAILABLE",
        "RESERVED",
        "SOLD",
        "RENTED",
        "LEASED",
        "UNAVAILABLE",
    ]


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


class PropertyLocationAttributesResponse(PropertyResponse):
    """API response representation including location and attributes."""

    address_line_1: str | None
    address_line_2: str | None
    locality: str | None
    city: str | None
    state: str | None
    postal_code: str | None

    property_type: str | None
    bhk: int | None
    built_up_area: Decimal | None
    carpet_area: Decimal | None
    floor_number: int | None
    total_floors: int | None


class PropertyStatusResponse(PropertyResponse):
    """API response representation including availability status."""

    status: str | None
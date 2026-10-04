"""Customer requirement API schemas for DealFlow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RequirementStatus = Literal["ACTIVE", "INACTIVE"]


class CustomerRequirementCreateRequest(BaseModel):
    """Request body for creating a customer requirement."""

    model_config = ConfigDict(extra="forbid")


class CustomerRequirementUpdateRequest(BaseModel):
    """Request body for updating customer requirement budget information."""

    model_config = ConfigDict(extra="forbid")

    budget_min: Decimal | None = Field(default=None, ge=0)
    budget_max: Decimal | None = Field(default=None, ge=0)
    budget_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
    )

    @field_validator("budget_currency")
    @classmethod
    def validate_budget_currency(cls, value: str | None) -> str | None:
        """Normalize and validate the budget currency code."""

        if value is None:
            return None

        normalized = value.strip().upper()

        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Budget currency must be a three-letter code.")

        return normalized

    @model_validator(mode="after")
    def validate_budget_range(self) -> "CustomerRequirementUpdateRequest":
        """Validate the range when both budget values are supplied."""

        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_min > self.budget_max
        ):
            raise ValueError(
                "Budget minimum cannot be greater than budget maximum."
            )

        return self


class CustomerRequirementResponse(BaseModel):
    """Response representation of a customer requirement."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    status: RequirementStatus
    is_active: bool
    budget_min: Decimal | None
    budget_max: Decimal | None
    budget_currency: str | None
    created_at: datetime
    updated_at: datetime
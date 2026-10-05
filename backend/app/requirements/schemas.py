from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RequirementStatus = Literal["ACTIVE", "INACTIVE"]

PropertyType = Literal[
    "APARTMENT",
    "VILLA",
    "INDEPENDENT_HOUSE",
    "PLOT",
    "COMMERCIAL",
    "OTHER",
]


class CustomerRequirementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CustomerRequirementResponse(BaseModel):
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


class CustomerRequirementUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RequirementStatus | None = None
    is_active: bool | None = None

    budget_min: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        max_digits=18,
        decimal_places=2,
    )
    budget_max: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        max_digits=18,
        decimal_places=2,
    )
    budget_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
    )

    @field_validator("budget_currency")
    @classmethod
    def validate_budget_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip().upper()

        if len(normalized) != 3:
            raise ValueError("Budget currency must be a 3-character code.")

        if not normalized.isalpha():
            raise ValueError(
                "Budget currency must be a 3-letter alphabetic code."
            )

        return normalized

    @model_validator(mode="after")
    def validate_budget_range(self) -> "CustomerRequirementUpdateRequest":
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError(
                    "Budget minimum cannot be greater than budget maximum."
                )

        return self


class CustomerRequirementBudgetUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_min: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        max_digits=18,
        decimal_places=2,
    )
    budget_max: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        max_digits=18,
        decimal_places=2,
    )
    budget_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
    )

    @field_validator("budget_currency")
    @classmethod
    def validate_budget_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip().upper()

        if len(normalized) != 3:
            raise ValueError("Budget currency must be a 3-character code.")

        if not normalized.isalpha():
            raise ValueError(
                "Budget currency must be a 3-letter alphabetic code."
            )

        return normalized

    @model_validator(mode="after")
    def validate_budget_range(self) -> "CustomerRequirementBudgetUpdateRequest":
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError(
                    "Budget minimum cannot be greater than budget maximum."
                )

        has_budget = (
            self.budget_min is not None
            or self.budget_max is not None
        )

        if has_budget and self.budget_currency is None:
            raise ValueError(
                "Budget currency is required when budget is provided."
            )

        if (
            self.budget_currency is not None
            and self.budget_min is None
            and self.budget_max is None
        ):
            raise ValueError(
                "Budget minimum or maximum is required when budget currency is provided."
            )

        return self


class CustomerRequirementBudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    budget_min: Decimal | None
    budget_max: Decimal | None
    budget_currency: str | None
    updated_at: datetime


class CustomerRequirementLocationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str = Field(min_length=1, max_length=150)
    locality: str = Field(min_length=1, max_length=200)

    @field_validator("city", "locality")
    @classmethod
    def validate_location_text(cls, value: str) -> str:
        normalized = value.strip()

        if not normalized:
            raise ValueError("Location value cannot be blank.")

        return normalized


class CustomerRequirementLocationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
    )
    locality: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    is_active: bool | None = None

    @field_validator("city", "locality", mode="before")
    @classmethod
    def validate_location_text(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            raise ValueError("Location value cannot be null.")

        normalized = value.strip()

        if not normalized:
            raise ValueError("Location value cannot be blank.")

        return normalized


class CustomerRequirementLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    customer_requirement_id: UUID
    city: str
    locality: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerRequirementPropertyPreferenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_type: PropertyType

    bhk_min: int | None = Field(
        default=None,
        gt=0,
    )
    bhk_max: int | None = Field(
        default=None,
        gt=0,
    )

    @model_validator(mode="after")
    def validate_bhk_range(
        self,
    ) -> "CustomerRequirementPropertyPreferenceCreateRequest":
        if self.bhk_min is not None and self.bhk_max is not None:
            if self.bhk_min > self.bhk_max:
                raise ValueError(
                    "BHK minimum cannot be greater than BHK maximum."
                )

        return self


class CustomerRequirementPropertyPreferenceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_type: PropertyType | None = None

    bhk_min: int | None = Field(
        default=None,
        gt=0,
    )
    bhk_max: int | None = Field(
        default=None,
        gt=0,
    )
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_bhk_range(
        self,
    ) -> "CustomerRequirementPropertyPreferenceUpdateRequest":
        if self.bhk_min is not None and self.bhk_max is not None:
            if self.bhk_min > self.bhk_max:
                raise ValueError(
                    "BHK minimum cannot be greater than BHK maximum."
                )

        return self


class CustomerRequirementPropertyPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    customer_requirement_id: UUID
    property_type: PropertyType
    bhk_min: int | None
    bhk_max: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
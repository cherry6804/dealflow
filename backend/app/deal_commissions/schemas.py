"""Pydantic schemas for deal commission management."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class DealCommissionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commission_type: str
    fixed_amount: Decimal | None = Field(
        default=None, gt=0, max_digits=20, decimal_places=2
    )
    rate_percent: Decimal | None = Field(
        default=None, gt=0, le=100, max_digits=7, decimal_places=4
    )
    currency: str = Field(default="INR", min_length=3, max_length=3)
    terms: str | None = Field(default=None, max_length=10000)

    @field_validator("commission_type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in {"FIXED", "PERCENTAGE"}:
            raise ValueError("Commission type must be FIXED or PERCENTAGE.")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("Currency must be a three-letter currency code.")
        return value

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_commission_value(self) -> DealCommissionCreateRequest:
        if self.commission_type == "FIXED":
            if self.fixed_amount is None or self.rate_percent is not None:
                raise ValueError(
                    "FIXED commissions require fixed_amount and forbid rate_percent."
                )
        elif self.rate_percent is None or self.fixed_amount is not None:
            raise ValueError(
                "PERCENTAGE commissions require rate_percent and forbid fixed_amount."
            )
        return self


class DealCommissionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commission_type: str | None = None
    fixed_amount: Decimal | None = Field(
        default=None, gt=0, max_digits=20, decimal_places=2
    )
    rate_percent: Decimal | None = Field(
        default=None, gt=0, le=100, max_digits=7, decimal_places=4
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    terms: str | None = Field(default=None, max_length=10000)

    @field_validator("commission_type")
    @classmethod
    def validate_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if value not in {"FIXED", "PERCENTAGE"}:
            raise ValueError("Commission type must be FIXED or PERCENTAGE.")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("Currency must be a three-letter currency code.")
        return value

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def require_update_fields(self) -> DealCommissionUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        return self


class DealCommissionPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_reference: str | None = Field(default=None, max_length=200)

    @field_validator("payment_reference")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class DealCommissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    deal_id: UUID
    commission_type: str
    fixed_amount: Decimal | None
    rate_percent: Decimal | None
    currency: str
    status: str
    terms: str | None
    agreed_at: datetime | None
    paid_at: datetime | None
    payment_reference: str | None
    created_by_user_id: UUID | None
    updated_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

    # Populated by the API using the deal's expected value.
    calculated_amount: Decimal | None = None


class DealCommissionListResponse(BaseModel):
    items: list[DealCommissionResponse]
    total: int

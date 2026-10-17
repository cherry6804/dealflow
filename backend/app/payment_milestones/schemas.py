
"""Pydantic schemas for deal payment milestones."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class PaymentMilestoneCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=2)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    due_at: datetime
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Milestone name cannot be blank.")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("Currency must be a three-letter currency code.")
        return value

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("due_at must include a timezone.")
        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class PaymentMilestoneUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=150)
    amount: Decimal | None = Field(
        default=None, gt=0, max_digits=20, decimal_places=2
    )
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    due_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Milestone name cannot be blank.")
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

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("due_at must include a timezone.")
        return value

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_update_fields(self) -> PaymentMilestoneUpdateRequest:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        return self


class PaymentMilestoneMarkPaidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_reference: str | None = Field(default=None, max_length=200)

    @field_validator("payment_reference")
    @classmethod
    def normalize_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class PaymentMilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    deal_id: UUID
    name: str
    amount: Decimal
    currency: str
    due_at: datetime
    notes: str | None
    status: str
    paid_at: datetime | None
    payment_reference: str | None
    paid_by_user_id: UUID | None
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def is_overdue(self) -> bool:
        """Return whether an unpaid milestone has passed its due date."""
        if self.status != "PENDING":
            return False

        due_at = self.due_at
        if due_at.tzinfo is None or due_at.utcoffset() is None:
            due_at = due_at.replace(tzinfo=timezone.utc)

        return due_at < datetime.now(timezone.utc)


class PaymentMilestoneListResponse(BaseModel):
    items: list[PaymentMilestoneResponse]
    total: int

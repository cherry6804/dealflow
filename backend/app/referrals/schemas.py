
"""Pydantic schemas for referral management."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


ReferralStatus = Literal["NEW", "CONTACTED", "CONVERTED", "NOT_CONVERTED"]

_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _normalize_optional_text(value: str | None) -> str | None:
    """Trim optional text and convert blank strings to None."""
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def _validate_email(value: str | None) -> str | None:
    """Normalize an optional email and validate its basic format."""
    normalized = _normalize_optional_text(value)

    if normalized is None:
        return None

    if len(normalized) > 254 or not _EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("Enter a valid email address.")

    return normalized


class ReferralCreateRequest(BaseModel):
    """Fields required to create a referral."""

    model_config = ConfigDict(extra="forbid")

    referral_name: str = Field(min_length=1, max_length=200)
    referral_phone: str | None = Field(default=None, max_length=50)
    referral_email: str | None = Field(default=None, max_length=254)
    customer_profile_id: UUID | None = None
    referrer_contact_id: UUID | None = None
    deal_id: UUID | None = None
    status: ReferralStatus = "NEW"
    notes: str | None = Field(default=None, max_length=10000)

    @field_validator("referral_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """Trim the referral name and reject blank values."""
        value = value.strip()

        if not value:
            raise ValueError("Referral name cannot be blank.")

        return value

    @field_validator("referral_phone", "notes")
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        """Normalize optional text fields."""
        return _normalize_optional_text(value)

    @field_validator("referral_email")
    @classmethod
    def validate_referral_email(cls, value: str | None) -> str | None:
        """Validate the optional referral email."""
        return _validate_email(value)

    @model_validator(mode="after")
    def require_association(self) -> ReferralCreateRequest:
        """Require an association with a customer, contact, or deal."""
        if not any(
            (
                self.customer_profile_id,
                self.referrer_contact_id,
                self.deal_id,
            )
        ):
            raise ValueError(
                "Associate the referral with a customer, referring contact, or deal."
            )

        return self


class ReferralUpdateRequest(BaseModel):
    """Fields that may be changed on an existing referral."""

    model_config = ConfigDict(extra="forbid")

    referral_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
    )
    referral_phone: str | None = Field(default=None, max_length=50)
    referral_email: str | None = Field(default=None, max_length=254)
    customer_profile_id: UUID | None = None
    referrer_contact_id: UUID | None = None
    deal_id: UUID | None = None
    status: ReferralStatus | None = None
    notes: str | None = Field(default=None, max_length=10000)

    @field_validator("referral_name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        """Trim the referral name and reject blank values."""
        if value is None:
            return None

        value = value.strip()

        if not value:
            raise ValueError("Referral name cannot be blank.")

        return value

    @field_validator("referral_phone", "notes")
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        """Normalize optional text fields."""
        return _normalize_optional_text(value)

    @field_validator("referral_email")
    @classmethod
    def validate_referral_email(cls, value: str | None) -> str | None:
        """Validate the optional referral email."""
        return _validate_email(value)

    @model_validator(mode="after")
    def require_update_fields(self) -> ReferralUpdateRequest:
        """Reject requests that do not provide any update fields."""
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")

        return self


class ReferralResponse(BaseModel):
    """Referral returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    customer_profile_id: UUID | None
    referrer_contact_id: UUID | None
    deal_id: UUID | None
    referral_name: str
    referral_phone: str | None
    referral_email: str | None
    status: str
    notes: str | None
    created_by_user_id: UUID | None
    updated_by_user_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ReferralListResponse(BaseModel):
    """Paginated referral listing."""

    items: list[ReferralResponse]
    total: int
    page: int
    page_size: int

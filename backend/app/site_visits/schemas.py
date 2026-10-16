"""Pydantic schemas for DealFlow site visits."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SiteVisitCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    lead_id: UUID | None = None
    customer_profile_id: UUID | None = None
    owner_user_id: UUID | None = None
    scheduled_at: datetime
    ends_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def validate_customer_reference(self):
        if self.lead_id is None and self.customer_profile_id is None:
            raise ValueError("Either lead_id or customer_profile_id must be provided.")
        if self.lead_id is not None and self.customer_profile_id is not None:
            raise ValueError("Provide either lead_id or customer_profile_id, not both.")
        return self

    @field_validator("scheduled_at", "ends_at")
    @classmethod
    def validate_timezone(cls, value: datetime | None):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Visit date and time must include a timezone.")
        return value

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.ends_at is not None and self.ends_at <= self.scheduled_at:
            raise ValueError("ends_at must be later than scheduled_at.")
        return self

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: str | None):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SiteVisitAttendanceRequest(BaseModel):
    """Record attendance, customer outcome, and feedback for a site visit."""

    model_config = ConfigDict(extra="forbid")

    status: str
    outcome: str | None = None
    feedback: str | None = Field(default=None, max_length=10000)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        allowed = {"COMPLETED", "CANCELLED", "NO_SHOW"}
        if value not in allowed:
            raise ValueError(
                "Status must be COMPLETED, CANCELLED, or NO_SHOW."
            )
        return value

    @field_validator("outcome")
    @classmethod
    def validate_outcome(cls, value: str | None) -> str | None:
        allowed = {
            "INTERESTED",
            "NOT_INTERESTED",
            "NEGOTIATION",
            "FOLLOW_UP_REQUIRED",
            "OTHER",
        }
        if value is not None and value not in allowed:
            raise ValueError("Invalid site visit outcome.")
        return value

    @field_validator("feedback")
    @classmethod
    def normalize_feedback(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SiteVisitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    property_id: UUID
    lead_id: UUID | None
    customer_profile_id: UUID | None
    owner_user_id: UUID
    scheduled_at: datetime
    ends_at: datetime | None
    status: str
    outcome: str | None
    notes: str | None
    feedback: str | None
    created_at: datetime
    updated_at: datetime


class SiteVisitListResponse(BaseModel):
    items: list[SiteVisitResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

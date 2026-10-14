"""Pydantic schemas for DealFlow Follow-up APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


FollowUpType = Literal[
    "CALL",
    "EMAIL",
    "MEETING",
    "VISIT",
    "TASK",
    "OTHER",
]


class FollowUpCreateRequest(BaseModel):
    """Request payload for creating a follow-up on a lead."""

    model_config = ConfigDict(extra="forbid")

    follow_up_type: FollowUpType
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    due_at: datetime
    owner_user_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        """Reject titles containing only whitespace."""
        normalized = value.strip()

        if not normalized:
            raise ValueError("Follow-up title cannot be blank.")

        return normalized

    @field_validator("description")
    @classmethod
    def validate_description(
        cls,
        value: str | None,
    ) -> str | None:
        """Normalize optional descriptions."""
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware due date and time."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Follow-up due_at must include a timezone."
            )

        return value


class FollowUpResponse(BaseModel):
    """Response representation of a persisted follow-up."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    lead_id: UUID
    owner_user_id: UUID
    follow_up_type: FollowUpType
    title: str
    description: str | None
    due_at: datetime
    status: Literal["PENDING", "COMPLETED", "CANCELLED"]
    completed_at: datetime | None
    completed_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class FollowUpCompleteRequest(BaseModel):
    """Request payload for completing a follow-up."""

    model_config = ConfigDict(extra="forbid")


class FollowUpRescheduleRequest(BaseModel):
    """Request payload for rescheduling a follow-up."""

    model_config = ConfigDict(extra="forbid")

    due_at: datetime

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware rescheduled due date and time."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Follow-up due_at must include a timezone."
            )

        return value


class BulkFollowUpRequest(BaseModel):
    """Request to apply an operation to selected follow-ups."""

    model_config = ConfigDict(extra="forbid")

    follow_up_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("follow_up_ids")
    @classmethod
    def validate_follow_up_ids(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        """Reject duplicate IDs to avoid ambiguous results."""
        if len(value) != len(set(value)):
            raise ValueError(
                "Duplicate follow-up IDs are not allowed."
            )

        return value


class BulkFollowUpRescheduleRequest(BulkFollowUpRequest):
    """Request to reschedule selected follow-ups."""

    due_at: datetime

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware rescheduled due date and time."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Follow-up due_at must include a timezone."
            )

        return value


class BulkFollowUpItemResult(BaseModel):
    """Outcome for one follow-up in a bulk operation."""

    follow_up_id: UUID
    success: bool
    message: str
    follow_up: FollowUpResponse | None = None


class BulkFollowUpResponse(BaseModel):
    """Summary and individual outcomes for a bulk operation."""

    total: int
    succeeded: int
    failed: int
    results: list[BulkFollowUpItemResult]
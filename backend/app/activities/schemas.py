"""Pydantic schemas for DealFlow Activity APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


ActivityType = Literal[
    "NOTE",
    "CALL",
    "EMAIL",
    "MEETING",
    "STATUS_CHANGE",
    "OWNER_CHANGE",
    "TASK",
    "OTHER",
]


class ActivityCreateRequest(BaseModel):
    """Request payload for creating an activity on a lead."""

    model_config = ConfigDict(extra="forbid")

    activity_type: ActivityType
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    details: dict[str, Any] | None = None
    occurred_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        """Reject titles containing only whitespace."""
        normalized = value.strip()

        if not normalized:
            raise ValueError("Activity title cannot be blank.")

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


class ActivityResponse(BaseModel):
    """Response representation of a persisted activity."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    lead_id: UUID
    actor_id: UUID
    activity_type: ActivityType
    title: str
    description: str | None
    details: dict[str, Any] | None
    occurred_at: datetime
    created_at: datetime


class ActivityListResponse(BaseModel):
    """Response containing a lead's activity timeline."""

    items: list[ActivityResponse]

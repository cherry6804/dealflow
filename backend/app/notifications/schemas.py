"""Pydantic schemas for in-app notifications."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


class NotificationResponse(BaseModel):
    """Response schema for a single notification."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    recipient_user_id: UUID
    event_type: str
    title: str
    message: str
    resource_type: str | None
    resource_id: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationListResponse(BaseModel):
    """Paginated response containing notifications."""

    items: list[NotificationResponse]
    total: int
    unread_count: int
    limit: int
    offset: int


class NotificationUnreadCountResponse(BaseModel):
    """Response containing the unread notification count."""

    unread_count: int


class NotificationMarkAllReadResponse(BaseModel):
    """Response after marking notifications as read."""

    updated_count: int


class NotificationPreferencesResponse(BaseModel):
    """Response schema for a user's notification preferences."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    user_id: UUID
    enabled: bool
    follow_ups_enabled: bool
    deals_enabled: bool
    site_visits_enabled: bool
    leads_enabled: bool
    automation_enabled: bool
    created_at: datetime
    updated_at: datetime


class NotificationPreferencesUpdateRequest(BaseModel):
    """Request schema for updating notification preferences."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    follow_ups_enabled: bool | None = None
    deals_enabled: bool | None = None
    site_visits_enabled: bool | None = None
    leads_enabled: bool | None = None
    automation_enabled: bool | None = None

    @model_validator(mode="after")
    def validate_update(self) -> NotificationPreferencesUpdateRequest:
        """Require at least one supplied setting and reject null values."""

        if not self.model_fields_set:
            raise ValueError("At least one preference must be provided.")

        if any(
            value is None
            for value in self.model_dump(exclude_unset=True).values()
        ):
            raise ValueError("Preference values cannot be null.")

        return self

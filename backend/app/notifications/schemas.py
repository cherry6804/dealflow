
"""Pydantic schemas for in-app notifications."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    """Represent a notification belonging to the current user."""

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
    """Paginated notifications and the total unread count."""

    items: list[NotificationResponse]
    total: int
    unread_count: int
    limit: int
    offset: int


class NotificationUnreadCountResponse(BaseModel):
    """Return the unread notification count."""

    unread_count: int


class NotificationMarkAllReadResponse(BaseModel):
    """Summarize a mark-all-as-read operation."""

    updated_count: int

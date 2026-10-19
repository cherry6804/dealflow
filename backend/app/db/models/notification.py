
"""Database model for tenant-scoped, user-facing notifications."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    """Represent a notification delivered to one organization member."""

    __tablename__ = "notifications"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "recipient_user_id",
            "event_key",
            name="uq_notifications_recipient_event_key",
        ),
        Index(
            "ix_notifications_recipient_created",
            "organization_id",
            "recipient_user_id",
            "created_at",
        ),
        Index(
            "ix_notifications_recipient_read_created",
            "organization_id",
            "recipient_user_id",
            "read_at",
            "created_at",
        ),
        Index(
            "ix_notifications_org_event_created",
            "organization_id",
            "event_type",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )

    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    resource_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    resource_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # Stable key supplied by the event producer. NULL allows events that
    # intentionally do not participate in deduplication.
    event_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

"""Audit event model for DealFlow security and accountability events."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.organization import Organization
    from app.db.models.user import User


class AuditEventType(str, Enum):
    """Supported categories of DealFlow audit events."""

    AUTHORIZATION = "authorization"


class AuditDecision(str, Enum):
    """Security decision associated with an auditable authorization event."""

    ALLOWED = "allowed"
    DENIED = "denied"


class AuditEvent(Base):
    """Represent a persistent, security-sensitive audit event."""

    __tablename__ = "audit_events"

    __table_args__ = (
        Index(
            "ix_audit_events_organization_occurred_at",
            "organization_id",
            "occurred_at",
        ),
        Index(
            "ix_audit_events_user_occurred_at",
            "user_id",
            "occurred_at",
        ),
        Index(
            "ix_audit_events_event_type_occurred_at",
            "event_type",
            "occurred_at",
        ),
        Index(
            "ix_audit_events_decision_occurred_at",
            "decision",
            "occurred_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )

    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    action: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    decision: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    permission_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    resource_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    resource_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    event_metadata: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[user_id],
    )

    organization: Mapped[Organization | None] = relationship(
        "Organization",
        foreign_keys=[organization_id],
    )
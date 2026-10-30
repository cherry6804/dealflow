
"""Business activity model for DealFlow lead timelines."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.lead import Lead
    from app.db.models.organization import Organization
    from app.db.models.user import User


class Activity(Base):
    """Represent a tenant-owned business activity associated with a lead."""

    __tablename__ = "activities"

    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_activities_id_organization_id",
        ),
        ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_activities_lead_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["actor_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_activities_actor_membership_tenant",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_activities_org_lead_occurred_at",
            "organization_id",
            "lead_id",
            "occurred_at",
        ),
        Index(
            "ix_activities_org_occurred_at",
            "organization_id",
            "occurred_at",
        ),
        Index(
            "ix_activities_actor_occurred_at",
            "actor_id",
            "occurred_at",
        ),
    )

    TYPE_NOTE = "NOTE"
    TYPE_CALL = "CALL"
    TYPE_EMAIL = "EMAIL"
    TYPE_MEETING = "MEETING"
    TYPE_STATUS_CHANGE = "STATUS_CHANGE"
    TYPE_OWNER_CHANGE = "OWNER_CHANGE"
    TYPE_TASK = "TASK"
    TYPE_OTHER = "OTHER"

    TYPE_VALUES = (
        TYPE_NOTE,
        TYPE_CALL,
        TYPE_EMAIL,
        TYPE_MEETING,
        TYPE_STATUS_CHANGE,
        TYPE_OWNER_CHANGE,
        TYPE_TASK,
        TYPE_OTHER,
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

    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    activity_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    details: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    organization: Mapped[Organization] = relationship(
        "Organization",
    )

    lead: Mapped[Lead] = relationship(
        "Lead",
        overlaps="organization",
    )

    actor: Mapped[User] = relationship(
        "User",
        primaryjoin="User.id == foreign(Activity.actor_id)",
        overlaps="organization",
    )
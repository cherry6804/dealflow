"""Follow-up work item model for DealFlow."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.lead import Lead
    from app.db.models.organization import Organization
    from app.db.models.user import User


class FollowUp(Base):
    """Represent a tenant-owned follow-up task associated with a lead."""

    __tablename__ = "follow_ups"

    __table_args__ = (
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_follow_ups_id_organization_id",
        ),
        ForeignKeyConstraint(
            ["lead_id", "organization_id"],
            ["leads.id", "leads.organization_id"],
            name="fk_follow_ups_lead_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_follow_ups_owner_membership_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["completed_by_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_follow_ups_completed_by_membership_tenant",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'CANCELLED')",
            name="ck_follow_ups_status",
        ),
        CheckConstraint(
            "follow_up_type IN ('CALL', 'EMAIL', 'MEETING', 'VISIT', 'TASK', 'OTHER')",
            name="ck_follow_ups_type",
        ),
        CheckConstraint(
            "(status = 'COMPLETED' AND completed_at IS NOT NULL "
            "AND completed_by_user_id IS NOT NULL) OR "
            "(status != 'COMPLETED' AND completed_at IS NULL "
            "AND completed_by_user_id IS NULL)",
            name="ck_follow_ups_completion_fields",
        ),
        Index(
            "ix_follow_ups_org_status_due_at",
            "organization_id",
            "status",
            "due_at",
        ),
        Index(
            "ix_follow_ups_org_lead_due_at",
            "organization_id",
            "lead_id",
            "due_at",
        ),
        Index(
            "ix_follow_ups_owner_status_due_at",
            "owner_user_id",
            "status",
            "due_at",
        ),
    )

    STATUS_PENDING = "PENDING"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_VALUES = (
        STATUS_PENDING,
        STATUS_COMPLETED,
        STATUS_CANCELLED,
    )

    TYPE_CALL = "CALL"
    TYPE_EMAIL = "EMAIL"
    TYPE_MEETING = "MEETING"
    TYPE_VISIT = "VISIT"
    TYPE_TASK = "TASK"
    TYPE_OTHER = "OTHER"

    TYPE_VALUES = (
        TYPE_CALL,
        TYPE_EMAIL,
        TYPE_MEETING,
        TYPE_VISIT,
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

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    follow_up_type: Mapped[str] = mapped_column(
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

    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    
    organization: Mapped[Organization] = relationship(
        "Organization",
        overlaps="lead",
    )

    lead: Mapped[Lead] = relationship(
        "Lead",
        foreign_keys="[FollowUp.lead_id]",
        overlaps="organization",
    )

    owner: Mapped[User] = relationship(
        "User",
        primaryjoin="User.id == foreign(FollowUp.owner_user_id)",
        foreign_keys="[FollowUp.owner_user_id]",
    )

    completed_by: Mapped[User | None] = relationship(
        "User",
        primaryjoin="User.id == foreign(FollowUp.completed_by_user_id)",
        foreign_keys="[FollowUp.completed_by_user_id]",
    )


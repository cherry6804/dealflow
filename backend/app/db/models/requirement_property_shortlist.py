
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RequirementPropertyShortlist(Base):
    """Record a property's manual shortlist association with a requirement."""

    __tablename__ = "requirement_property_shortlists"

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_requirement_id", "organization_id"],
            [
                "customer_requirements.id",
                "customer_requirements.organization_id",
            ],
            name="fk_requirement_property_shortlists_requirement_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["created_by_user_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_requirement_property_shortlists_creator_tenant",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "customer_requirement_id",
            "property_id",
            name="uq_requirement_property_shortlists_requirement_property",
        ),
        Index(
            "ix_requirement_property_shortlists_org_property",
            "organization_id",
            "property_id",
        ),
        Index(
            "ix_requirement_property_shortlists_org_requirement_created",
            "organization_id",
            "customer_requirement_id",
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

    customer_requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("properties.id", ondelete="CASCADE"),
        nullable=False,
    )

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

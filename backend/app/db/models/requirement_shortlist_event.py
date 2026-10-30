
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal
from sqlalchemy import CheckConstraint
from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    JSON,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RequirementShortlistEvent(Base):
    """Append-only history of manual shortlist additions and removals."""

    __tablename__ = "requirement_shortlist_events"

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('ADDED', 'REMOVED')",
            name="ck_requirement_shortlist_events_event_type",
        ),
        ForeignKeyConstraint(
            ["actor_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_requirement_shortlist_events_actor_tenant",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_requirement_shortlist_events_org_requirement_created",
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

    # Historical reference only; deliberately not a property FK.
    property_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    event_type: Mapped[Literal["ADDED", "REMOVED"]] = mapped_column(
        String(10),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    property_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

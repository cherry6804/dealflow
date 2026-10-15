
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RequirementMatchRun(Base):
    """Immutable record of a matching execution for a requirement."""

    __tablename__ = "requirement_match_runs"

    __table_args__ = (
        ForeignKeyConstraint(
            ["actor_id", "organization_id"],
            [
                "organization_memberships.user_id",
                "organization_memberships.organization_id",
            ],
            name="fk_requirement_match_runs_actor_tenant",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_requirement_match_runs_org_requirement_created",
            "organization_id",
            "customer_requirement_id",
            "created_at",
        ),
        UniqueConstraint(
            "id",
            "organization_id",
            name="uq_requirement_match_runs_id_organization",
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

    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    criteria_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    total_candidates: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    matched_candidates: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

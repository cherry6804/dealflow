
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DealStageHistory(Base):
    """Record an auditable deal-stage transition."""

    __tablename__ = "deal_stage_history"

    __table_args__ = (
        ForeignKeyConstraint(
            ["deal_id", "organization_id"],
            ["deals.id", "deals.organization_id"],
            name="fk_deal_stage_history_deal_tenant",
            ondelete="CASCADE",
        ),
        Index(
            "ix_deal_stage_history_org_deal_created",
            "organization_id",
            "deal_id",
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

    deal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
    )

    from_stage: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    to_stage: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

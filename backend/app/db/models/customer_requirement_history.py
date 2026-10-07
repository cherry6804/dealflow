from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.customer_requirement import CustomerRequirement
    from app.db.models.organization import Organization
    from app.db.models.user import User


class CustomerRequirementHistory(Base):
    __tablename__ = "customer_requirement_history"

    __table_args__ = (
        UniqueConstraint(
            "customer_requirement_id",
            "organization_id",
            "version",
            name="uq_customer_requirement_history_requirement_org_version",
        ),
        ForeignKeyConstraint(
            ["customer_requirement_id", "organization_id"],
            [
                "customer_requirements.id",
                "customer_requirements.organization_id",
            ],
            name="fk_customer_requirement_history_requirement_tenant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    customer_requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "organizations.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    change_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    customer_requirement: Mapped[CustomerRequirement] = relationship(
        "CustomerRequirement",
        back_populates="history",
    )

    organization: Mapped[Organization] = relationship(
        "Organization",
        overlaps="customer_requirement,history",
    )

    actor: Mapped[User] = relationship(
        "User",
    )
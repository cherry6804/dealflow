import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.membership import Membership
    from app.db.models.role import Role


class MembershipRole(Base):
    """Assign an authorization role to an organization membership."""

    __tablename__ = "membership_roles"

    __table_args__ = (
        UniqueConstraint(
            "membership_id",
            "role_id",
            name="uq_membership_roles_membership_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organization_memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    membership: Mapped["Membership"] = relationship(
        "Membership",
        back_populates="membership_roles",
    )

    role: Mapped["Role"] = relationship(
        "Role",
        back_populates="membership_roles",
    )
"""Organization-level enablement for a governed AI or automation capability."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrganizationCapabilitySetting(Base):
    """Whether one organization has enabled one capability.

    A missing row means the capability is disabled (the catalogue default). The row
    records the actor and the policy version so every change is attributable.
    """

    __tablename__ = "organization_capability_settings"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "capability_key",
            name="uq_organization_capability_settings_org_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    capability_key: Mapped[str] = mapped_column(String(100), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # manual: set by a person through the settings API. migration_evidence_active_rule: granted
    # by the E13 migration from an active automation rule with a known activating user.
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", server_default="manual")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

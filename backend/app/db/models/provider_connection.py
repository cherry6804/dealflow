"""Provider connection registry: metadata and secret references, never secret values (DFR1-006 / DFR1-011).

A connection says that an organization has configured a provider of one kind. Its status is only ``verified``
after a real health check succeeded, so a configured-but-unchecked provider never counts as connected. The
secret is referenced by the name of an environment variable (``secret_ref``) and is never stored here.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

PROVIDER_KINDS = ("llm", "whatsapp", "email", "voice")
PROVIDER_STATUSES = ("not_verified", "verified", "unhealthy", "disabled")


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_kind", name="uq_provider_connections_org_kind"),
        CheckConstraint(
            "provider_kind IN ('llm', 'whatsapp', 'email', 'voice')",
            name="ck_provider_connections_kind",
        ),
        CheckConstraint(
            "status IN ('not_verified', 'verified', 'unhealthy', 'disabled')",
            name="ck_provider_connections_status",
        ),
        Index("ix_provider_connections_org_status", "organization_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Name of the environment variable that holds the secret. The value is never stored or returned.
    secret_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_verified")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

"""Organization-scoped provider credential with encrypted secret storage (DFR1-011 subset)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProviderCredential(Base):
    """One provider credential for one organization.

    The secret is stored only as authenticated ciphertext. A revoked credential keeps its row
    for audit, with the ciphertext and key metadata cleared. At most one credential per
    organization and provider can be active at a time.
    """

    __tablename__ = "provider_credentials"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_provider_credentials_status",
        ),
        CheckConstraint(
            "(status = 'active' AND ciphertext IS NOT NULL"
            " AND encryption_key_id IS NOT NULL AND encryption_algorithm IS NOT NULL)"
            " OR (status = 'revoked' AND ciphertext IS NULL)",
            name="ck_provider_credentials_secret_state",
        ),
        Index(
            "uq_provider_credentials_active_provider",
            "organization_id",
            "provider_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    encryption_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    encryption_algorithm: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    rotated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
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
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

"""Organization-level connection to an external provider (ADR-0032).

A connection is the organization's relationship with one provider. It references the encrypted
credential in ``provider_credentials`` and never holds a secret itself. Its status is a record of
the last verification, and the provider counts as ready only when readiness (``app.providers.readiness``)
confirms that the verified credential version is still the active one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProviderConnection(Base):
    __tablename__ = "provider_connections"

    STATUS_UNVERIFIED = "unverified"
    STATUS_VERIFYING = "verifying"
    STATUS_CONNECTED = "connected"
    STATUS_DEGRADED = "degraded"
    STATUS_FAILED = "failed"
    STATUS_DISCONNECTED = "disconnected"
    STATUSES = (
        STATUS_UNVERIFIED,
        STATUS_VERIFYING,
        STATUS_CONNECTED,
        STATUS_DEGRADED,
        STATUS_FAILED,
        STATUS_DISCONNECTED,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('unverified', 'verifying', 'connected', 'degraded', 'failed', 'disconnected')",
            name="ck_provider_connections_status",
        ),
        CheckConstraint("consecutive_failures >= 0", name="ck_provider_connections_failures_non_negative"),
        CheckConstraint("version >= 1", name="ck_provider_connections_version_positive"),
        # One live connection per organization and provider.
        Index(
            "uq_provider_connections_live_provider",
            "organization_id",
            "provider_key",
            unique=True,
            postgresql_where=text("status <> 'disconnected'"),
        ),
        # One live connection per credential.
        Index(
            "uq_provider_connections_live_credential",
            "credential_id",
            unique=True,
            postgresql_where=text("status <> 'disconnected'"),
        ),
        Index("ix_provider_connections_due", "status", "next_verification_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("provider_credentials.id", ondelete="RESTRICT"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    status_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Credential version that last passed verification. Readiness requires it to equal the active version.
    verified_credential_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_verification_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optimistic concurrency token. Every state change increments it.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

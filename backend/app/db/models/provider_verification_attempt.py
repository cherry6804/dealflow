"""Verification attempt history for a provider connection (ADR-0032, decision D7).

Rows record outcomes and reason codes only. They never hold a credential, a provider response body
or an error message from the provider.
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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProviderVerificationAttempt(Base):
    __tablename__ = "provider_verification_attempts"

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('succeeded', 'transient_failure', 'permanent_failure', 'timed_out', 'not_verified')",
            name="ck_provider_verification_attempts_outcome",
        ),
        CheckConstraint(
            "trigger IN ('created', 'rotated', 'manual', 'scheduled')",
            name="ck_provider_verification_attempts_trigger",
        ),
        Index("ix_provider_verification_attempts_connection", "connection_id", "attempted_at"),
        Index("ix_provider_verification_attempts_organization", "organization_id", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("provider_connections.id", ondelete="RESTRICT"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False)
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    adapter_version: Mapped[str] = mapped_column(String(40), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

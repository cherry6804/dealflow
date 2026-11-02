"""Cached SIBVO organization-level entitlement snapshot (WS5, ADR-0027).

One row per organization and product. The row keeps SIBVO's signed body so it can be verified again
on every read. ``expires_at`` is the only validity clock. A row with no body, or an expired one, never
authorizes execution.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrganizationEntitlementSnapshot(Base):
    __tablename__ = "organization_entitlement_snapshots"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "product_key",
            name="uq_org_entitlement_snapshots_org_product",
        ),
        CheckConstraint(
            "failure_count >= 0",
            name="ck_org_entitlement_snapshots_failures_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_key: Mapped[str] = mapped_column(String(40), nullable=False)
    # SIBVO's signed body, exactly as received. Null after an explicit SIBVO denial.
    snapshot_body: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Consecutive refresh failures, for backoff only. Backoff never extends a snapshot's validity.
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_refresh_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

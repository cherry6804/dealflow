"""AI provider pricing versions and provider cost entries (DFR1-017).

A price version is a platform-level, versioned provider rate for one provider, model, usage unit and currency. It is valid from
``effective_from`` until ``effective_to``. A new version closes the previous one and never changes it, so historical costs keep the
price they were calculated with. There are no seeded prices. Without a version, usage is recorded as unpriced.

A provider cost entry is the platform's cost for one settled usage entry and one unit. It is separate from the customer-credit side of
the ledger. Customer credits have no entry type here, because no approved credit conversion exists. A priced entry carries its currency,
amount in minor units and the price version used. An unpriced entry carries no amount, so unknown cost is never read as zero.
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
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiProviderPrice(Base):
    __tablename__ = "ai_provider_prices"

    __table_args__ = (
        CheckConstraint(
            "unit_price_minor >= 0", name="ck_ai_provider_prices_price_non_negative"
        ),
        CheckConstraint(
            "quantity_per_price >= 1", name="ck_ai_provider_prices_quantity_positive"
        ),
        CheckConstraint("version >= 1", name="ck_ai_provider_prices_version_positive"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_ai_provider_prices_validity_order",
        ),
        UniqueConstraint(
            "provider_key",
            "model",
            "unit",
            "version",
            name="uq_ai_provider_prices_version",
        ),
        # At most one open version per provider, model and unit.
        Index(
            "uq_ai_provider_prices_open",
            "provider_key",
            "model",
            "unit",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_per_price: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_reference: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiProviderCostEntry(Base):
    __tablename__ = "ai_provider_cost_entries"

    STATUS_PRICED = "priced"
    STATUS_UNPRICED = "unpriced"

    __table_args__ = (
        CheckConstraint(
            "status IN ('priced', 'unpriced')",
            name="ck_ai_provider_cost_entries_status",
        ),
        CheckConstraint("quantity >= 0", name="ck_ai_provider_cost_entries_quantity"),
        CheckConstraint(
            "(status = 'priced' AND amount_minor IS NOT NULL AND amount_minor >= 0 AND currency IS NOT NULL"
            " AND price_id IS NOT NULL AND price_version IS NOT NULL)"
            " OR (status = 'unpriced' AND amount_minor IS NULL AND reason_code IS NOT NULL)",
            name="ck_ai_provider_cost_entries_state",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_ai_provider_cost_entries_idempotency",
        ),
        Index(
            "ix_ai_provider_cost_entries_org_occurred", "organization_id", "occurred_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    usage_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_usage_events.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    price_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_provider_prices.id", ondelete="RESTRICT"), nullable=True
    )
    price_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_per_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

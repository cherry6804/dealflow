"""Provider pricing versions and provider cost entries (DFR1-017).

Two rules shape this module:

1. Provider cost is recorded from a price version that is valid at the moment of usage. If no valid version exists, the entry is
   recorded as unpriced. An unpriced entry is never stored as zero cost.
2. Provider cost never becomes a customer credit. Nothing here writes ``customer_credits``, and no credit conversion is applied.

Price versions are platform configuration. They are created by calling ```create_price_version`` from server-side code, for example
an operator script run by the platform owner. No tenant-facing endpoint changes prices. The module does not seed any rate.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.ai_pricing import AiProviderCostEntry, AiProviderPrice
from app.db.models.ai_usage_event import AiUsageEvent

PRICEABLE_UNITS: tuple[str, ...] = (
    "tokens_input",
    "tokens_output",
    "images",
    "document_pages",
    "audio_ms",
)
REASON_NO_PRICE_VERSION = "no_price_version"
MAX_SOURCE_REFERENCE = 200
MAX_UNIT_PRICE_MINOR = 10_000_000_000
MAX_QUANTITY_PER_PRICE = 1_000_000_000


class PricingError(ValueError):
    """A price version was refused. ``reason`` is a stable code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def create_price_version(
    db: Session,
    *,
    provider_key: str,
    model: str,
    unit: str,
    currency: str,
    unit_price_minor: int,
    quantity_per_price: int,
    effective_from: datetime,
    source_reference: str,
    actor_user_id: UUID | None = None,
) -> AiProviderPrice:
    """Add a price version. The previous open version for the same provider, model and unit is closed at ``effective_from``."""
    if unit not in PRICEABLE_UNITS:
        raise PricingError("unpriceable_unit")
    if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
        raise PricingError("invalid_currency")
    if not isinstance(unit_price_minor, int) or isinstance(unit_price_minor, bool):
        raise PricingError("invalid_price")
    if unit_price_minor < 0 or unit_price_minor > MAX_UNIT_PRICE_MINOR:
        raise PricingError("invalid_price")
    if not isinstance(quantity_per_price, int) or isinstance(quantity_per_price, bool):
        raise PricingError("invalid_quantity_basis")
    if quantity_per_price < 1 or quantity_per_price > MAX_QUANTITY_PER_PRICE:
        raise PricingError("invalid_quantity_basis")
    if effective_from.tzinfo is None or effective_from.utcoffset() is None:
        raise PricingError("effective_from_must_be_aware")
    reference = source_reference.strip()
    if not reference or len(reference) > MAX_SOURCE_REFERENCE:
        raise PricingError("source_reference_required")
    moment = effective_from.astimezone(UTC)

    previous = db.scalar(
        select(AiProviderPrice)
        .where(
            AiProviderPrice.provider_key == provider_key,
            AiProviderPrice.model == model,
            AiProviderPrice.unit == unit,
            AiProviderPrice.effective_to.is_(None),
        )
        .with_for_update()
    )
    latest_version = (
        db.scalar(
            select(func.max(AiProviderPrice.version)).where(
                AiProviderPrice.provider_key == provider_key,
                AiProviderPrice.model == model,
                AiProviderPrice.unit == unit,
            )
        )
        or 0
    )
    if previous is not None:
        if moment <= previous.effective_from:
            raise PricingError("effective_from_must_follow_current_version")
        previous.effective_to = moment
    row = AiProviderPrice(
        provider_key=provider_key,
        model=model,
        unit=unit,
        currency=currency,
        unit_price_minor=unit_price_minor,
        quantity_per_price=quantity_per_price,
        version=latest_version + 1,
        effective_from=moment,
        effective_to=None,
        source_reference=reference,
        created_by_user_id=actor_user_id,
    )
    db.add(row)
    db.flush()
    return row


def price_for(
    db: Session, *, provider_key: str, model: str, unit: str, at: datetime
) -> AiProviderPrice | None:
    """The price version valid at ``at``, or None when no version covers that moment."""
    moment = at.astimezone(UTC)
    return db.scalar(
        select(AiProviderPrice).where(
            AiProviderPrice.provider_key == provider_key,
            AiProviderPrice.model == model,
            AiProviderPrice.unit == unit,
            AiProviderPrice.effective_from <= moment,
            (AiProviderPrice.effective_to.is_(None))
            | (AiProviderPrice.effective_to > moment),
        )
    )


def _amount_minor(quantity: int, price: AiProviderPrice) -> int:
    """Integer minor units, rounded up so a partial unit is never free."""
    numerator = quantity * price.unit_price_minor
    return -(-numerator // price.quantity_per_price)


def record_provider_costs(
    db: Session,
    *,
    organization_id: UUID,
    events: Mapping[str, AiUsageEvent],
    provider_key: str,
    model: str,
) -> list[AiProviderCostEntry]:
    """Record one cost entry per settled usage unit. Idempotent: a repeated settlement returns the existing entries.

    The provider and model are the ones that actually answered. An unpriced unit is recorded with its reason, not skipped.
    """
    entries: list[AiProviderCostEntry] = []
    for unit, event in events.items():
        if unit not in PRICEABLE_UNITS or event.quantity is None:
            continue
        key = f"cost:{event.idempotency_key}"
        existing = db.scalar(
            select(AiProviderCostEntry).where(
                AiProviderCostEntry.organization_id == organization_id,
                AiProviderCostEntry.idempotency_key == key,
            )
        )
        if existing is not None:
            entries.append(existing)
            continue
        base = {
            "organization_id": organization_id,
            "usage_event_id": event.id,
            "idempotency_key": key,
            "provider_key": provider_key,
            "model": model,
            "unit": unit,
            "quantity": event.quantity,
            "occurred_at": event.occurred_at,
        }
        price = price_for(
            db, provider_key=provider_key, model=model, unit=unit, at=event.occurred_at
        )
        if price is None:
            entry = AiProviderCostEntry(
                **base,
                status=AiProviderCostEntry.STATUS_UNPRICED,
                reason_code=REASON_NO_PRICE_VERSION,
            )
        else:
            entry = AiProviderCostEntry(
                **base,
                status=AiProviderCostEntry.STATUS_PRICED,
                price_id=price.id,
                price_version=price.version,
                unit_price_minor=price.unit_price_minor,
                quantity_per_price=price.quantity_per_price,
                amount_minor=_amount_minor(event.quantity, price),
                currency=price.currency,
            )
        db.add(entry)
        db.flush()
        entries.append(entry)
    return entries


def provider_cost_totals(
    db: Session, *, organization_id: UUID, start: datetime, end: datetime
) -> dict[str, Any]:
    """Totals per currency, plus the count and units of unpriced entries. Currencies are never added together."""
    rows = db.execute(
        select(AiProviderCostEntry.currency, func.sum(AiProviderCostEntry.amount_minor))
        .where(
            AiProviderCostEntry.organization_id == organization_id,
            AiProviderCostEntry.status == AiProviderCostEntry.STATUS_PRICED,
            AiProviderCostEntry.occurred_at >= start,
            AiProviderCostEntry.occurred_at < end,
        )
        .group_by(AiProviderCostEntry.currency)
    ).all()
    unpriced = db.execute(
        select(AiProviderCostEntry.unit, func.count())
        .where(
            AiProviderCostEntry.organization_id == organization_id,
            AiProviderCostEntry.status == AiProviderCostEntry.STATUS_UNPRICED,
            AiProviderCostEntry.occurred_at >= start,
            AiProviderCostEntry.occurred_at < end,
        )
        .group_by(AiProviderCostEntry.unit)
    ).all()
    return {
        "priced_minor_by_currency": {currency: int(total) for currency, total in rows},
        "unpriced_entries_by_unit": {unit: int(count) for unit, count in unpriced},
        "unpriced_entry_count": sum(int(count) for _unit, count in unpriced),
    }


__all__ = [
    "PRICEABLE_UNITS",
    "REASON_NO_PRICE_VERSION",
    "PricingError",
    "create_price_version",
    "price_for",
    "provider_cost_totals",
    "record_provider_costs",
]

"""Property service-layer operations for DealFlow."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.property import Property


def create_property(
    db: Session,
    *,
    organization_id: UUID,
) -> Property:
    """Create a Property within the verified tenant."""

    property_record = Property(
        organization_id=organization_id,
    )

    db.add(property_record)
    db.flush()
    db.refresh(property_record)

    return property_record


def get_property(
    db: Session,
    *,
    organization_id: UUID,
    property_id: UUID,
) -> Property | None:
    """Retrieve a Property within the verified tenant."""

    statement = select(Property).where(
        Property.id == property_id,
        Property.organization_id == organization_id,
    )

    return db.scalar(statement)


def update_property_commercial(
    db: Session,
    *,
    organization_id: UUID,
    property_id: UUID,
    transaction_type: Literal["SALE", "RENT", "LEASE"],
    price: Decimal | None,
    currency: str,
    rent: Decimal | None,
    security_deposit: Decimal | None,
    maintenance_charge: Decimal | None,
) -> Property | None:
    """Update commercial fields for a Property within the verified tenant."""

    property_record = get_property(
        db=db,
        organization_id=organization_id,
        property_id=property_id,
    )

    if property_record is None:
        return None

    property_record.transaction_type = transaction_type
    property_record.price = price
    property_record.currency = currency
    property_record.rent = rent
    property_record.security_deposit = security_deposit
    property_record.maintenance_charge = maintenance_charge

    db.flush()
    db.refresh(property_record)

    return property_record
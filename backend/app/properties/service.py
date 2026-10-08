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


def update_property_location_attributes(
    db: Session,
    *,
    organization_id: UUID,
    property_id: UUID,
    address_line_1: str | None,
    address_line_2: str | None,
    locality: str | None,
    city: str | None,
    state: str | None,
    postal_code: str | None,
    property_type: str | None,
    bhk: int | None,
    built_up_area: Decimal | None,
    carpet_area: Decimal | None,
    floor_number: int | None,
    total_floors: int | None,
    fields_to_update: set[str],
) -> Property | None:
    """Update Property location and attributes within the verified tenant.

    Only fields explicitly supplied by the PATCH request are changed.
    Explicit null values are supported for clearing nullable fields.
    """

    property_record = get_property(
        db=db,
        organization_id=organization_id,
        property_id=property_id,
    )

    if property_record is None:
        return None

    values = {
        "address_line_1": address_line_1,
        "address_line_2": address_line_2,
        "locality": locality,
        "city": city,
        "state": state,
        "postal_code": postal_code,
        "property_type": property_type,
        "bhk": bhk,
        "built_up_area": built_up_area,
        "carpet_area": carpet_area,
        "floor_number": floor_number,
        "total_floors": total_floors,
    }

    for field_name in fields_to_update:
        setattr(property_record, field_name, values[field_name])

    resulting_floor_number = property_record.floor_number
    resulting_total_floors = property_record.total_floors

    if (
        resulting_floor_number is not None
        and resulting_total_floors is not None
        and resulting_floor_number > resulting_total_floors
    ):
        raise ValueError(
            "Floor number cannot be greater than total floors."
        )

    db.flush()
    db.refresh(property_record)

    return property_record
"""Property service-layer operations for DealFlow."""

from __future__ import annotations

from decimal import Decimal
from math import ceil
from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.property import Property
from app.properties.schemas import PropertySearchQuery


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


def update_property_status(
    db: Session,
    *,
    organization_id: UUID,
    property_id: UUID,
    status: Literal[
        "AVAILABLE",
        "RESERVED",
        "SOLD",
        "RENTED",
        "LEASED",
        "UNAVAILABLE",
    ],
) -> Property | None:
    """Update availability status for a Property within the verified tenant."""

    property_record = get_property(
        db=db,
        organization_id=organization_id,
        property_id=property_id,
    )

    if property_record is None:
        return None

    property_record.status = status

    db.flush()
    db.refresh(property_record)

    return property_record


def search_properties(
    db: Session,
    *,
    organization_id: UUID,
    filters: PropertySearchQuery,
) -> tuple[list[Property], int, int]:
    """Search and filter Properties within the verified tenant.

    Search behavior:
    - Always scopes results to the verified organization.
    - Multiple filters are combined using AND semantics.
    - Text search checks supported address/location fields.
    - Results use deterministic created_at/id descending order.
    - Pagination is applied after filtering and ordering.

    Returns:
        A tuple containing:
        - properties for the requested page
        - total number of matching properties
        - total number of pages
    """

    ranges = (
        ("min_price", "max_price"),
        ("min_rent", "max_rent"),
        ("min_built_up_area", "max_built_up_area"),
        ("min_carpet_area", "max_carpet_area"),
    )

    for minimum_field, maximum_field in ranges:
        minimum = getattr(filters, minimum_field)
        maximum = getattr(filters, maximum_field)

        if (
            minimum is not None
            and maximum is not None
            and minimum > maximum
        ):
            raise ValueError(
                f"{minimum_field} must be less than or equal to "
                f"{maximum_field}."
            )

    conditions = [
        Property.organization_id == organization_id,
    ]

    if filters.q:
        search_term = f"%{filters.q}%"

        conditions.append(
            or_(
                Property.address_line_1.ilike(search_term),
                Property.address_line_2.ilike(search_term),
                Property.locality.ilike(search_term),
                Property.city.ilike(search_term),
                Property.state.ilike(search_term),
                Property.postal_code.ilike(search_term),
            )
        )

    if filters.transaction_type is not None:
        conditions.append(
            Property.transaction_type == filters.transaction_type,
        )

    if filters.status is not None:
        conditions.append(
            Property.status == filters.status,
        )

    if filters.property_type is not None:
        conditions.append(
            Property.property_type == filters.property_type,
        )

    if filters.bhk is not None:
        conditions.append(
            Property.bhk == filters.bhk,
        )

    if filters.city is not None:
        conditions.append(
            func.lower(Property.city) == filters.city.lower(),
        )

    if filters.state is not None:
        conditions.append(
            func.lower(Property.state) == filters.state.lower(),
        )

    if filters.locality is not None:
        conditions.append(
            Property.locality.ilike(f"%{filters.locality}%"),
        )

    if filters.postal_code is not None:
        conditions.append(
            Property.postal_code.ilike(f"%{filters.postal_code}%"),
        )

    if filters.min_price is not None:
        conditions.append(
            Property.price >= filters.min_price,
        )

    if filters.max_price is not None:
        conditions.append(
            Property.price <= filters.max_price,
        )

    if filters.min_rent is not None:
        conditions.append(
            Property.rent >= filters.min_rent,
        )

    if filters.max_rent is not None:
        conditions.append(
            Property.rent <= filters.max_rent,
        )

    if filters.min_built_up_area is not None:
        conditions.append(
            Property.built_up_area >= filters.min_built_up_area,
        )

    if filters.max_built_up_area is not None:
        conditions.append(
            Property.built_up_area <= filters.max_built_up_area,
        )

    if filters.min_carpet_area is not None:
        conditions.append(
            Property.carpet_area >= filters.min_carpet_area,
        )

    if filters.max_carpet_area is not None:
        conditions.append(
            Property.carpet_area <= filters.max_carpet_area,
        )

    if filters.floor_number is not None:
        conditions.append(
            Property.floor_number == filters.floor_number,
        )

    if filters.total_floors is not None:
        conditions.append(
            Property.total_floors == filters.total_floors,
        )

    count_statement = (
        select(func.count())
        .select_from(Property)
        .where(*conditions)
    )

    total = db.scalar(count_statement) or 0

    offset = (filters.page - 1) * filters.page_size

    statement = (
        select(Property)
        .where(*conditions)
        .order_by(
            Property.created_at.desc(),
            Property.id.desc(),
        )
        .offset(offset)
        .limit(filters.page_size)
    )

    properties = list(db.scalars(statement).all())

    total_pages = (
        ceil(total / filters.page_size)
        if total > 0
        else 0
    )

    return properties, total, total_pages
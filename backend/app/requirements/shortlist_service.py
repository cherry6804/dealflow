
"""Tenant-safe manual property shortlist operations and event history."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.property import Property
from app.db.models.requirement_property_shortlist import (
    RequirementPropertyShortlist,
)
from app.db.models.requirement_shortlist_event import RequirementShortlistEvent


def _property_snapshot(property_record: Property) -> dict[str, Any]:
    """Capture property details as JSON-safe historical data."""
    return {
        "id": str(property_record.id),
        "organization_id": str(property_record.organization_id),
        "status": property_record.status,
        "transaction_type": property_record.transaction_type,
        "price": (
            str(property_record.price)
            if property_record.price is not None
            else None
        ),
        "currency": property_record.currency,
        "rent": (
            str(property_record.rent)
            if property_record.rent is not None
            else None
        ),
        "security_deposit": (
            str(property_record.security_deposit)
            if property_record.security_deposit is not None
            else None
        ),
        "maintenance_charge": (
            str(property_record.maintenance_charge)
            if property_record.maintenance_charge is not None
            else None
        ),
        "address_line_1": property_record.address_line_1,
        "address_line_2": property_record.address_line_2,
        "locality": property_record.locality,
        "city": property_record.city,
        "state": property_record.state,
        "postal_code": property_record.postal_code,
        "property_type": property_record.property_type,
        "bhk": property_record.bhk,
        "built_up_area": (
            str(property_record.built_up_area)
            if property_record.built_up_area is not None
            else None
        ),
        "carpet_area": (
            str(property_record.carpet_area)
            if property_record.carpet_area is not None
            else None
        ),
        "floor_number": property_record.floor_number,
        "total_floors": property_record.total_floors,
    }


def _record_shortlist_event(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
    property_record: Property,
    actor_id: UUID,
    event_type: str,
) -> RequirementShortlistEvent:
    """Add a shortlist event to the current transaction."""
    if event_type not in {"ADDED", "REMOVED"}:
        raise ValueError("Unsupported shortlist event type.")

    event = RequirementShortlistEvent(
        organization_id=organization_id,
        customer_requirement_id=requirement_id,
        property_id=property_record.id,
        actor_id=actor_id,
        event_type=event_type,
        property_snapshot=_property_snapshot(property_record),
    )
    db.add(event)
    db.flush()
    return event


def create_requirement_property_shortlist(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
    property_id: UUID,
    actor_id: UUID,
) -> tuple[RequirementPropertyShortlist, Property]:
    """Shortlist a property and record its addition within one transaction."""

    requirement = db.scalar(
        select(CustomerRequirement).where(
            CustomerRequirement.id == requirement_id,
            CustomerRequirement.organization_id == organization_id,
        )
    )
    if requirement is None:
        raise ValueError("Customer requirement not found.")

    property_record = db.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == organization_id,
        )
    )
    if property_record is None:
        raise ValueError("Property not found.")

    existing = db.scalar(
        select(RequirementPropertyShortlist).where(
            RequirementPropertyShortlist.organization_id == organization_id,
            RequirementPropertyShortlist.customer_requirement_id
            == requirement_id,
            RequirementPropertyShortlist.property_id == property_id,
        )
    )
    if existing is not None:
        raise ValueError("Property is already shortlisted for this requirement.")

    shortlist = RequirementPropertyShortlist(
        organization_id=organization_id,
        customer_requirement_id=requirement_id,
        property_id=property_id,
        created_by_user_id=actor_id,
    )
    db.add(shortlist)
    db.flush()
    db.refresh(shortlist)

    _record_shortlist_event(
        db,
        organization_id=organization_id,
        requirement_id=requirement_id,
        property_record=property_record,
        actor_id=actor_id,
        event_type="ADDED",
    )

    return shortlist, property_record


def list_requirement_property_shortlists(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
) -> list[tuple[RequirementPropertyShortlist, Property]]:
    """List shortlisted properties for a tenant-owned requirement."""

    requirement_exists = db.scalar(
        select(CustomerRequirement.id).where(
            CustomerRequirement.id == requirement_id,
            CustomerRequirement.organization_id == organization_id,
        )
    )
    if requirement_exists is None:
        raise ValueError("Customer requirement not found.")

    statement = (
        select(RequirementPropertyShortlist, Property)
        .join(
            Property,
            Property.id == RequirementPropertyShortlist.property_id,
        )
        .where(
            RequirementPropertyShortlist.organization_id == organization_id,
            RequirementPropertyShortlist.customer_requirement_id
            == requirement_id,
            Property.organization_id == organization_id,
        )
        .order_by(
            RequirementPropertyShortlist.created_at.desc(),
            RequirementPropertyShortlist.id.asc(),
        )
    )

    return list(db.execute(statement).all())


def remove_requirement_property_shortlist(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
    property_id: UUID,
    actor_id: UUID,
) -> None:
    """Record a removal and delete the association atomically."""

    requirement_exists = db.scalar(
        select(CustomerRequirement.id).where(
            CustomerRequirement.id == requirement_id,
            CustomerRequirement.organization_id == organization_id,
        )
    )
    if requirement_exists is None:
        raise ValueError("Customer requirement not found.")

    shortlist = db.scalar(
        select(RequirementPropertyShortlist).where(
            RequirementPropertyShortlist.organization_id == organization_id,
            RequirementPropertyShortlist.customer_requirement_id
            == requirement_id,
            RequirementPropertyShortlist.property_id == property_id,
        )
    )
    if shortlist is None:
        raise ValueError("Shortlisted property not found.")

    property_record = db.scalar(
        select(Property).where(
            Property.id == property_id,
            Property.organization_id == organization_id,
        )
    )
    if property_record is None:
        raise ValueError("Property not found.")

    _record_shortlist_event(
        db,
        organization_id=organization_id,
        requirement_id=requirement_id,
        property_record=property_record,
        actor_id=actor_id,
        event_type="REMOVED",
    )

    db.delete(shortlist)
    db.flush()

def list_requirement_shortlist_events(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
) -> list[RequirementShortlistEvent]:
    """Return historical shortlist activity for a tenant and requirement ID."""

    statement = (
        select(RequirementShortlistEvent)
        .where(
            RequirementShortlistEvent.organization_id == organization_id,
            RequirementShortlistEvent.customer_requirement_id == requirement_id,
        )
        .order_by(
            RequirementShortlistEvent.created_at.asc(),
            RequirementShortlistEvent.id.asc(),
        )
    )

    return list(db.scalars(statement).all())
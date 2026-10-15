
"""Tenant-safe manual property shortlist operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.property import Property
from app.db.models.requirement_property_shortlist import (
    RequirementPropertyShortlist,
)


def create_requirement_property_shortlist(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
    property_id: UUID,
    actor_id: UUID,
) -> tuple[RequirementPropertyShortlist, Property]:
    """Shortlist a property for a requirement within the current tenant."""

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
) -> None:
    """Remove a property's shortlist association within the tenant."""

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

    db.delete(shortlist)
    db.flush()

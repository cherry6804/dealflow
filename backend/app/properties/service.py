"""Property service-layer operations for DealFlow."""

from __future__ import annotations

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
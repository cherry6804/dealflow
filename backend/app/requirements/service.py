"""Customer requirement service operations for DealFlow."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.organization import Organization


def create_customer_requirement(
    db: Session,
    *,
    organization_id: UUID,
) -> CustomerRequirement:
    """Create a new active customer requirement for a tenant."""

    organization_statement = select(Organization).where(
        Organization.id == organization_id,
        Organization.is_active.is_(True),
    )

    organization = db.scalar(organization_statement)

    if organization is None:
        raise ValueError("Organization not found.")

    requirement = CustomerRequirement(
        organization_id=organization_id,
        status=CustomerRequirement.STATUS_ACTIVE,
        is_active=True,
    )

    db.add(requirement)
    db.flush()
    db.refresh(requirement)

    return requirement


def get_customer_requirement(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
) -> CustomerRequirement | None:
    """Retrieve a customer requirement within the supplied tenant."""

    statement = select(CustomerRequirement).where(
        CustomerRequirement.id == requirement_id,
        CustomerRequirement.organization_id == organization_id,
    )

    return db.scalar(statement)
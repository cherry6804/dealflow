"""Customer requirement service operations for DealFlow."""

from __future__ import annotations

from decimal import Decimal
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


def update_customer_requirement_budget(
    db: Session,
    *,
    requirement: CustomerRequirement,
    budget_min: Decimal | None = None,
    budget_max: Decimal | None = None,
    budget_currency: str | None = None,
    update_budget_min: bool = False,
    update_budget_max: bool = False,
    update_budget_currency: bool = False,
) -> CustomerRequirement:
    """Update only the supplied budget fields."""

    new_budget_min = (
        budget_min if update_budget_min else requirement.budget_min
    )

    new_budget_max = (
        budget_max if update_budget_max else requirement.budget_max
    )

    new_budget_currency = (
        budget_currency
        if update_budget_currency
        else requirement.budget_currency
    )

    if (
        new_budget_min is not None
        and new_budget_max is not None
        and new_budget_min > new_budget_max
    ):
        raise ValueError(
            "Budget minimum cannot be greater than budget maximum."
        )

    if (
        new_budget_min is not None
        or new_budget_max is not None
    ) and new_budget_currency is None:
        raise ValueError(
            "Budget currency is required when a budget value is provided."
        )

    if (
        new_budget_min is None
        and new_budget_max is None
        and new_budget_currency is not None
    ):
        raise ValueError(
            "Budget currency cannot be set without a budget value."
        )

    if update_budget_min:
        requirement.budget_min = budget_min

    if update_budget_max:
        requirement.budget_max = budget_max

    if update_budget_currency:
        requirement.budget_currency = budget_currency

    db.add(requirement)
    db.flush()
    db.refresh(requirement)

    return requirement
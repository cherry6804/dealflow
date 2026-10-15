"""Matching engine for customer requirements and available properties."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_location import (
    CustomerRequirementLocation,
)
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.property import Property


def _normalise(value: str | None) -> str | None:
    """Normalise optional text for case-insensitive comparisons."""
    if value is None:
        return None

    normalised = value.strip().casefold()
    return normalised or None


def _matches_location(
    property_record: Property,
    locations: list[CustomerRequirementLocation],
) -> bool:
    """Return whether a property matches an active requested location."""
    if not locations:
        return True

    property_city = _normalise(property_record.city)
    property_locality = _normalise(property_record.locality)

    for location in locations:
        requested_city = _normalise(location.city)
        requested_locality = _normalise(location.locality)

        if (
            requested_city is not None
            and requested_locality is not None
            and property_city == requested_city
            and property_locality == requested_locality
        ):
            return True

    return False


def _matches_property_preference(
    property_record: Property,
    preferences: list[CustomerRequirementPropertyPreference],
) -> bool:
    """Match any active property-type preference and its optional BHK range."""
    if not preferences:
        return True

    for preference in preferences:
        if (
            _normalise(property_record.property_type)
            != _normalise(preference.property_type)
        ):
            continue

        if preference.bhk_min is not None:
            if (
                property_record.bhk is None
                or property_record.bhk < preference.bhk_min
            ):
                continue

        if preference.bhk_max is not None:
            if (
                property_record.bhk is None
                or property_record.bhk > preference.bhk_max
            ):
                continue

        return True

    return False


def _matches_budget(
    requirement: CustomerRequirement,
    property_record: Property,
) -> bool:
    """Check budget only when comparable pricing and currency are available."""
    if (
        requirement.budget_min is None
        and requirement.budget_max is None
    ):
        return True

    requirement_currency = _normalise(requirement.budget_currency)
    property_currency = _normalise(property_record.currency)

    # Never claim a budget match when the currencies cannot be compared.
    if (
        requirement_currency is None
        or property_currency is None
        or requirement_currency != property_currency
    ):
        return False

    if property_record.transaction_type == Property.TRANSACTION_TYPE_SALE:
        amount = property_record.price
    elif property_record.transaction_type == Property.TRANSACTION_TYPE_RENT:
        amount = property_record.rent
    else:
        # Lease pricing semantics are not defined by the current requirement model.
        return False

    if amount is None:
        return False

    if (
        requirement.budget_min is not None
        and amount < requirement.budget_min
    ):
        return False

    if (
        requirement.budget_max is not None
        and amount > requirement.budget_max
    ):
        return False

    return True


def get_matching_properties(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
) -> list[Property]:
    """Return available properties matching a tenant-owned active requirement.

    Location and property preferences use OR semantics within each category.
    Location, property preference, and budget categories use AND semantics.
    Results are ordered deterministically by creation time and ID.
    """

    requirement_statement = select(CustomerRequirement).where(
        CustomerRequirement.id == requirement_id,
        CustomerRequirement.organization_id == organization_id,
        CustomerRequirement.status == CustomerRequirement.STATUS_ACTIVE,
        CustomerRequirement.is_active.is_(True),
    )
    requirement = db.scalar(requirement_statement)

    if requirement is None:
        raise ValueError("Active customer requirement not found.")

    locations_statement = select(CustomerRequirementLocation).where(
        CustomerRequirementLocation.organization_id == organization_id,
        CustomerRequirementLocation.customer_requirement_id == requirement_id,
        CustomerRequirementLocation.is_active.is_(True),
    )
    locations = list(db.scalars(locations_statement).all())

    preferences_statement = select(
        CustomerRequirementPropertyPreference
    ).where(
        CustomerRequirementPropertyPreference.organization_id
        == organization_id,
        CustomerRequirementPropertyPreference.customer_requirement_id
        == requirement_id,
        CustomerRequirementPropertyPreference.is_active.is_(True),
    )
    preferences = list(db.scalars(preferences_statement).all())

    properties_statement = (
        select(Property)
        .where(
            Property.organization_id == organization_id,
            Property.status == Property.STATUS_AVAILABLE,
        )
        .order_by(
            Property.created_at.desc(),
            Property.id.desc(),
        )
    )
    property_records = list(db.scalars(properties_statement).all())

    matches = [
        property_record
        for property_record in property_records
        if _matches_location(property_record, locations)
        and _matches_property_preference(property_record, preferences)
        and _matches_budget(requirement, property_record)
    ]

    return matches

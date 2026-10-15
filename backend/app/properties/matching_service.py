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
from app.properties.schemas import (
    PropertyMatchCriterionResult,
    PropertyMatchResult,
)
from app.properties.schemas import PropertySearchResult


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

def get_property_match_results(
    db: Session,
    *,
    organization_id: UUID,
    requirement_id: UUID,
) -> list[PropertyMatchResult]:
    """Return available property candidates with criterion explanations."""

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

    results: list[PropertyMatchResult] = []

    for property_record in property_records:
        criteria: list[PropertyMatchCriterionResult] = []

        if locations:
            location_match = _matches_location(property_record, locations)
            criteria.append(
                PropertyMatchCriterionResult(
                    criterion="LOCATION",
                    status="MATCH" if location_match else "MISMATCH",
                    explanation=(
                        f"Property location {property_record.locality or 'unknown'}, "
                        f"{property_record.city or 'unknown'} matches an active "
                        "requested location."
                        if location_match
                        else (
                            "Property city and locality do not match any active "
                            "requested location."
                        )
                    ),
                )
            )
        else:
            criteria.append(
                PropertyMatchCriterionResult(
                    criterion="LOCATION",
                    status="NOT_CONFIGURED",
                    explanation=(
                        "No active location preferences are configured."
                    ),
                )
            )

        if preferences:
            preference_match = _matches_property_preference(
                property_record,
                preferences,
            )
            criteria.append(
                PropertyMatchCriterionResult(
                    criterion="PROPERTY_TYPE_AND_BHK",
                    status="MATCH" if preference_match else "MISMATCH",
                    explanation=(
                        "Property type and BHK satisfy an active preference."
                        if preference_match
                        else (
                            "Property type or BHK does not satisfy any active "
                            "property preference."
                        )
                    ),
                )
            )
        else:
            criteria.append(
                PropertyMatchCriterionResult(
                    criterion="PROPERTY_TYPE_AND_BHK",
                    status="NOT_CONFIGURED",
                    explanation=(
                        "No active property preferences are configured."
                    ),
                )
            )

        budget_configured = (
            requirement.budget_min is not None
            or requirement.budget_max is not None
        )

        if not budget_configured:
            criteria.append(
                PropertyMatchCriterionResult(
                    criterion="BUDGET",
                    status="NOT_CONFIGURED",
                    explanation="No budget bounds are configured.",
                )
            )
        else:
            budget_match = _matches_budget(requirement, property_record)

            if budget_match:
                budget_status = "MATCH"
                budget_explanation = (
                    "Property price is within the configured budget bounds "
                    "and uses the same currency."
                )
            elif (
                requirement.budget_currency is None
                or property_record.currency is None
                or _normalise(requirement.budget_currency)
                != _normalise(property_record.currency)
            ):
                budget_status = "UNKNOWN"
                budget_explanation = (
                    "Budget compatibility cannot be established because "
                    "the requirement and property currencies are missing "
                    "or different."
                )
            elif (
                property_record.transaction_type
                == Property.TRANSACTION_TYPE_LEASE
            ):
                budget_status = "UNKNOWN"
                budget_explanation = (
                    "Lease budget compatibility cannot be evaluated because "
                    "lease pricing semantics are not defined."
                )

            elif property_record.transaction_type not in (
                Property.TRANSACTION_TYPE_SALE,
                Property.TRANSACTION_TYPE_RENT,
            ):
                budget_status = "UNKNOWN"
                budget_explanation = (
                    "Budget compatibility cannot be evaluated because "
                    "the property transaction type is missing or unsupported."
                )
            elif (
                property_record.transaction_type
                == Property.TRANSACTION_TYPE_SALE
                and property_record.price is None
            ) or (
                property_record.transaction_type
                == Property.TRANSACTION_TYPE_RENT
                and property_record.rent is None
            ):
                budget_status = "UNKNOWN"
                budget_explanation = (
                    "The property has no comparable price or rent recorded."
                )
            else:
                budget_status = "MISMATCH"
                budget_explanation = (
                    "Property price or rent is outside the configured budget "
                    "bounds."
                )

            criteria.append(
                PropertyMatchCriterionResult(
                    criterion="BUDGET",
                    status=budget_status,
                    explanation=budget_explanation,
                )
            )

        overall_match = all(
            criterion.status in ("MATCH", "NOT_CONFIGURED")
            for criterion in criteria
        )

        results.append(
            PropertyMatchResult(
                property=PropertySearchResult.model_validate(property_record),
                overall_match=overall_match,
                criteria=criteria,
            )
        )

    return results

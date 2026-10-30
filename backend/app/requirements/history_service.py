"""Customer requirement history operations for DealFlow."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_history import (
    CustomerRequirementHistory,
)
from app.db.models.customer_requirement_location import (
    CustomerRequirementLocation,
)
from app.db.models.customer_requirement_possession_parking_preference import (
    CustomerRequirementPossessionParkingPreference,
)
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)


def _serialize_decimal(value: Decimal | None) -> str | None:
    """Serialize Decimal values into JSON-safe strings."""

    if value is None:
        return None

    return str(value)


def build_customer_requirement_snapshot(
    db: Session,
    *,
    requirement: CustomerRequirement,
    organization_id: UUID,
) -> dict[str, Any]:
    """Build a complete immutable snapshot of the requirement aggregate."""

    if requirement.organization_id != organization_id:
        raise ValueError("Customer requirement not found.")

    locations_statement = (
        select(CustomerRequirementLocation)
        .where(
            CustomerRequirementLocation.customer_requirement_id == requirement.id,
            CustomerRequirementLocation.organization_id == organization_id,
        )
        .order_by(
            CustomerRequirementLocation.created_at.asc(),
            CustomerRequirementLocation.id.asc(),
        )
    )

    property_preferences_statement = (
        select(CustomerRequirementPropertyPreference)
        .where(
            CustomerRequirementPropertyPreference.customer_requirement_id
            == requirement.id,
            CustomerRequirementPropertyPreference.organization_id
            == organization_id,
        )
        .order_by(
            CustomerRequirementPropertyPreference.created_at.asc(),
            CustomerRequirementPropertyPreference.id.asc(),
        )
    )

    possession_parking_statement = select(
        CustomerRequirementPossessionParkingPreference
    ).where(
        CustomerRequirementPossessionParkingPreference.customer_requirement_id
        == requirement.id,
        CustomerRequirementPossessionParkingPreference.organization_id
        == organization_id,
    )

    locations = list(db.scalars(locations_statement).all())

    property_preferences = list(
        db.scalars(property_preferences_statement).all()
    )

    possession_parking = db.scalar(possession_parking_statement)

    return {
        "requirement": {
            "id": str(requirement.id),
            "organization_id": str(requirement.organization_id),
            "status": requirement.status,
            "is_active": requirement.is_active,
            "budget_min": _serialize_decimal(requirement.budget_min),
            "budget_max": _serialize_decimal(requirement.budget_max),
            "budget_currency": requirement.budget_currency,
            "lead_id": (
                str(requirement.lead_id)
                if requirement.lead_id is not None
                else None
            ),
            "customer_profile_id": (
                str(requirement.customer_profile_id)
                if requirement.customer_profile_id is not None
                else None
            ),
            "created_at": (
                requirement.created_at.isoformat()
                if requirement.created_at is not None
                else None
            ),
            "updated_at": (
                requirement.updated_at.isoformat()
                if requirement.updated_at is not None
                else None
            ),
        },
        "locations": [
            {
                "id": str(location.id),
                "organization_id": str(location.organization_id),
                "customer_requirement_id": str(
                    location.customer_requirement_id
                ),
                "city": location.city,
                "locality": location.locality,
                "is_active": location.is_active,
                "created_at": (
                    location.created_at.isoformat()
                    if location.created_at is not None
                    else None
                ),
                "updated_at": (
                    location.updated_at.isoformat()
                    if location.updated_at is not None
                    else None
                ),
            }
            for location in locations
        ],
        "property_preferences": [
            {
                "id": str(preference.id),
                "organization_id": str(preference.organization_id),
                "customer_requirement_id": str(
                    preference.customer_requirement_id
                ),
                "property_type": preference.property_type,
                "bhk_min": preference.bhk_min,
                "bhk_max": preference.bhk_max,
                "is_active": preference.is_active,
                "created_at": (
                    preference.created_at.isoformat()
                    if preference.created_at is not None
                    else None
                ),
                "updated_at": (
                    preference.updated_at.isoformat()
                    if preference.updated_at is not None
                    else None
                ),
            }
            for preference in property_preferences
        ],
        "possession_parking_preference": (
            {
                "id": str(possession_parking.id),
                "organization_id": str(possession_parking.organization_id),
                "customer_requirement_id": str(
                    possession_parking.customer_requirement_id
                ),
                "possession_preference": (
                    possession_parking.possession_preference
                ),
                "parking_preference": possession_parking.parking_preference,
                "parking_spaces_min": possession_parking.parking_spaces_min,
                "is_active": possession_parking.is_active,
                "created_at": (
                    possession_parking.created_at.isoformat()
                    if possession_parking.created_at is not None
                    else None
                ),
                "updated_at": (
                    possession_parking.updated_at.isoformat()
                    if possession_parking.updated_at is not None
                    else None
                ),
            }
            if possession_parking is not None
            else None
        ),
    }


def get_next_customer_requirement_history_version(
    db: Session,
    *,
    requirement_id: UUID,
    organization_id: UUID,
) -> int:
    """Return the next history version for a tenant-scoped requirement."""

    statement = (
        select(CustomerRequirementHistory.version)
        .where(
            CustomerRequirementHistory.customer_requirement_id
            == requirement_id,
            CustomerRequirementHistory.organization_id == organization_id,
        )
        .order_by(CustomerRequirementHistory.version.desc())
        .limit(1)
    )

    latest_version = db.scalar(statement)

    if latest_version is None:
        return 1

    return latest_version + 1


def create_customer_requirement_history(
    db: Session,
    *,
    requirement: CustomerRequirement,
    organization_id: UUID,
    actor_id: UUID,
    change_type: str,
) -> CustomerRequirementHistory:
    """
    Create and flush an immutable requirement history snapshot.

    The parent CustomerRequirement row is locked before allocating the
    next history version. This serializes concurrent history writes for
    the same requirement and prevents duplicate version allocation.
    """

    if requirement.organization_id != organization_id:
        raise ValueError("Customer requirement not found.")

    if not change_type.strip():
        raise ValueError("History change type is required.")

    # Ensure all pending changes to the requirement and its aggregate
    # are visible to the transaction before the history snapshot is built.
    db.flush()

    # Lock the parent requirement row for the duration of this transaction.
    #
    # This is the serialization point for history version allocation.
    # Concurrent transactions attempting to create history for the same
    # requirement must wait for this row lock to be released.
    locked_requirement = db.scalar(
        select(CustomerRequirement)
        .where(
            CustomerRequirement.id == requirement.id,
            CustomerRequirement.organization_id == organization_id,
        )
        .with_for_update()
    )

    if locked_requirement is None:
        raise ValueError("Customer requirement not found.")

    snapshot = build_customer_requirement_snapshot(
        db,
        requirement=locked_requirement,
        organization_id=organization_id,
    )

    version = get_next_customer_requirement_history_version(
        db,
        requirement_id=locked_requirement.id,
        organization_id=organization_id,
    )

    history = CustomerRequirementHistory(
        customer_requirement_id=locked_requirement.id,
        organization_id=organization_id,
        version=version,
        actor_id=actor_id,
        change_type=change_type,
        snapshot=snapshot,
    )

    db.add(history)
    db.flush()

    return history


def list_customer_requirement_history(
    db: Session,
    *,
    requirement_id: UUID,
    organization_id: UUID,
) -> list[CustomerRequirementHistory]:
    """
    Return all history entries for a tenant-owned requirement.

    History is ordered by version ascending so callers receive the
    requirement's evolution from earliest to latest state.
    """

    requirement_statement = select(CustomerRequirement.id).where(
        CustomerRequirement.id == requirement_id,
        CustomerRequirement.organization_id == organization_id,
    )

    requirement_exists = db.scalar(requirement_statement)

    if requirement_exists is None:
        raise ValueError("Customer requirement not found.")

    statement = (
        select(CustomerRequirementHistory)
        .where(
            CustomerRequirementHistory.customer_requirement_id
            == requirement_id,
            CustomerRequirementHistory.organization_id == organization_id,
        )
        .order_by(
            CustomerRequirementHistory.version.asc(),
            CustomerRequirementHistory.id.asc(),
        )
    )

    return list(db.scalars(statement).all())


def get_customer_requirement_history_version(
    db: Session,
    *,
    requirement_id: UUID,
    organization_id: UUID,
    version: int,
) -> CustomerRequirementHistory | None:
    """
    Return one history version for a tenant-owned requirement.

    The requirement and history rows must belong to the same verified
    organization. A missing requirement or missing version returns None
    so the API layer can expose the appropriate 404 response.
    """

    if version <= 0:
        raise ValueError("History version must be greater than zero.")

    statement = (
        select(CustomerRequirementHistory)
        .join(
            CustomerRequirement,
            CustomerRequirement.id
            == CustomerRequirementHistory.customer_requirement_id,
        )
        .where(
            CustomerRequirementHistory.customer_requirement_id
            == requirement_id,
            CustomerRequirementHistory.organization_id == organization_id,
            CustomerRequirementHistory.version == version,
            CustomerRequirement.organization_id == organization_id,
        )
    )

    return db.scalar(statement)
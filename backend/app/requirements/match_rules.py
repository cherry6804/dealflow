"""Versioned rules for explaining, ranking and fingerprinting property matches (DFR1-022).

The eligibility checks themselves stay in ``app/properties/matching_service.py``. This module reads their result and adds three
things an agent or a person needs: a classification (eligible, excluded or insufficient data) with the factors behind it, a
deterministic ranking among eligible properties, and an input fingerprint. Two runs with the same fingerprint used the same
requirement and the same inventory, so the stored ranking can be reproduced and a stale run can be recognised.

A score here is never a probability. Ranking uses only counts of configured criteria and the budget headroom, and each rank comes
with the basis it was given.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_location import CustomerRequirementLocation
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.property import Property
from app.properties.schemas import PropertyMatchResult

MATCH_RULESET_VERSION = "property-match-v1"
ELIGIBLE = "eligible"
EXCLUDED = "excluded"
INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class Classification:
    eligibility: str
    matched_factors: tuple[dict[str, str], ...]
    unmatched_factors: tuple[dict[str, str], ...]
    missing_information: tuple[dict[str, str], ...]
    exclusion_reasons: tuple[str, ...]
    configured_matches: int
    budget_headroom: Decimal | None = field(default=None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligibility": self.eligibility,
            "matched_factors": [dict(item) for item in self.matched_factors],
            "unmatched_factors": [dict(item) for item in self.unmatched_factors],
            "missing_information": [dict(item) for item in self.missing_information],
            "exclusion_reasons": list(self.exclusion_reasons),
            "configured_matches": self.configured_matches,
            "budget_headroom": str(self.budget_headroom) if self.budget_headroom is not None else None,
        }


def _amount(property_record: Property) -> Decimal | None:
    if property_record.transaction_type == Property.TRANSACTION_TYPE_SALE:
        return property_record.price
    if property_record.transaction_type == Property.TRANSACTION_TYPE_RENT:
        return property_record.rent
    return None


def _headroom(requirement: CustomerRequirement, property_record: Property) -> Decimal | None:
    """How far under the budget ceiling the price sits, as a fraction. Only computed when both figures are comparable."""
    amount = _amount(property_record)
    if requirement.budget_max is None or amount is None or requirement.budget_max <= 0 or amount > requirement.budget_max:
        return None
    return ((requirement.budget_max - amount) / requirement.budget_max).quantize(Decimal("0.0001"))


def classify(requirement: CustomerRequirement, result: PropertyMatchResult) -> Classification:
    """Sort one property's criteria into matched, unmatched, missing and excluded. Pure."""
    matched = tuple({"criterion": c.criterion, "explanation": c.explanation} for c in result.criteria if c.status == "MATCH")
    unmatched = tuple({"criterion": c.criterion, "explanation": c.explanation} for c in result.criteria if c.status == "MISMATCH")
    missing = tuple({"criterion": c.criterion, "explanation": c.explanation} for c in result.criteria if c.status == "UNKNOWN")
    if unmatched:
        eligibility = EXCLUDED
    elif missing:
        eligibility = INSUFFICIENT_DATA
    else:
        eligibility = ELIGIBLE
    headroom = None
    if eligibility == ELIGIBLE and result.property.transaction_type in (Property.TRANSACTION_TYPE_SALE, Property.TRANSACTION_TYPE_RENT):
        headroom = _headroom(requirement, result.property)
    return Classification(
        eligibility=eligibility,
        matched_factors=matched,
        unmatched_factors=unmatched,
        missing_information=missing,
        exclusion_reasons=tuple(item["explanation"] for item in unmatched),
        configured_matches=len(matched),
        budget_headroom=headroom,
    )


def rank(
    requirement: CustomerRequirement,
    results: list[PropertyMatchResult],
) -> list[tuple[PropertyMatchResult, Classification, int | None, dict[str, Any]]]:
    """Classify every result and rank the eligible ones.

    Order: eligible before insufficient data before excluded. Among eligible properties: more configured criteria matched first, then
    more budget headroom, then the newer listing, then the identifier. Only eligible properties receive a rank (1 is the best).
    """
    classified = [(result, classify(requirement, result)) for result in results]

    def key(item: tuple[PropertyMatchResult, Classification]):
        result, classification = item
        group = {ELIGIBLE: 0, INSUFFICIENT_DATA: 1, EXCLUDED: 2}[classification.eligibility]
        headroom = classification.budget_headroom or Decimal(0)
        created = result.property.created_at
        created_key = created.timestamp() if isinstance(created, datetime) else 0.0
        return (group, -classification.configured_matches, -float(headroom), -created_key, str(result.property.id))

    ordered = sorted(classified, key=key)
    eligible_total = sum(1 for _, classification in ordered if classification.eligibility == ELIGIBLE)
    output: list[tuple[PropertyMatchResult, Classification, int | None, dict[str, Any]]] = []
    position = 0
    for result, classification in ordered:
        if classification.eligibility == ELIGIBLE:
            position += 1
            basis = {
                "rule": MATCH_RULESET_VERSION,
                "rank": position,
                "of_eligible": eligible_total,
                "configured_matches": classification.configured_matches,
                "budget_headroom": str(classification.budget_headroom) if classification.budget_headroom is not None else None,
                "order": ["configured_matches", "budget_headroom", "listing_created_at", "property_id"],
            }
            output.append((result, classification, position, basis))
        else:
            output.append((result, classification, None, {"rule": MATCH_RULESET_VERSION, "reason": classification.eligibility}))
    return output


def compute_input_hash(db: Session, *, organization_id: UUID, requirement: CustomerRequirement) -> str:
    """A fingerprint of everything the matching outcome depends on: the requirement and its active criteria, and every available
    property in the organization. Equal fingerprints mean the same outcome; a change to any of them makes the old run stale."""
    locations = db.scalars(select(CustomerRequirementLocation).where(
        CustomerRequirementLocation.organization_id == organization_id,
        CustomerRequirementLocation.customer_requirement_id == requirement.id,
        CustomerRequirementLocation.is_active.is_(True),
    ).order_by(CustomerRequirementLocation.id)).all()
    preferences = db.scalars(select(CustomerRequirementPropertyPreference).where(
        CustomerRequirementPropertyPreference.organization_id == organization_id,
        CustomerRequirementPropertyPreference.customer_requirement_id == requirement.id,
        CustomerRequirementPropertyPreference.is_active.is_(True),
    ).order_by(CustomerRequirementPropertyPreference.id)).all()
    properties = db.scalars(select(Property).where(
        Property.organization_id == organization_id,
        Property.status == Property.STATUS_AVAILABLE,
    ).order_by(Property.id)).all()
    payload = {
        "ruleset": MATCH_RULESET_VERSION,
        "requirement": {
            "id": str(requirement.id),
            "status": requirement.status,
            "is_active": requirement.is_active,
            "transaction_type": requirement.transaction_type,
            "budget_min": str(requirement.budget_min) if requirement.budget_min is not None else None,
            "budget_max": str(requirement.budget_max) if requirement.budget_max is not None else None,
            "budget_currency": requirement.budget_currency,
            "locations": [[item.city, item.locality] for item in locations],
            "preferences": [[item.property_type, item.bhk_min, item.bhk_max] for item in preferences],
        },
        "properties": [
            [
                str(item.id), item.status, item.transaction_type, str(item.price), str(item.rent), item.currency,
                item.city, item.locality, item.property_type, item.bhk,
                item.updated_at.isoformat() if item.updated_at else None,
            ]
            for item in properties
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

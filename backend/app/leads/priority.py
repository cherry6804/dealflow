"""Explainable lead priority from the organization's own CRM records (DFR1-020).

The score is a sum of rule points, not a probability. Each rule reads one fact from a record in the lead's organization, and every
rule that contributes shows the value it read, the points it earned, the maximum it could earn, and the record it came from.
A rule whose fact is absent contributes nothing and is listed as missing. It is never guessed.

When too few rules have facts to read (``MIN_KNOWN_FACTORS_FOR_RULE_METHOD``), the result is labelled ``rule_based_baseline`` with
``insufficient_data`` set, so the caller sees that it is a baseline and not a full rule evaluation. Nothing here calls an AI model,
a provider or the gateway, so priority works when AI is off.

The rule set is versioned by ``RULESET_VERSION``. Every stored score records the version, the time it was computed, and a hash of
the facts it read, so the same facts can be recomputed and compared later. Human corrections are stored against a score for later
evaluation; they do not change the score that was computed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.activity import Activity
from app.db.models.contact import Contact
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_location import CustomerRequirementLocation
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead

RULESET_VERSION = "priority-rules-v1"
METHOD_RULE = "rule_based"
METHOD_BASELINE = "rule_based_baseline"
MIN_KNOWN_FACTORS_FOR_RULE_METHOD = 4
RECENT_ACTIVITY_DAYS = 7
ACTIVITY_WINDOW_DAYS = 30
MAX_REQUIREMENTS_SUMMARISED = 5
MAX_LOCATIONS_PER_REQUIREMENT = 10
MAX_PREFERENCES_PER_REQUIREMENT = 10
BANDS = ("high", "medium", "low")
NOT_APPLICABLE_STATUSES = frozenset({Lead.STATUS_WON, Lead.STATUS_LOST})

INTEREST_POINTS = {"HIGH": 25, "MEDIUM": 15, "LOW": 5}


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    known: bool
    points: int
    max_points: int
    observed: str | None
    source: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "known": self.known,
            "points": self.points,
            "max_points": self.max_points,
            "observed": self.observed,
            "source": self.source,
        }


@dataclass(frozen=True)
class PriorityResult:
    outcome: str  # scored or not_applicable
    reason_code: str
    score: int | None = None
    band: str | None = None
    method: str | None = None
    confidence: str | None = None
    insufficient_data: bool = False
    factors: tuple[Factor, ...] = ()
    missing_factors: tuple[str, ...] = ()
    requirements: tuple[dict[str, Any], ...] = ()
    input_hash: str | None = None
    ruleset_version: str = RULESET_VERSION
    computed_at: datetime | None = None


def band_for(score: int) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def confidence_for(known_factors: int) -> str:
    if known_factors >= 6:
        return "high"
    if known_factors >= MIN_KNOWN_FACTORS_FOR_RULE_METHOD:
        return "medium"
    return "low"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _requirement_summary(requirement: CustomerRequirement, locations: list[CustomerRequirementLocation],
                         preferences: list[CustomerRequirementPropertyPreference]) -> dict[str, Any]:
    """The requirement's facts as the scoring read them. Contact details of the customer are never included."""
    return {
        "requirement_id": str(requirement.id),
        "budget_min": str(requirement.budget_min) if requirement.budget_min is not None else None,
        "budget_max": str(requirement.budget_max) if requirement.budget_max is not None else None,
        "budget_currency": requirement.budget_currency,
        "locations": [
            {"record_id": str(row.id), "city": row.city, "locality": row.locality}
            for row in locations[:MAX_LOCATIONS_PER_REQUIREMENT]
        ],
        "property_preferences": [
            {"record_id": str(row.id), "property_type": row.property_type, "bhk_min": row.bhk_min, "bhk_max": row.bhk_max}
            for row in preferences[:MAX_PREFERENCES_PER_REQUIREMENT]
        ],
    }


def _input_hash(lead: Lead, facts: dict[str, Any]) -> str:
    encoded = json.dumps({"lead": str(lead.id), "status": lead.status, "facts": facts}, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_priority(db: Session, *, organization_id: UUID, lead_id: UUID, now: datetime | None = None) -> PriorityResult:
    """Read the lead's facts inside its organization and return the explainable result. Writes nothing."""
    moment = now or datetime.now(UTC)
    lead = db.scalar(select(Lead).where(Lead.id == lead_id, Lead.organization_id == organization_id))
    if lead is None:
        return PriorityResult(outcome="not_found", reason_code="lead_not_found")
    if not lead.is_active or lead.status in NOT_APPLICABLE_STATUSES:
        return PriorityResult(outcome="not_applicable", reason_code="lead_closed_or_inactive")

    contact = db.scalar(select(Contact).where(Contact.id == lead.contact_id, Contact.organization_id == organization_id))
    last_activity_at = db.scalar(
        select(func.max(Activity.created_at)).where(Activity.lead_id == lead.id, Activity.organization_id == organization_id)
    )
    latest_touch = max(value for value in (lead.updated_at, last_activity_at) if value is not None)
    if latest_touch.tzinfo is None:
        latest_touch = latest_touch.replace(tzinfo=UTC)
    pending_follow_ups = db.scalar(select(func.count()).select_from(FollowUp).where(
        FollowUp.lead_id == lead.id,
        FollowUp.organization_id == organization_id,
        FollowUp.status == FollowUp.STATUS_PENDING,
        FollowUp.due_at >= moment,
    )) or 0
    requirements = list(db.scalars(select(CustomerRequirement).where(
        CustomerRequirement.lead_id == lead.id,
        CustomerRequirement.organization_id == organization_id,
        CustomerRequirement.is_active.is_(True),
    ).order_by(CustomerRequirement.created_at, CustomerRequirement.id).limit(MAX_REQUIREMENTS_SUMMARISED)).all())

    summaries: list[dict[str, Any]] = []
    locations_total = 0
    preferences_total = 0
    budget_points = 0
    budget_known = bool(requirements)
    budget_observed = None
    for requirement in requirements:
        locations = list(db.scalars(select(CustomerRequirementLocation).where(
            CustomerRequirementLocation.customer_requirement_id == requirement.id,
            CustomerRequirementLocation.organization_id == organization_id,
            CustomerRequirementLocation.is_active.is_(True),
        ).order_by(CustomerRequirementLocation.id)).all())
        preferences = list(db.scalars(select(CustomerRequirementPropertyPreference).where(
            CustomerRequirementPropertyPreference.customer_requirement_id == requirement.id,
            CustomerRequirementPropertyPreference.organization_id == organization_id,
            CustomerRequirementPropertyPreference.is_active.is_(True),
        ).order_by(CustomerRequirementPropertyPreference.id)).all())
        locations_total += len(locations)
        preferences_total += len(preferences)
        if requirement.budget_max is not None:
            budget_points = max(budget_points, 15)
            budget_observed = str(requirement.budget_max)
        elif requirement.budget_min is not None:
            budget_points = max(budget_points, 10)
            budget_observed = str(requirement.budget_min)
        summaries.append(_requirement_summary(requirement, locations, preferences))

    recent = latest_touch >= moment - timedelta(days=RECENT_ACTIVITY_DAYS)
    within_window = latest_touch >= moment - timedelta(days=ACTIVITY_WINDOW_DAYS)
    activity_points = 20 if recent else 10 if within_window else 0
    interest_points = INTEREST_POINTS.get(lead.interest or "", 0)
    reachable = bool(contact and (contact.email or contact.phone))

    factors = (
        Factor("interest", "Stated interest", lead.interest is not None, interest_points, 25,
               lead.interest, {"entity": "lead", "id": str(lead.id), "field": "interest"}),
        Factor("recent_activity", "Recent activity", True, activity_points, 20,
               _iso(latest_touch), {"entity": "lead", "id": str(lead.id), "field": "updated_at or activity"}),
        Factor("budget", "Stated budget", budget_known, budget_points if budget_known else 0, 15,
               budget_observed, {"entity": "customer_requirement", "id": ",".join(s["requirement_id"] for s in summaries),
                                 "field": "budget_max or budget_min"}),
        Factor("locations", "Preferred locations", budget_known, 10 if locations_total else 0, 10,
               str(locations_total) if budget_known else None,
               {"entity": "customer_requirement_location", "id": ",".join(s["requirement_id"] for s in summaries),
                "field": "is_active"}),
        Factor("property_preferences", "Property preferences", budget_known, 10 if preferences_total else 0, 10,
               str(preferences_total) if budget_known else None,
               {"entity": "customer_requirement_property_preference",
                "id": ",".join(s["requirement_id"] for s in summaries), "field": "is_active"}),
        Factor("follow_up", "Upcoming follow-up", True, 10 if pending_follow_ups else 0, 10,
               str(pending_follow_ups), {"entity": "follow_up", "id": str(lead.id), "field": "status and due_at"}),
        Factor("reachability", "Contact details on file", contact is not None, 10 if reachable else 0, 10,
               "yes" if reachable else "no", {"entity": "contact", "id": str(lead.contact_id), "field": "email or phone"}),
    )
    known = sum(1 for factor in factors if factor.known)
    score = min(100, sum(factor.points for factor in factors))
    method = METHOD_RULE if known >= MIN_KNOWN_FACTORS_FOR_RULE_METHOD else METHOD_BASELINE
    facts = {factor.key: factor.observed for factor in factors}
    return PriorityResult(
        outcome="scored",
        reason_code="ok",
        score=score,
        band=band_for(score),
        method=method,
        confidence=confidence_for(known),
        insufficient_data=method == METHOD_BASELINE,
        factors=factors,
        missing_factors=tuple(factor.key for factor in factors if not factor.known),
        requirements=tuple(summaries),
        input_hash=_input_hash(lead, facts),
        computed_at=moment,
    )

"""Evaluate a requirement against available inventory, store the run, and recommend next actions (DFR1-022).

Evaluation reuses the existing matching engine and the existing run history (``create_requirement_match_run``). It adds only the
ranking and fingerprint from ``match_rules`` and the recommendations below. Evaluating the same requirement and inventory again
returns the stored run, so a duplicate request writes nothing. The requirement row is locked for the whole evaluation, so two
concurrent requests produce one run.

Recommendations are deterministic. Each one states the facts it rests on and the basis it has: a verified CRM fact, a deterministic
matching finding, or missing information. No recommendation here is an AI suggestion. A recommendation that belongs to an out of date
run is shown as stale, and a member cannot decide on it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.attribution import user_attribution
from app.audit.independent import OUTCOME_COMPLETED, persist_independent_audit_event
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_location import CustomerRequirementLocation
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.follow_up import FollowUp
from app.db.models.next_best_action import NextBestActionRecommendation
from app.db.models.requirement_match_run import RequirementMatchRun
from app.db.models.requirement_match_run_result import RequirementMatchRunResult
from app.db.models.requirement_property_shortlist import RequirementPropertyShortlist
from app.governance.execution_gate import actor_permission_granted
from app.requirements.match_history_service import create_requirement_match_run
from app.requirements.match_rules import (
    ELIGIBLE,
    INSUFFICIENT_DATA,
    MATCH_RULESET_VERSION,
    compute_input_hash,
)

NBA_RULESET_VERSION = "next-best-action-v1"
MATCH_AUDIT_EVENT = "property_match"
MAX_REVIEW_PROPERTIES = 3

CATEGORY_MISSING_INFORMATION = "request_missing_information"
CATEGORY_REVIEW_PROPERTY = "review_property"
CATEGORY_SITE_VISIT = "arrange_site_visit"
CATEGORY_FOLLOW_UP = "follow_up_lead"
CATEGORY_ESCALATE = "escalate_to_human"
DECISIONS = {
    "accepted": (NextBestActionRecommendation.STATUS_OPEN,),
    "dismissed": (NextBestActionRecommendation.STATUS_OPEN, NextBestActionRecommendation.STATUS_ACCEPTED),
    "done": (NextBestActionRecommendation.STATUS_ACCEPTED,),
}

REASON_NOT_FOUND = "requirement_not_found"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_STALE = "recommendation_stale"
REASON_INVALID_TRANSITION = "invalid_transition"
REASON_NOT_FOUND_RECOMMENDATION = "recommendation_not_found"
REASON_INVALID_DECISION = "invalid_decision"


class EvaluationError(Exception):
    def __init__(self, reason: str, problems: list[str] | None = None, *, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problems = problems or []
        self.status = status


def _require(db: Session, *, organization_id: UUID, actor_id: UUID, permission: str) -> None:
    if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id, permission_key=permission):
        raise EvaluationError(REASON_PERMISSION_DENIED, status=403)


def _locked_active_requirement(db: Session, *, organization_id: UUID, requirement_id: UUID) -> CustomerRequirement:
    requirement = db.scalar(select(CustomerRequirement).where(
        CustomerRequirement.id == requirement_id,
        CustomerRequirement.organization_id == organization_id,
        CustomerRequirement.status == CustomerRequirement.STATUS_ACTIVE,
        CustomerRequirement.is_active.is_(True),
    ).with_for_update())
    if requirement is None:
        raise EvaluationError(REASON_NOT_FOUND, status=404)
    return requirement


def _latest_run(db: Session, *, organization_id: UUID, requirement_id: UUID) -> RequirementMatchRun | None:
    return db.scalar(select(RequirementMatchRun).where(
        RequirementMatchRun.organization_id == organization_id,
        RequirementMatchRun.customer_requirement_id == requirement_id,
    ).order_by(RequirementMatchRun.created_at.desc(), RequirementMatchRun.id.desc()).limit(1))


def is_run_stale(db: Session, *, organization_id: UUID, run: RequirementMatchRun) -> bool:
    """True when the requirement or the available inventory changed after the run, or the run predates the fingerprint."""
    if run.input_hash is None or run.ruleset_version != MATCH_RULESET_VERSION:
        return True
    requirement = db.scalar(select(CustomerRequirement).where(
        CustomerRequirement.id == run.customer_requirement_id,
        CustomerRequirement.organization_id == organization_id,
    ))
    if requirement is None:
        return True
    return compute_input_hash(db, organization_id=organization_id, requirement=requirement) != run.input_hash


def _shortlisted_ids(db: Session, *, organization_id: UUID, requirement_id: UUID) -> set[str]:
    return {str(item) for item in db.scalars(select(RequirementPropertyShortlist.property_id).where(
        RequirementPropertyShortlist.organization_id == organization_id,
        RequirementPropertyShortlist.customer_requirement_id == requirement_id,
    )).all()}


def _pending_follow_ups(db: Session, *, organization_id: UUID, lead_id: UUID | None) -> int:
    if lead_id is None:
        return 0
    return int(db.scalar(select(func.count()).select_from(FollowUp).where(
        FollowUp.organization_id == organization_id,
        FollowUp.lead_id == lead_id,
        FollowUp.status == FollowUp.STATUS_PENDING,
    )) or 0)


def _property_title(snapshot: dict[str, Any]) -> str:
    parts = [str(snapshot.get("bhk")) + " BHK" if snapshot.get("bhk") else None, snapshot.get("property_type"),
             snapshot.get("locality"), snapshot.get("city")]
    return ", ".join(part for part in parts if part) or "Property"


def _add(db: Session, *, organization_id: UUID, requirement_id: UUID, run_id: UUID, category: str, subject_key: str,
         basis: str, priority: int, summary: str, facts: dict[str, Any],
         subject_property_id: UUID | None = None) -> NextBestActionRecommendation:
    row = NextBestActionRecommendation(
        organization_id=organization_id,
        customer_requirement_id=requirement_id,
        match_run_id=run_id,
        category=category,
        subject_key=subject_key,
        basis=basis,
        status=NextBestActionRecommendation.STATUS_OPEN,
        priority=priority,
        summary=summary[:500],
        subject_property_id=subject_property_id,
        facts=facts,
        ruleset_version=NBA_RULESET_VERSION,
        history=[],
    )
    db.add(row)
    return row


def generate_recommendations(db: Session, *, organization_id: UUID, requirement: CustomerRequirement,
                             run: RequirementMatchRun, results: list[RequirementMatchRunResult]) -> list[NextBestActionRecommendation]:
    """Create the recommendations for one run. Deterministic: the same run always yields the same recommendations."""
    eligible = sorted((r for r in results if r.eligibility == ELIGIBLE), key=lambda r: r.rank or 0)
    insufficient = [r for r in results if r.eligibility == INSUFFICIENT_DATA]
    excluded = [r for r in results if r.eligibility == "excluded"]
    shortlisted = _shortlisted_ids(db, organization_id=organization_id, requirement_id=requirement.id)
    rows: list[NextBestActionRecommendation] = []

    missing: list[str] = []
    if requirement.transaction_type is None:
        missing.append("transaction_type")
    if requirement.budget_min is None and requirement.budget_max is None:
        missing.append("budget")
    active_locations = db.scalar(select(func.count()).select_from(CustomerRequirementLocation).where(
        CustomerRequirementLocation.organization_id == organization_id,
        CustomerRequirementLocation.customer_requirement_id == requirement.id,
        CustomerRequirementLocation.is_active.is_(True),
    )) or 0
    if active_locations == 0:
        missing.append("location")
    active_preferences = db.scalar(select(func.count()).select_from(CustomerRequirementPropertyPreference).where(
        CustomerRequirementPropertyPreference.organization_id == organization_id,
        CustomerRequirementPropertyPreference.customer_requirement_id == requirement.id,
        CustomerRequirementPropertyPreference.is_active.is_(True),
    )) or 0
    if active_preferences == 0:
        missing.append("property_preference")
    if missing:
        rows.append(_add(
            db, organization_id=organization_id, requirement_id=requirement.id, run_id=run.id,
            category=CATEGORY_MISSING_INFORMATION, subject_key="requirement", basis="missing_information", priority=2,
            summary="Record the missing requirement details: " + ", ".join(missing).replace("_", " ") + ".",
            facts={"missing": missing, "source": {"entity": "customer_requirement", "id": str(requirement.id)}},
        ))

    for position, result in enumerate(eligible[:MAX_REVIEW_PROPERTIES], start=1):
        property_id = str(result.property_id)
        if property_id in shortlisted:
            continue
        snapshot = result.property_snapshot or {}
        rows.append(_add(
            db, organization_id=organization_id, requirement_id=requirement.id, run_id=run.id,
            category=CATEGORY_REVIEW_PROPERTY, subject_key=f"property:{property_id}", basis="deterministic_match",
            priority=1 if position == 1 else 2,
            summary=f"Review {_property_title(snapshot)}: eligible, rank {result.rank} of {len(eligible)}.",
            facts={"rank": result.rank, "eligible_count": len(eligible),
                   "matched_factors": (result.ranking_basis or {}).get("matched_factors", []),
                   "source": {"entity": "property", "id": property_id}},
            subject_property_id=result.property_id,
        ))

    for result in eligible:
        property_id = str(result.property_id)
        if property_id not in shortlisted:
            continue
        rows.append(_add(
            db, organization_id=organization_id, requirement_id=requirement.id, run_id=run.id,
            category=CATEGORY_SITE_VISIT, subject_key=f"property:{property_id}", basis="deterministic_match", priority=1,
            summary=f"Arrange a site visit for {_property_title(result.property_snapshot or {})}. No visit is booked by this step.",
            facts={"rank": result.rank, "source": {"entity": "property", "id": property_id}},
            subject_property_id=result.property_id,
        ))

    pending = _pending_follow_ups(db, organization_id=organization_id, lead_id=requirement.lead_id)
    if requirement.lead_id is not None and eligible and pending == 0:
        rows.append(_add(
            db, organization_id=organization_id, requirement_id=requirement.id, run_id=run.id,
            category=CATEGORY_FOLLOW_UP, subject_key="lead", basis="verified_fact", priority=2,
            summary="No pending follow-up is recorded for this lead. Follow up on the eligible properties.",
            facts={"pending_follow_ups": 0, "eligible_count": len(eligible),
                   "source": {"entity": "lead", "id": str(requirement.lead_id)}},
        ))

    if not eligible:
        if insufficient:
            summary = (f"{len(insufficient)} available propert{'y' if len(insufficient) == 1 else 'ies'} could not be checked "
                       "because data is missing. A person should complete the inventory data or decide the next step.")
            basis = "missing_information"
        else:
            summary = ("No available property matches the recorded requirement. A person should decide whether to change the "
                       "requirement or search elsewhere.")
            basis = "deterministic_match"
        rows.append(_add(
            db, organization_id=organization_id, requirement_id=requirement.id, run_id=run.id,
            category=CATEGORY_ESCALATE, subject_key="requirement", basis=basis, priority=1, summary=summary,
            facts={"eligible_count": 0, "insufficient_data_count": len(insufficient), "excluded_count": len(excluded),
                   "source": {"entity": "property_match_run", "id": str(run.id)}},
        ))

    db.flush()
    return rows


def _audit(db: Session, *, organization_id: UUID, actor_id: UUID, action: str, requirement_id: UUID,
           metadata: dict[str, Any]) -> None:
    persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=actor_id),
        event_type=MATCH_AUDIT_EVENT,
        action=action,
        decision="allowed",
        outcome=OUTCOME_COMPLETED,
        permission_key="requirements.update",
        resource_type="customer_requirement",
        resource_id=str(requirement_id),
        metadata=metadata,
    )


def evaluate_requirement(db: Session, *, organization_id: UUID, actor_id: UUID,
                         requirement_id: UUID) -> tuple[RequirementMatchRun, bool]:
    """Evaluate and store a run, or return the stored run when nothing changed since it. Returns ``(run, created)``."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="requirements.update")
    requirement = _locked_active_requirement(db, organization_id=organization_id, requirement_id=requirement_id)
    digest = compute_input_hash(db, organization_id=organization_id, requirement=requirement)
    latest = _latest_run(db, organization_id=organization_id, requirement_id=requirement.id)
    if latest is not None and latest.input_hash == digest and latest.ruleset_version == MATCH_RULESET_VERSION:
        return latest, False

    try:
        run, saved = create_requirement_match_run(db, organization_id=organization_id, requirement_id=requirement.id,
                                                  actor_id=actor_id)
    except ValueError as error:
        raise EvaluationError(REASON_NOT_FOUND, [str(error)], status=404) from error
    generate_recommendations(db, organization_id=organization_id, requirement=requirement, run=run, results=saved)
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="property_match.evaluated",
           requirement_id=requirement.id,
           metadata={"run_id": str(run.id), "eligible": sum(1 for r in saved if r.eligibility == ELIGIBLE),
                     "ruleset_version": MATCH_RULESET_VERSION})
    return run, True


def latest_evaluation(db: Session, *, organization_id: UUID, actor_id: UUID, requirement_id: UUID) -> dict[str, Any] | None:
    """The latest stored run with its ranked results and recommendations, each flagged stale when out of date. Read only."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="requirements.read")
    if db.scalar(select(CustomerRequirement.id).where(
        CustomerRequirement.id == requirement_id, CustomerRequirement.organization_id == organization_id,
    )) is None:
        raise EvaluationError(REASON_NOT_FOUND, status=404)
    run = _latest_run(db, organization_id=organization_id, requirement_id=requirement_id)
    if run is None:
        return None
    stale = is_run_stale(db, organization_id=organization_id, run=run)
    results = list(db.scalars(select(RequirementMatchRunResult).where(
        RequirementMatchRunResult.organization_id == organization_id,
        RequirementMatchRunResult.match_run_id == run.id,
    )).all())
    results.sort(key=lambda r: (r.rank is None, r.rank or 0, str(r.property_id)))
    recommendations = list(db.scalars(select(NextBestActionRecommendation).where(
        NextBestActionRecommendation.organization_id == organization_id,
        NextBestActionRecommendation.match_run_id == run.id,
    ).order_by(NextBestActionRecommendation.priority, NextBestActionRecommendation.category,
               NextBestActionRecommendation.subject_key)).all())
    return {"run": run, "stale": stale, "results": results, "recommendations": recommendations}


def record_feedback(db: Session, *, organization_id: UUID, actor_id: UUID, recommendation_id: UUID, decision: str,
                    reason: str | None) -> NextBestActionRecommendation:
    """Record a member's decision on a recommendation. Stale recommendations cannot be decided. History is appended, never rewritten."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="requirements.update")
    if decision not in DECISIONS:
        raise EvaluationError(REASON_INVALID_DECISION, ["The decision must be accepted, dismissed or done."], status=422)
    row = db.scalar(select(NextBestActionRecommendation).where(
        NextBestActionRecommendation.id == recommendation_id,
        NextBestActionRecommendation.organization_id == organization_id,
    ).with_for_update())
    if row is None:
        raise EvaluationError(REASON_NOT_FOUND_RECOMMENDATION, status=404)
    run = db.get(RequirementMatchRun, row.match_run_id)
    if run is None or run.organization_id != organization_id:
        raise EvaluationError(REASON_NOT_FOUND_RECOMMENDATION, status=404)
    if is_run_stale(db, organization_id=organization_id, run=run):
        raise EvaluationError(REASON_STALE, ["The requirement or inventory changed after this recommendation. Evaluate again first."])
    if row.status not in DECISIONS[decision]:
        raise EvaluationError(REASON_INVALID_TRANSITION, [f"A {row.status} recommendation cannot be {decision}."])

    now = datetime.now(UTC)
    previous = row.status
    row.status = {"accepted": NextBestActionRecommendation.STATUS_ACCEPTED,
                  "dismissed": NextBestActionRecommendation.STATUS_DISMISSED,
                  "done": NextBestActionRecommendation.STATUS_DONE}[decision]
    row.decided_by_user_id = actor_id
    row.decided_at = now
    row.updated_at = now
    row.history = [*(row.history or []), {"from": previous, "to": row.status, "by": str(actor_id), "at": now.isoformat(),
                                          "reason": (reason or "").strip()[:500] or None}]
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="next_best_action.decided",
           requirement_id=row.customer_requirement_id,
           metadata={"recommendation_id": str(row.id), "category": row.category, "to": row.status})
    return row

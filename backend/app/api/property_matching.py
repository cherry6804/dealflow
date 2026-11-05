"""Property matching evaluation, ranked results, recommendations and feedback over HTTP (DFR1-022).

Every route is scoped to the verified organization. Reading needs ``requirements.read``. Evaluating, recording a transaction type and
deciding on a recommendation need ``requirements.update`` and are attributed to the signed-in member. Responses carry the rule
versions and the stale flag, and never describe a heuristic as a probability.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.next_best_action import NextBestActionRecommendation
from app.db.models.requirement_match_run import RequirementMatchRun
from app.db.models.requirement_match_run_result import RequirementMatchRunResult
from app.db.session import get_db_session
from app.requirements.history_service import create_customer_requirement_history
from app.requirements.match_evaluation_service import (
    NBA_RULESET_VERSION,
    EvaluationError,
    evaluate_requirement,
    latest_evaluation,
    record_feedback,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(tags=["property-matching"])

DISCLAIMER = (
    "Rule-based matching against recorded requirement and inventory facts. Eligibility is decided by the rules, and rank orders "
    "eligible properties by the criteria counted. This is not a probability."
)


class TransactionTypeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_type: Literal["SALE", "RENT", "LEASE"] | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=20)
    reason: str | None = Field(default=None, max_length=500)


def _raise(error: EvaluationError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _result_body(row: RequirementMatchRunResult) -> dict[str, Any]:
    basis = row.ranking_basis or {}
    return {
        "property_id": str(row.property_id),
        "rank": row.rank,
        "eligibility": row.eligibility,
        "overall_match": row.overall_match,
        "criteria": row.criteria_results_snapshot,
        "matched_factors": basis.get("matched_factors", []),
        "unmatched_factors": basis.get("unmatched_factors", []),
        "missing_information": basis.get("missing_information", []),
        "exclusion_reasons": basis.get("exclusion_reasons", []),
        "ranking_basis": {key: value for key, value in basis.items() if key not in {
            "matched_factors", "unmatched_factors", "missing_information", "exclusion_reasons", "eligibility"}},
        "property": row.property_snapshot,
    }


def _recommendation_body(row: NextBestActionRecommendation, *, stale: bool) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "category": row.category,
        "basis": row.basis,
        "status": row.status,
        "priority": row.priority,
        "summary": row.summary,
        "subject_property_id": str(row.subject_property_id) if row.subject_property_id else None,
        "facts": row.facts,
        "ruleset_version": row.ruleset_version,
        "stale": stale,
        "history": row.history,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


def _run_body(run: RequirementMatchRun, *, stale: bool, results: list[RequirementMatchRunResult],
              recommendations: list[NextBestActionRecommendation]) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "requirement_id": str(run.customer_requirement_id),
        "evaluated_at": run.created_at.isoformat() if run.created_at else None,
        "evaluated_by_user_id": str(run.actor_id),
        "ruleset_version": run.ruleset_version,
        "next_best_action_ruleset_version": NBA_RULESET_VERSION,
        "input_fingerprint": run.input_hash,
        "stale": stale,
        "total_candidates": run.total_candidates,
        "eligible_count": sum(1 for r in results if r.eligibility == "eligible"),
        "results": [_result_body(r) for r in results],
        "recommendations": [_recommendation_body(r, stale=stale) for r in recommendations],
        "disclaimer": DISCLAIMER,
    }


@router.post("/api/v1/customer-requirements/{requirement_id}/match-evaluations")
def evaluate_endpoint(
    requirement_id: UUID,
    response: Response,
    tenant: TenantContext = Depends(require_permission("requirements.update")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Evaluate the requirement. Returns the stored run (200) when nothing changed since it, or a new run (201)."""
    try:
        run, created = evaluate_requirement(db, organization_id=tenant.organization_id,
                                            actor_id=user_context.user.id, requirement_id=requirement_id)
        db.commit()
    except EvaluationError as error:
        db.rollback()
        _raise(error)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    latest = latest_evaluation(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                               requirement_id=requirement_id)
    assert latest is not None
    return dict(_run_body(run, stale=False, results=latest["results"], recommendations=latest["recommendations"]),
                created=created)


@router.get("/api/v1/customer-requirements/{requirement_id}/match-evaluations/latest")
def latest_endpoint(
    requirement_id: UUID,
    tenant: TenantContext = Depends(require_permission("requirements.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any] | None:
    """The latest stored evaluation, or null when none exists. A stale evaluation is marked as stale, not as current."""
    try:
        latest = latest_evaluation(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                                   requirement_id=requirement_id)
    except EvaluationError as error:
        _raise(error)
    if latest is None:
        return None
    return _run_body(latest["run"], stale=latest["stale"], results=latest["results"],
                     recommendations=latest["recommendations"])


@router.put("/api/v1/customer-requirements/{requirement_id}/transaction-type")
def transaction_type_endpoint(
    requirement_id: UUID,
    payload: TransactionTypeRequest,
    tenant: TenantContext = Depends(require_permission("requirements.update")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Record whether the customer wants to buy (SALE), rent (RENT) or lease (LEASE). Matching uses it from the next evaluation."""
    row = db.scalar(select(CustomerRequirement).where(
        CustomerRequirement.id == requirement_id,
        CustomerRequirement.organization_id == tenant.organization_id,
    ).with_for_update())
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"reason": "requirement_not_found"})
    row.transaction_type = payload.transaction_type
    create_customer_requirement_history(
        db,
        requirement=row,
        organization_id=tenant.organization_id,
        actor_id=user_context.user.id,
        change_type="REQUIREMENT_UPDATED",
    )
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "transaction_type": row.transaction_type}


@router.post("/api/v1/next-best-actions/{recommendation_id}/feedback")
def feedback_endpoint(
    recommendation_id: UUID,
    payload: FeedbackRequest,
    tenant: TenantContext = Depends(require_permission("requirements.update")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = record_feedback(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                              recommendation_id=recommendation_id, decision=payload.decision, reason=payload.reason)
        db.commit()
    except EvaluationError as error:
        db.rollback()
        _raise(error)
    return _recommendation_body(row, stale=False)


__all__ = ["router"]

"""Explainable lead priority over HTTP (DFR1-020).

Every route is scoped to the verified organization and checks one permission. The score is rule points from recorded CRM facts. It
is not a probability, and the response says so. Errors carry a stable reason and, for validation, the problems found.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.models.lead_priority import LeadPriorityCorrection, LeadPriorityScore
from app.db.session import get_db_session
from app.leads.priority import METHOD_BASELINE, RULESET_VERSION
from app.leads.priority_service import (
    PriorityError,
    calculate_and_store,
    list_corrections,
    list_scores,
    record_correction,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/leads", tags=["lead-priority"])

DISCLAIMER = (
    "Rule points calculated from recorded CRM facts. This is not a probability and it is not calibrated. "
    "A label of rule_based_baseline means too few facts were available for a full rule evaluation."
)


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrected_band: str | None = Field(default=None, max_length=10)
    corrected_score: int | None = Field(default=None, ge=0, le=100)
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=120)


def _raise(error: PriorityError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _score_body(row: LeadPriorityScore) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "lead_id": str(row.lead_id),
        "score": row.score,
        "band": row.band,
        "method": row.method,
        "confidence": row.confidence,
        "insufficient_data": row.insufficient_data,
        "ruleset_version": row.ruleset_version,
        "computed_at": row.computed_at.isoformat(),
        "computed_by_user_id": str(row.computed_by_user_id),
        "factors": row.factors,
        "missing_factors": row.missing_factors,
        "requirements": row.requirement_summary,
        "input_hash": row.input_hash,
        "disclaimer": DISCLAIMER,
    }


def _correction_body(row: LeadPriorityCorrection) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "score_id": str(row.score_id),
        "corrected_band": row.corrected_band,
        "corrected_score": row.corrected_score,
        "reason": row.reason,
        "actor_user_id": str(row.actor_user_id),
        "created_at": row.created_at.isoformat(),
    }


@router.post("/{lead_id}/priority", status_code=status.HTTP_201_CREATED)
def calculate_priority_endpoint(
    lead_id: UUID,
    tenant: TenantContext = Depends(require_permission("leads.update")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Calculate and store a new priority for the lead. Earlier scores are kept, so history shows how it changed."""
    try:
        row = calculate_and_store(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, lead_id=lead_id)
        db.commit()
    except PriorityError as error:
        db.rollback()
        _raise(error)
    return _score_body(row)


@router.get("/{lead_id}/priority")
def list_priority_endpoint(
    lead_id: UUID,
    limit: int = Query(default=10, ge=1, le=50),
    tenant: TenantContext = Depends(require_permission("leads.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        rows = list_scores(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                           lead_id=lead_id, limit=limit)
    except PriorityError as error:
        _raise(error)
    return {
        "ruleset_version": RULESET_VERSION,
        "latest": _score_body(rows[0]) if rows else None,
        "items": [_score_body(row) for row in rows],
        "baseline_label": METHOD_BASELINE,
    }


@router.post("/{lead_id}/priority/{score_id}/corrections")
def record_correction_endpoint(
    lead_id: UUID,
    score_id: UUID,
    payload: CorrectionRequest,
    tenant: TenantContext = Depends(require_permission("leads.update")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Record a human correction for evaluation. The score itself is not changed."""
    try:
        row, created = record_correction(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            lead_id=lead_id,
            score_id=score_id,
            corrected_band=payload.corrected_band,
            corrected_score=payload.corrected_score,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
    except PriorityError as error:
        db.rollback()
        _raise(error)
    body = _correction_body(row)
    body["created"] = created
    return body


@router.get("/{lead_id}/priority/{score_id}/corrections")
def list_corrections_endpoint(
    lead_id: UUID,
    score_id: UUID,
    tenant: TenantContext = Depends(require_permission("leads.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        rows = list_corrections(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                                lead_id=lead_id, score_id=score_id)
    except PriorityError as error:
        _raise(error)
    return {"items": [_correction_body(row) for row in rows]}


__all__ = ["router"]

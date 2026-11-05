"""Lead qualification results and human review over HTTP (DFR1-021).

Reading results needs ``leads.read``. Recording a review needs ``leads.update`` and is attributed to the signed-in member. A
review changes only the review fields of the result. ``stale`` tells the reader that the lead changed after the findings were
recorded, so the findings may no longer describe it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.models.lead_intake import LeadQualificationResult
from app.db.session import get_db_session
from app.leads.qualification import (
    QualificationError,
    is_stale,
    list_qualifications,
    review_qualification,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(tags=["lead-qualification"])


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=20)
    reason: str | None = Field(default=None, max_length=500)


def _raise(error: QualificationError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _body(row: LeadQualificationResult, *, stale: bool) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "lead_id": str(row.lead_id),
        "execution_id": str(row.execution_id),
        "score_id": str(row.score_id),
        "requires_review": row.requires_review,
        "review_status": row.review_status,
        "review_reason": row.review_reason,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "reviewed_by_user_id": str(row.reviewed_by_user_id) if row.reviewed_by_user_id else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "stale": stale,
        "findings": row.findings,
    }


@router.get("/api/v1/leads/{lead_id}/qualifications")
def list_qualifications_endpoint(
    lead_id: UUID,
    limit: int = Query(default=20, ge=1, le=50),
    tenant: TenantContext = Depends(require_permission("leads.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        rows = list_qualifications(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                                   lead_id=lead_id, limit=limit)
    except QualificationError as error:
        _raise(error)
    return {"items": [_body(row, stale=is_stale(db, row)) for row in rows]}


@router.post("/api/v1/lead-qualifications/{qualification_id}/review")
def review_endpoint(
    qualification_id: UUID,
    payload: ReviewRequest,
    tenant: TenantContext = Depends(require_permission("leads.update")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = review_qualification(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            qualification_id=qualification_id,
            decision=payload.decision,
            reason=payload.reason,
        )
        db.commit()
    except QualificationError as error:
        db.rollback()
        _raise(error)
    return _body(row, stale=is_stale(db, row))


__all__ = ["router"]

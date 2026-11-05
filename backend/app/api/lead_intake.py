"""Lead intake over HTTP (DFR1-021).

Submitting, listing and reading a submission need the lead permissions of the signed-in member, scoped to the verified
organization. Processing and the human decision are separate permissions. Nothing here calls an AI model: intake works with AI
disabled, and only an agent run needs AI.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.models.lead_intake import LeadIntakeSubmission
from app.db.session import get_db_session
from app.leads.intake_service import (
    IntakeError,
    decide_submission,
    get_submission,
    list_submissions,
    process_submission,
    submit_intake,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/lead-intake", tags=["lead-intake"])


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_channel: str = Field(min_length=1, max_length=20)
    external_reference: str = Field(min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(min_length=1, max_length=20)
    contact_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


def _raise(error: IntakeError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _body(row: LeadIntakeSubmission) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "source_channel": row.source_channel,
        "external_reference": row.external_reference,
        "status": row.status,
        "validation_problems": row.validation_problems,
        "normalized": row.normalized_payload,
        "match_outcome": row.match_outcome,
        "candidate_contact_ids": row.candidate_contact_ids,
        "contact_id": str(row.contact_id) if row.contact_id else None,
        "lead_id": str(row.lead_id) if row.lead_id else None,
        "decision": row.decision,
        "decision_reason": row.decision_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
    }


@router.post("")
def submit_endpoint(
    payload: SubmitRequest,
    response: Response,
    tenant: TenantContext = Depends(require_permission("leads.create")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Store one submission. A repeated reference with the same content returns the stored submission (200), not a new one."""
    try:
        row, created = submit_intake(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            source_channel=payload.source_channel,
            external_reference=payload.external_reference,
            payload=payload.payload,
        )
        db.commit()
    except IntakeError as error:
        db.rollback()
        _raise(error)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return dict(_body(row), created=created)


@router.get("")
def list_endpoint(
    limit: int = Query(default=50, ge=1, le=100),
    tenant: TenantContext = Depends(require_permission("leads.read")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    rows = list_submissions(db, organization_id=tenant.organization_id, limit=limit)
    return {"items": [_body(row) for row in rows]}


@router.get("/{submission_id}")
def get_endpoint(
    submission_id: UUID,
    tenant: TenantContext = Depends(require_permission("leads.read")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = get_submission(db, organization_id=tenant.organization_id, submission_id=submission_id)
    except IntakeError as error:
        _raise(error)
    return _body(row)


@router.post("/{submission_id}/process")
def process_endpoint(
    submission_id: UUID,
    tenant: TenantContext = Depends(require_permission("leads.create")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = process_submission(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                                 submission_id=submission_id)
        db.commit()
    except IntakeError as error:
        db.rollback()
        _raise(error)
    return _body(row)


@router.post("/{submission_id}/decision")
def decision_endpoint(
    submission_id: UUID,
    payload: DecisionRequest,
    tenant: TenantContext = Depends(require_permission("leads.update")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """A person decides an uncertain match: attach to a matched contact, create a new contact, or reject."""
    try:
        row = decide_submission(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            submission_id=submission_id,
            decision=payload.decision,
            contact_id=payload.contact_id,
            reason=payload.reason,
        )
        db.commit()
    except IntakeError as error:
        db.rollback()
        _raise(error)
    return _body(row)


__all__ = ["router"]

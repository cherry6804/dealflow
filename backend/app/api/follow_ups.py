"""FastAPI routes for DealFlow follow-up operations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.follow_ups.schemas import (
    FollowUpCreateRequest,
    FollowUpResponse,
)
from app.follow_ups.service import create_follow_up
from app.tenant.dependencies import TenantContext


router = APIRouter(
    prefix="/api/v1/leads/{lead_id}/follow-ups",
    tags=["follow-ups"],
)


@router.post(
    "",
    response_model=FollowUpResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_follow_up_endpoint(
    lead_id: UUID,
    payload: FollowUpCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("leads.update"),
    ),
    db: Session = Depends(get_db_session),
) -> FollowUpResponse:
    """Create a follow-up for a lead in the verified tenant."""

    try:
        follow_up = create_follow_up(
            db=db,
            organization_id=tenant_context.organization_id,
            current_user_id=tenant_context.membership.user_id,
            lead_id=lead_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if follow_up is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found.",
        )

    db.commit()
    db.refresh(follow_up)

    return FollowUpResponse.model_validate(follow_up)

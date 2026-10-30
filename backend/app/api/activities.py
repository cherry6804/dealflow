"""FastAPI routes for DealFlow lead activity operations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.activities.schemas import (
    ActivityCreateRequest,
    ActivityListResponse,
    ActivityResponse,
)
from app.activities.service import (
    create_activity,
    list_lead_activities,
)
from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext


router = APIRouter(
    prefix="/api/v1/leads/{lead_id}/activities",
    tags=["activities"],
)


@router.post(
    "",
    response_model=ActivityResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_activity_endpoint(
    lead_id: UUID,
    payload: ActivityCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("leads.update"),
    ),
    db: Session = Depends(get_db_session),
) -> ActivityResponse:
    """Create an activity for a lead in the verified tenant."""
    activity = create_activity(
        db=db,
        organization_id=tenant_context.organization_id,
        actor_id=tenant_context.membership.user_id,
        lead_id=lead_id,
        payload=payload,
    )

    if activity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found.",
        )

    db.commit()
    db.refresh(activity)

    return ActivityResponse.model_validate(activity).model_copy(
        update={
            "actor_display_name": activity.actor.display_name,
        }
    )


@router.get(
    "",
    response_model=ActivityListResponse,
    status_code=status.HTTP_200_OK,
)
def list_activities_endpoint(
    lead_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("leads.read"),
    ),
    db: Session = Depends(get_db_session),
) -> ActivityListResponse:
    """Retrieve a lead's timeline within the verified tenant."""
    activities = list_lead_activities(
        db=db,
        organization_id=tenant_context.organization_id,
        lead_id=lead_id,
    )

    if activities is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found.",
        )

    return ActivityListResponse(
        items=[
            ActivityResponse.model_validate(activity).model_copy(
                update={
                    "actor_display_name": activity.actor.display_name,
                }
            )
            for activity in activities
        ],
    )

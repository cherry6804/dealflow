
"""FastAPI routes for DealFlow Lead operations."""

from __future__ import annotations

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.activities.schemas import ActivityListResponse, ActivityResponse
from app.activities.service import list_recent_activities
from app.authz.dependencies import require_permission
from app.db.models.lead import Lead
from app.db.session import get_db_session
from app.leads.schemas import (
    LeadCreateRequest,
    LeadInterest,
    LeadListResponse,
    LeadListQuery,
    LeadOutcome,
    LeadResponse,
    LeadStatus,
    LeadUpdateRequest,
)
from app.leads.service import (
    create_lead,
    get_lead,
    list_leads,
    update_lead,
)
from app.notifications.service import create_notification
from app.tenant.dependencies import TenantContext


router = APIRouter(
    prefix="/api/v1/leads",
    tags=["leads"],
)


def _notify_lead_user(
    db: Session,
    *,
    organization_id: UUID,
    recipient_user_id: UUID,
    lead: Lead,
    event_type: str,
    title: str,
    message: str,
    event_key: str,
) -> None:
    """Create a preference-aware notification for a Lead event."""
    create_notification(
        db,
        organization_id=organization_id,
        recipient_user_id=recipient_user_id,
        event_type=event_type,
        title=title,
        message=message,
        resource_type="lead",
        resource_id=str(lead.id),
        event_key=event_key,
    )


@router.post(
    "",
    response_model=LeadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_lead_endpoint(
    payload: LeadCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("leads.create"),
    ),
    db: Session = Depends(get_db_session),
) -> LeadResponse:
    """Create a Lead within the verified tenant."""
    lead = create_lead(
        db=db,
        organization_id=tenant_context.organization_id,
        payload=payload,
    )

    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contact not found.",
        )

    _notify_lead_user(
        db,
        organization_id=tenant_context.organization_id,
        recipient_user_id=tenant_context.membership.user_id,
        lead=lead,
        event_type="LEAD_CREATED",
        title="New lead created",
        message="A new lead has been created.",
        event_key=f"lead:{lead.id}:created",
    )

    db.commit()
    db.refresh(lead)

    return LeadResponse.model_validate(lead)


@router.get(
    "",
    response_model=LeadListResponse,
    status_code=status.HTTP_200_OK,
)
def list_leads_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=320),
    status: LeadStatus | None = Query(default=None),
    interest: LeadInterest | None = Query(default=None),
    outcome: LeadOutcome | None = Query(default=None),
    owner_user_id: UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    tenant_context: TenantContext = Depends(
        require_permission("leads.read"),
    ),
    db: Session = Depends(get_db_session),
) -> LeadListResponse:
    """List and filter Leads within the verified tenant."""
    query = LeadListQuery(
        page=page,
        page_size=page_size,
        search=search,
        status=status,
        interest=interest,
        outcome=outcome,
        owner_user_id=owner_user_id,
        is_active=is_active,
    )

    leads, total = list_leads(
        db=db,
        organization_id=tenant_context.organization_id,
        query=query,
    )

    total_pages = ceil(total / page_size) if total > 0 else 0

    return LeadListResponse(
        items=[
            LeadResponse.model_validate(lead)
            for lead in leads
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


@router.get(
    "/activities/recent",
    response_model=ActivityListResponse,
    status_code=status.HTTP_200_OK,
)
def list_recent_activities_endpoint(
    limit: int = Query(default=10, ge=1, le=50),
    tenant_context: TenantContext = Depends(
        require_permission("leads.read"),
    ),
    db: Session = Depends(get_db_session),
) -> ActivityListResponse:
    """List recent activities for the verified organization."""
    activities = list_recent_activities(
        db=db,
        organization_id=tenant_context.organization_id,
        limit=limit,
    )

    return ActivityListResponse(
        items=[
            ActivityResponse.model_validate(activity).model_copy(
                update={
                    "actor_display_name": (
                        activity.actor.display_name
                        if activity.actor
                        else None
                    ),
                }
            )
            for activity in activities
        ],
    )


@router.get(
    "/{lead_id}",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
)
def get_lead_endpoint(
    lead_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("leads.read"),
    ),
    db: Session = Depends(get_db_session),
) -> LeadResponse:
    """Retrieve a Lead within the verified tenant."""
    lead = get_lead(
        db=db,
        organization_id=tenant_context.organization_id,
        lead_id=lead_id,
    )

    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found.",
        )

    return LeadResponse.model_validate(lead)


@router.patch(
    "/{lead_id}",
    response_model=LeadResponse,
    status_code=status.HTTP_200_OK,
)
def update_lead_endpoint(
    lead_id: UUID,
    payload: LeadUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("leads.update"),
    ),
    db: Session = Depends(get_db_session),
) -> LeadResponse:
    """Update a Lead, record activities, and notify relevant users."""
    organization_id = tenant_context.organization_id
    actor_id = tenant_context.membership.user_id

    previous_lead = get_lead(
        db=db,
        organization_id=organization_id,
        lead_id=lead_id,
    )

    if previous_lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found.",
        )

    previous_status = previous_lead.status
    previous_owner_user_id = previous_lead.owner_user_id
    previous_next_action = previous_lead.next_action
    previous_next_action_at = previous_lead.next_action_at

    try:
        lead = update_lead(
            db=db,
            organization_id=organization_id,
            actor_id=actor_id,
            lead_id=lead_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found.",
        )

    # Notify the new owner when the Lead is assigned or reassigned.
    owner_changed = lead.owner_user_id != previous_owner_user_id

    if owner_changed and lead.owner_user_id is not None:
        _notify_lead_user(
            db,
            organization_id=organization_id,
            recipient_user_id=lead.owner_user_id,
            lead=lead,
            event_type="LEAD_ASSIGNED",
            title="Lead assigned to you",
            message="A lead has been assigned to you.",
            event_key=(
                f"lead:{lead.id}:assigned:"
                f"{lead.updated_at.isoformat()}"
            ),
        )

    # Notify the owner about status changes; if unassigned, notify the actor.
    if lead.status != previous_status:
        recipient_id = lead.owner_user_id or actor_id

        _notify_lead_user(
            db,
            organization_id=organization_id,
            recipient_user_id=recipient_id,
            lead=lead,
            event_type="LEAD_STATUS_CHANGED",
            title="Lead status updated",
            message=(
                f"Lead status changed from {previous_status} "
                f"to {lead.status}."
            ),
            event_key=(
                f"lead:{lead.id}:status:"
                f"{previous_status}:{lead.status}:"
                f"{lead.updated_at.isoformat()}"
            ),
        )

    # Notify the owner about next-action changes; fall back to the actor.
    next_action_changed = (
        lead.next_action != previous_next_action
        or lead.next_action_at != previous_next_action_at
    )

    if next_action_changed:
        recipient_id = lead.owner_user_id or actor_id

        _notify_lead_user(
            db,
            organization_id=organization_id,
            recipient_user_id=recipient_id,
            lead=lead,
            event_type="LEAD_NEXT_ACTION_CHANGED",
            title="Lead next action updated",
            message="The lead's next action or schedule has changed.",
            event_key=(
                f"lead:{lead.id}:next-action:"
                f"{lead.updated_at.isoformat()}"
            ),
        )

    # Commit the Lead update, activities, and notifications together.
    db.commit()
    db.refresh(lead)

    return LeadResponse.model_validate(lead)

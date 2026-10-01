"""FastAPI routes for DealFlow Lead operations."""

from __future__ import annotations

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
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
from app.tenant.dependencies import TenantContext


router = APIRouter(
    prefix="/api/v1/leads",
    tags=["leads"],
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

    db.commit()
    db.refresh(lead)

    return LeadResponse.model_validate(lead)


@router.get(
    "",
    response_model=LeadListResponse,
    status_code=status.HTTP_200_OK,
)
def list_leads_endpoint(
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    search: str | None = Query(
        default=None,
        min_length=1,
        max_length=320,
    ),
    status: LeadStatus | None = Query(
        default=None,
    ),
    interest: LeadInterest | None = Query(
        default=None,
    ),
    outcome: LeadOutcome | None = Query(
        default=None,
    ),
    owner_user_id: UUID | None = Query(
        default=None,
    ),
    is_active: bool | None = Query(
        default=None,
    ),
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

    total_pages = (
        ceil(total / page_size)
        if total > 0
        else 0
    )

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
    """Update a Lead within the verified tenant."""
    try:
        lead = update_lead(
            db=db,
            organization_id=tenant_context.organization_id,
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

    db.commit()
    db.refresh(lead)

    return LeadResponse.model_validate(lead)
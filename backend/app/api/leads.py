"""Lead API routes for DealFlow."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.leads.schemas import LeadCreateRequest, LeadResponse
from app.leads.service import create_lead, get_lead
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
"""Customer requirement API endpoints for DealFlow."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.requirements.schemas import (
    CustomerRequirementCreateRequest,
    CustomerRequirementResponse,
)
from app.requirements.service import (
    create_customer_requirement,
    get_customer_requirement,
)
from app.tenant.dependencies import TenantContext


router = APIRouter(
    prefix="/api/v1/customer-requirements",
    tags=["customer-requirements"],
)


@router.post(
    "",
    response_model=CustomerRequirementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_requirement(
    payload: CustomerRequirementCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.create"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementResponse:
    """Create a customer requirement within the verified tenant."""

    del payload

    try:
        requirement = create_customer_requirement(
            db=db,
            organization_id=tenant_context.organization_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(requirement)

    return CustomerRequirementResponse.model_validate(requirement)


@router.get(
    "/{requirement_id}",
    response_model=CustomerRequirementResponse,
    status_code=status.HTTP_200_OK,
)
def get_requirement(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementResponse:
    """Retrieve a customer requirement within the verified tenant."""

    requirement = get_customer_requirement(
        db=db,
        organization_id=tenant_context.organization_id,
        requirement_id=requirement_id,
    )

    if requirement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer requirement not found.",
        )

    return CustomerRequirementResponse.model_validate(requirement)
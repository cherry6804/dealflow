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
    CustomerRequirementUpdateRequest,
)
from app.requirements.service import (
    create_customer_requirement,
    get_customer_requirement,
    update_customer_requirement_budget,
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


@router.patch(
    "/{requirement_id}",
    response_model=CustomerRequirementResponse,
    status_code=status.HTTP_200_OK,
)
def update_requirement(
    requirement_id: UUID,
    payload: CustomerRequirementUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementResponse:
    """Update customer requirement budget information."""

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

    fields_set = payload.model_fields_set

    try:
        requirement = update_customer_requirement_budget(
            db=db,
            requirement=requirement,
            budget_min=payload.budget_min,
            budget_max=payload.budget_max,
            budget_currency=payload.budget_currency,
            update_budget_min="budget_min" in fields_set,
            update_budget_max="budget_max" in fields_set,
            update_budget_currency="budget_currency" in fields_set,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(requirement)

    return CustomerRequirementResponse.model_validate(requirement)
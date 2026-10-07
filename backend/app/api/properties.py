"""FastAPI routes for DealFlow Property operations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.properties.schemas import (
    PropertyCommercialResponse,
    PropertyCommercialUpdateRequest,
    PropertyCreateRequest,
    PropertyResponse,
)
from app.properties.service import (
    create_property,
    update_property_commercial,
)
from app.tenant.dependencies import TenantContext


router = APIRouter(
    prefix="/api/v1/properties",
    tags=["properties"],
)


@router.post(
    "",
    response_model=PropertyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_property_endpoint(
    payload: PropertyCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("properties.create"),
    ),
    db: Session = Depends(get_db_session),
) -> PropertyResponse:
    """Create a Property within the verified tenant."""

    property_record = create_property(
        db=db,
        organization_id=tenant_context.organization_id,
    )

    db.commit()
    db.refresh(property_record)

    return PropertyResponse.model_validate(property_record)


@router.patch(
    "/{property_id}/commercial",
    response_model=PropertyCommercialResponse,
    status_code=status.HTTP_200_OK,
)
def update_property_commercial_endpoint(
    property_id: UUID,
    payload: PropertyCommercialUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("properties.update"),
    ),
    db: Session = Depends(get_db_session),
) -> PropertyCommercialResponse:
    """Update commercial fields for a Property within the verified tenant."""

    property_record = update_property_commercial(
        db=db,
        organization_id=tenant_context.organization_id,
        property_id=property_id,
        transaction_type=payload.transaction_type,
        price=payload.price,
        currency=payload.currency,
        rent=payload.rent,
        security_deposit=payload.security_deposit,
        maintenance_charge=payload.maintenance_charge,
    )

    if property_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found.",
        )

    db.commit()
    db.refresh(property_record)

    return PropertyCommercialResponse.model_validate(property_record)
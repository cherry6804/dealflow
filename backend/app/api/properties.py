"""FastAPI routes for DealFlow Property operations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.properties.schemas import PropertyCreateRequest, PropertyResponse
from app.properties.service import create_property
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
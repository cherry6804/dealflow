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
    PropertyLocationAttributesResponse,
    PropertyLocationAttributesUpdateRequest,
    PropertyResponse,
    PropertySearchQuery,
    PropertySearchResponse,
    PropertySearchResult,
    PropertyStatusResponse,
    PropertyStatusUpdateRequest,
)
from app.properties.service import (
    create_property,
    search_properties,
    update_property_commercial,
    update_property_location_attributes,
    update_property_status,
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


@router.patch(
    "/{property_id}/location-attributes",
    response_model=PropertyLocationAttributesResponse,
    status_code=status.HTTP_200_OK,
)
def update_property_location_attributes_endpoint(
    property_id: UUID,
    payload: PropertyLocationAttributesUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("properties.update"),
    ),
    db: Session = Depends(get_db_session),
) -> PropertyLocationAttributesResponse:
    """Update location and core attributes for a Property within the verified tenant."""

    try:
        property_record = update_property_location_attributes(
            db=db,
            organization_id=tenant_context.organization_id,
            property_id=property_id,
            fields_to_update=payload.model_fields_set,
            address_line_1=payload.address_line_1,
            address_line_2=payload.address_line_2,
            locality=payload.locality,
            city=payload.city,
            state=payload.state,
            postal_code=payload.postal_code,
            property_type=payload.property_type,
            bhk=payload.bhk,
            built_up_area=payload.built_up_area,
            carpet_area=payload.carpet_area,
            floor_number=payload.floor_number,
            total_floors=payload.total_floors,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if property_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found.",
        )

    db.commit()
    db.refresh(property_record)

    return PropertyLocationAttributesResponse.model_validate(property_record)


@router.patch(
    "/{property_id}/status",
    response_model=PropertyStatusResponse,
    status_code=status.HTTP_200_OK,
)
def update_property_status_endpoint(
    property_id: UUID,
    payload: PropertyStatusUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("properties.update"),
    ),
    db: Session = Depends(get_db_session),
) -> PropertyStatusResponse:
    """Update availability status for a Property within the verified tenant."""

    property_record = update_property_status(
        db=db,
        organization_id=tenant_context.organization_id,
        property_id=property_id,
        status=payload.status,
    )

    if property_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Property not found.",
        )

    db.commit()
    db.refresh(property_record)

    return PropertyStatusResponse.model_validate(property_record)


@router.get(
    "/search",
    response_model=PropertySearchResponse,
    status_code=status.HTTP_200_OK,
)
def search_properties_endpoint(
    filters: PropertySearchQuery = Depends(),
    tenant_context: TenantContext = Depends(
        require_permission("properties.read"),
    ),
    db: Session = Depends(get_db_session),
) -> PropertySearchResponse:
    """Search and filter Properties within the verified tenant."""

    try:
        properties, total, total_pages = search_properties(
            db=db,
            organization_id=tenant_context.organization_id,
            filters=filters,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "type": "value_error",
                    "loc": ["query"],
                    "msg": f"Value error, {exc}",
                    "input": None,
                }
            ],
        ) from exc

    return PropertySearchResponse(
        items=[
            PropertySearchResult.model_validate(property_record)
            for property_record in properties
        ],
        page=filters.page,
        page_size=filters.page_size,
        total=total,
        total_pages=total_pages,
    )
"""Customer requirement API endpoints for DealFlow."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.requirements.schemas import (
    CustomerRequirementCreateRequest,
    CustomerRequirementLocationCreateRequest,
    CustomerRequirementLocationResponse,
    CustomerRequirementLocationUpdateRequest,
    CustomerRequirementPropertyPreferenceCreateRequest,
    CustomerRequirementPropertyPreferenceResponse,
    CustomerRequirementPropertyPreferenceUpdateRequest,
    CustomerRequirementResponse,
    CustomerRequirementUpdateRequest,
)
from app.requirements.service import (
    create_customer_requirement,
    create_customer_requirement_location,
    create_customer_requirement_property_preference,
    get_customer_requirement,
    get_customer_requirement_location,
    get_customer_requirement_property_preference,
    list_customer_requirement_locations,
    list_customer_requirement_property_preferences,
    update_customer_requirement_budget,
    update_customer_requirement_location,
    update_customer_requirement_property_preference,
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


@router.post(
    "/{requirement_id}/locations",
    response_model=CustomerRequirementLocationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_requirement_location(
    requirement_id: UUID,
    payload: CustomerRequirementLocationCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementLocationResponse:
    """Create a location for a tenant-owned customer requirement."""

    try:
        location = create_customer_requirement_location(
            db=db,
            organization_id=tenant_context.organization_id,
            customer_requirement_id=requirement_id,
            city=payload.city,
            locality=payload.locality,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(location)

    return CustomerRequirementLocationResponse.model_validate(location)


@router.get(
    "/{requirement_id}/locations",
    response_model=list[CustomerRequirementLocationResponse],
    status_code=status.HTTP_200_OK,
)
def list_requirement_locations(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> list[CustomerRequirementLocationResponse]:
    """List locations for a tenant-owned customer requirement."""

    try:
        locations = list_customer_requirement_locations(
            db=db,
            organization_id=tenant_context.organization_id,
            customer_requirement_id=requirement_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return [
        CustomerRequirementLocationResponse.model_validate(location)
        for location in locations
    ]


@router.patch(
    "/{requirement_id}/locations/{location_id}",
    response_model=CustomerRequirementLocationResponse,
    status_code=status.HTTP_200_OK,
)
def update_requirement_location(
    requirement_id: UUID,
    location_id: UUID,
    payload: CustomerRequirementLocationUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementLocationResponse:
    """Update a location within its tenant-owned requirement."""

    location = get_customer_requirement_location(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_requirement_id=requirement_id,
        location_id=location_id,
    )

    if location is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer requirement location not found.",
        )

    fields_set = payload.model_fields_set

    location = update_customer_requirement_location(
        db=db,
        location=location,
        city=payload.city,
        locality=payload.locality,
        is_active=payload.is_active,
        update_city="city" in fields_set,
        update_locality="locality" in fields_set,
        update_is_active="is_active" in fields_set,
    )

    db.commit()
    db.refresh(location)

    return CustomerRequirementLocationResponse.model_validate(location)


@router.post(
    "/{requirement_id}/property-preferences",
    response_model=CustomerRequirementPropertyPreferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_requirement_property_preference(
    requirement_id: UUID,
    payload: CustomerRequirementPropertyPreferenceCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementPropertyPreferenceResponse:
    """Create a property type and BHK preference for a requirement."""

    try:
        preference = create_customer_requirement_property_preference(
            db=db,
            organization_id=tenant_context.organization_id,
            customer_requirement_id=requirement_id,
            property_type=payload.property_type,
            bhk_min=payload.bhk_min,
            bhk_max=payload.bhk_max,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(preference)

    return CustomerRequirementPropertyPreferenceResponse.model_validate(
        preference
    )


@router.get(
    "/{requirement_id}/property-preferences",
    response_model=list[CustomerRequirementPropertyPreferenceResponse],
    status_code=status.HTTP_200_OK,
)
def list_requirement_property_preferences(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> list[CustomerRequirementPropertyPreferenceResponse]:
    """List property preferences for a requirement."""

    try:
        preferences = list_customer_requirement_property_preferences(
            db=db,
            organization_id=tenant_context.organization_id,
            customer_requirement_id=requirement_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return [
        CustomerRequirementPropertyPreferenceResponse.model_validate(
            preference
        )
        for preference in preferences
    ]


@router.patch(
    "/{requirement_id}/property-preferences/{preference_id}",
    response_model=CustomerRequirementPropertyPreferenceResponse,
    status_code=status.HTTP_200_OK,
)
def update_requirement_property_preference(
    requirement_id: UUID,
    preference_id: UUID,
    payload: CustomerRequirementPropertyPreferenceUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementPropertyPreferenceResponse:
    """Update a property preference within its requirement."""

    preference = get_customer_requirement_property_preference(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_requirement_id=requirement_id,
        preference_id=preference_id,
    )

    if preference is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer requirement property preference not found.",
        )

    fields_set = payload.model_fields_set

    try:
        preference = update_customer_requirement_property_preference(
            db=db,
            preference=preference,
            property_type=payload.property_type,
            bhk_min=payload.bhk_min,
            bhk_max=payload.bhk_max,
            is_active=payload.is_active,
            update_property_type="property_type" in fields_set,
            update_bhk_min="bhk_min" in fields_set,
            update_bhk_max="bhk_max" in fields_set,
            update_is_active="is_active" in fields_set,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(preference)

    return CustomerRequirementPropertyPreferenceResponse.model_validate(
        preference
    )
"""Customer requirement API endpoints for DealFlow."""

from __future__ import annotations
from app.properties.schemas import PropertyResponse
from uuid import UUID
from app.properties.matching_service import get_matching_properties
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.properties.schemas import (
    PropertyMatchResultsResponse,
    PropertyResponse,
)
from app.properties.matching_service import (
    get_matching_properties,
    get_property_match_results,
)
from app.requirements.match_history_service import (
    create_requirement_match_run,
    list_requirement_match_runs,
    list_requirement_match_run_results,
)
from app.requirements.shortlist_service import (
    list_requirement_shortlist_events,
)
from app.requirements.schemas import (
    RequirementMatchRunDetailResponse,
    RequirementMatchRunListResponse,
    RequirementMatchRunResultResponse,
    RequirementMatchRunSummaryResponse,
    RequirementShortlistEventListResponse,
    RequirementShortlistEventResponse,
)
from app.requirements.schemas import (
    CustomerRequirementAssociationRequest,
    CustomerRequirementAssociationResponse,
    CustomerRequirementHistoryListResponse,
    CustomerRequirementHistoryResponse,
    CustomerRequirementCreateRequest,
    CustomerRequirementLocationCreateRequest,
    CustomerRequirementLocationResponse,
    CustomerRequirementLocationUpdateRequest,
    CustomerRequirementPossessionParkingPreferenceCreateRequest,
    CustomerRequirementPossessionParkingPreferenceResponse,
    CustomerRequirementPossessionParkingPreferenceUpdateRequest,
    CustomerRequirementPropertyPreferenceCreateRequest,
    CustomerRequirementPropertyPreferenceResponse,
    CustomerRequirementPropertyPreferenceUpdateRequest,
    CustomerRequirementResponse,
    CustomerRequirementUpdateRequest,
    CustomerRequirementListResponse,
    RequirementPropertyShortlistCreateRequest,
    RequirementPropertyShortlistItemResponse,
    RequirementPropertyShortlistListResponse,
)
from app.requirements.history_service import (
    get_customer_requirement_history_version,
    list_customer_requirement_history,
)
from app.properties.schemas import PropertySearchResult
from app.requirements.service import (
    create_customer_requirement,
    get_customer_requirement_association,
    create_customer_requirement_location,
    create_customer_requirement_possession_parking_preference,
    create_customer_requirement_property_preference,
    get_customer_requirement,
    get_customer_requirement_location,
    get_customer_requirement_possession_parking_preference,
    get_customer_requirement_property_preference,
    list_customer_requirement_locations,
    list_customer_requirement_property_preferences,
    update_customer_requirement_association,
    update_customer_requirement_budget,
    update_customer_requirement_location,
    update_customer_requirement_possession_parking_preference,
    update_customer_requirement_property_preference,
    list_customer_requirements,
)
from app.requirements.shortlist_service import (
    create_requirement_property_shortlist,
    list_requirement_property_shortlists,
    remove_requirement_property_shortlist,
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
            actor_id=tenant_context.membership.user_id,
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
            organization_id=tenant_context.organization_id,
            actor_id=tenant_context.membership.user_id,
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
        organization_id=tenant_context.organization_id,
        actor_id=tenant_context.membership.user_id,
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
            organization_id=tenant_context.organization_id,
            actor_id=tenant_context.membership.user_id,
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


@router.post(
    "/{requirement_id}/possession-parking-preference",
    response_model=CustomerRequirementPossessionParkingPreferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_requirement_possession_parking_preference(
    requirement_id: UUID,
    payload: CustomerRequirementPossessionParkingPreferenceCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementPossessionParkingPreferenceResponse:
    """Create possession and parking preferences for a requirement."""

    try:
        preference = create_customer_requirement_possession_parking_preference(
            db=db,
            organization_id=tenant_context.organization_id,
            customer_requirement_id=requirement_id,
            possession_preference=payload.possession_preference,
            parking_preference=payload.parking_preference,
            parking_spaces_min=payload.parking_spaces_min,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(preference)

    return CustomerRequirementPossessionParkingPreferenceResponse.model_validate(
        preference
    )


@router.get(
    "/{requirement_id}/possession-parking-preference",
    response_model=CustomerRequirementPossessionParkingPreferenceResponse,
    status_code=status.HTTP_200_OK,
)
def get_requirement_possession_parking_preference(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementPossessionParkingPreferenceResponse:
    """Retrieve possession and parking preferences for a requirement."""

    preference = get_customer_requirement_possession_parking_preference(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_requirement_id=requirement_id,
    )

    if preference is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Customer requirement possession and parking preference "
                "not found."
            ),
        )

    return CustomerRequirementPossessionParkingPreferenceResponse.model_validate(
        preference
    )


@router.patch(
    "/{requirement_id}/possession-parking-preference",
    response_model=CustomerRequirementPossessionParkingPreferenceResponse,
    status_code=status.HTTP_200_OK,
)
def update_requirement_possession_parking_preference(
    requirement_id: UUID,
    payload: CustomerRequirementPossessionParkingPreferenceUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementPossessionParkingPreferenceResponse:
    """Update possession and parking preferences for a requirement."""

    preference = get_customer_requirement_possession_parking_preference(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_requirement_id=requirement_id,
    )

    if preference is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Customer requirement possession and parking preference "
                "not found."
            ),
        )

    fields_set = payload.model_fields_set

    try:
        preference = update_customer_requirement_possession_parking_preference(
            db=db,
            preference=preference,
            organization_id=tenant_context.organization_id,
            actor_id=tenant_context.membership.user_id,
            possession_preference=payload.possession_preference,
            parking_preference=payload.parking_preference,
            parking_spaces_min=payload.parking_spaces_min,
            is_active=payload.is_active,
            update_possession_preference=(
                "possession_preference" in fields_set
            ),
            update_parking_preference=(
                "parking_preference" in fields_set
            ),
            update_parking_spaces_min=(
                "parking_spaces_min" in fields_set
            ),
            update_is_active="is_active" in fields_set,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(preference)

    return CustomerRequirementPossessionParkingPreferenceResponse.model_validate(
        preference
    )


@router.post(
    "/{requirement_id}/association",
    response_model=CustomerRequirementAssociationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_requirement_association(
    requirement_id: UUID,
    payload: CustomerRequirementAssociationRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementAssociationResponse:
    """Create associations for a tenant-owned customer requirement."""

    requirement = get_customer_requirement_association(
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

    if not fields_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one association field must be provided.",
        )

    try:
        requirement = update_customer_requirement_association(
            db=db,
            requirement=requirement,
            organization_id=tenant_context.organization_id,
            actor_id=tenant_context.membership.user_id,
            lead_id=payload.lead_id,
            customer_profile_id=payload.customer_profile_id,
            update_lead_id="lead_id" in fields_set,
            update_customer_profile_id="customer_profile_id" in fields_set,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(requirement)

    return CustomerRequirementAssociationResponse(
        customer_requirement_id=requirement.id,
        organization_id=requirement.organization_id,
        lead_id=requirement.lead_id,
        customer_profile_id=requirement.customer_profile_id,
        updated_at=requirement.updated_at,
    )


@router.get(
    "/{requirement_id}/association",
    response_model=CustomerRequirementAssociationResponse,
    status_code=status.HTTP_200_OK,
)
def get_requirement_association(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementAssociationResponse:
    """Retrieve associations for a tenant-owned customer requirement."""

    requirement = get_customer_requirement_association(
        db=db,
        organization_id=tenant_context.organization_id,
        requirement_id=requirement_id,
    )

    if requirement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer requirement not found.",
        )

    return CustomerRequirementAssociationResponse(
        customer_requirement_id=requirement.id,
        organization_id=requirement.organization_id,
        lead_id=requirement.lead_id,
        customer_profile_id=requirement.customer_profile_id,
        updated_at=requirement.updated_at,
    )


@router.patch(
    "/{requirement_id}/association",
    response_model=CustomerRequirementAssociationResponse,
    status_code=status.HTTP_200_OK,
)
def update_requirement_association(
    requirement_id: UUID,
    payload: CustomerRequirementAssociationRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementAssociationResponse:
    """Update associations for a tenant-owned customer requirement."""

    requirement = get_customer_requirement_association(
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

    if not fields_set:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one association field must be provided.",
        )

    try:
        requirement = update_customer_requirement_association(
            db=db,
            requirement=requirement,
            organization_id=tenant_context.organization_id,
            actor_id=tenant_context.membership.user_id,
            lead_id=payload.lead_id,
            customer_profile_id=payload.customer_profile_id,
            update_lead_id="lead_id" in fields_set,
            update_customer_profile_id="customer_profile_id" in fields_set,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(requirement)

    return CustomerRequirementAssociationResponse(
        customer_requirement_id=requirement.id,
        organization_id=requirement.organization_id,
        lead_id=requirement.lead_id,
        customer_profile_id=requirement.customer_profile_id,
        updated_at=requirement.updated_at,
    )

@router.get(
    "/{requirement_id}/history",
    response_model=CustomerRequirementHistoryListResponse,
    status_code=status.HTTP_200_OK,
)
def list_requirement_history(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementHistoryListResponse:
    """List immutable history for a tenant-owned customer requirement."""

    try:
        history = list_customer_requirement_history(
            db=db,
            requirement_id=requirement_id,
            organization_id=tenant_context.organization_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return CustomerRequirementHistoryListResponse(
        items=[
            CustomerRequirementHistoryResponse.model_validate(item)
            for item in history
        ]
    )


@router.get(
    "/{requirement_id}/history/{version}",
    response_model=CustomerRequirementHistoryResponse,
    status_code=status.HTTP_200_OK,
)
def get_requirement_history_version(
    requirement_id: UUID,
    version: int,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementHistoryResponse:
    """Retrieve one immutable history version for a tenant-owned requirement."""

    if version <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="History version must be greater than zero.",
        )

    try:
        history = get_customer_requirement_history_version(
            db=db,
            requirement_id=requirement_id,
            organization_id=tenant_context.organization_id,
            version=version,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer requirement history version not found.",
        )

    return CustomerRequirementHistoryResponse.model_validate(history)

@router.get(
    "",
    response_model=CustomerRequirementListResponse,
    status_code=status.HTTP_200_OK,
)
def list_requirements(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(ACTIVE|INACTIVE)$",
    ),
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerRequirementListResponse:
    """List requirements belonging to the verified tenant."""

    items, total, total_pages = list_customer_requirements(
        db=db,
        organization_id=tenant_context.organization_id,
        page=page,
        page_size=page_size,
        status=status_filter,
    )

    return CustomerRequirementListResponse(
        items=[_requirement_response(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )

@router.get(
    "/{requirement_id}/matches",
    response_model=list[PropertyResponse],
    status_code=status.HTTP_200_OK,
)
def match_requirement_properties(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
):
    """Find available properties matching a customer requirement."""
    try:
        properties = get_matching_properties(
            db=db,
            organization_id=tenant_context.organization_id,
            requirement_id=requirement_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return [
        PropertyResponse.model_validate(property_record)
        for property_record in properties
    ]

@router.get(
    "/{requirement_id}/match-results",
    response_model=PropertyMatchResultsResponse,
    status_code=status.HTTP_200_OK,
)
def get_requirement_match_results(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> PropertyMatchResultsResponse:
    """Return available property candidates with matching explanations."""
    try:
        results = get_property_match_results(
            db=db,
            organization_id=tenant_context.organization_id,
            requirement_id=requirement_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return PropertyMatchResultsResponse(
        requirement_id=requirement_id,
        items=results,
        total=len(results),
    )


@router.post(
    "/{requirement_id}/shortlist",
    response_model=RequirementPropertyShortlistItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_requirement_property_shortlist(
    requirement_id: UUID,
    payload: RequirementPropertyShortlistCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> RequirementPropertyShortlistItemResponse:
    """Manually shortlist a property for a tenant-owned requirement."""

    try:
        shortlist, property_record = create_requirement_property_shortlist(
            db=db,
            organization_id=tenant_context.organization_id,
            requirement_id=requirement_id,
            property_id=payload.property_id,
            actor_id=tenant_context.membership.user_id,
        )
    except ValueError as exc:
        message = str(exc)
        error_status = (
            status.HTTP_409_CONFLICT
            if "already shortlisted" in message.lower()
            else status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(
            status_code=error_status,
            detail=message,
        ) from exc

    db.commit()
    db.refresh(shortlist)

    return RequirementPropertyShortlistItemResponse(
        property=PropertySearchResult.model_validate(property_record),
        created_at=shortlist.created_at,
        created_by_user_id=shortlist.created_by_user_id,
    )


@router.get(
    "/{requirement_id}/shortlist",
    response_model=RequirementPropertyShortlistListResponse,
    status_code=status.HTTP_200_OK,
)
def list_requirement_property_shortlist(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> RequirementPropertyShortlistListResponse:
    """List shortlisted properties for a tenant-owned requirement."""

    try:
        rows = list_requirement_property_shortlists(
            db=db,
            organization_id=tenant_context.organization_id,
            requirement_id=requirement_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    items = [
        RequirementPropertyShortlistItemResponse(
            property=PropertySearchResult.model_validate(property_record),
            created_at=shortlist.created_at,
            created_by_user_id=shortlist.created_by_user_id,
        )
        for shortlist, property_record in rows
    ]

    return RequirementPropertyShortlistListResponse(
        requirement_id=requirement_id,
        items=items,
        total=len(items),
    )


@router.delete(
    "/{requirement_id}/shortlist/{property_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_requirement_property_shortlist(
    requirement_id: UUID,
    property_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.update"),
    ),
    db: Session = Depends(get_db_session),
) -> None:
    """Remove a property from a requirement's manual shortlist."""

    try:
        remove_requirement_property_shortlist(
            db=db,
            organization_id=tenant_context.organization_id,
            requirement_id=requirement_id,
            property_id=property_id,
            actor_id=tenant_context.membership.user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    db.commit()
    return None

# ---------------------------------------------------------------------------
# DF-109: Immutable matching history
# ---------------------------------------------------------------------------

@router.post(
    "/{requirement_id}/match-runs",
    response_model=RequirementMatchRunDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_requirement_match_run(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> RequirementMatchRunDetailResponse:
    """Execute matching and atomically persist the complete run history."""


    try:
        run, results = create_requirement_match_run(
            db=db,
            organization_id=tenant_context.organization_id,
            requirement_id=requirement_id,
            actor_id=tenant_context.membership.user_id,
        )

        response = RequirementMatchRunDetailResponse(
            **RequirementMatchRunSummaryResponse.model_validate(
                run
            ).model_dump(),
            results=[
                RequirementMatchRunResultResponse.model_validate(result)
                for result in results
            ],
        )

        db.commit()
        return response

    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.get(
    "/{requirement_id}/match-runs",
    response_model=RequirementMatchRunListResponse,
    status_code=status.HTTP_200_OK,
)
def get_requirement_match_runs(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> RequirementMatchRunListResponse:
    """List saved matching runs, including runs for deleted requirements."""

    runs = list_requirement_match_runs(
        db=db,
        organization_id=tenant_context.organization_id,
        requirement_id=requirement_id,
    )

    return RequirementMatchRunListResponse(
        items=[
            RequirementMatchRunSummaryResponse.model_validate(run)
            for run in runs
        ],
        total=len(runs),
    )


@router.get(
    "/{requirement_id}/match-runs/{run_id}/results",
    response_model=list[RequirementMatchRunResultResponse],
    status_code=status.HTTP_200_OK,
)
def get_requirement_match_run_results(
    requirement_id: UUID,
    run_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> list[RequirementMatchRunResultResponse]:
    """Retrieve immutable results for a tenant-owned historical run."""

    try:
        results = list_requirement_match_run_results(
            db=db,
            organization_id=tenant_context.organization_id,
            requirement_id=requirement_id,
            run_id=run_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return [
        RequirementMatchRunResultResponse.model_validate(result)
        for result in results
    ]


@router.get(
    "/{requirement_id}/shortlist-events",
    response_model=RequirementShortlistEventListResponse,
    status_code=status.HTTP_200_OK,
)
def get_requirement_shortlist_events(
    requirement_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("requirements.read"),
    ),
    db: Session = Depends(get_db_session),
) -> RequirementShortlistEventListResponse:
    """Retrieve historical shortlist additions and removals."""

    events = list_requirement_shortlist_events(
        db=db,
        organization_id=tenant_context.organization_id,
        requirement_id=requirement_id,
    )

    return RequirementShortlistEventListResponse(
        requirement_id=requirement_id,
        items=[
            RequirementShortlistEventResponse.model_validate(event)
            for event in events
        ],
        total=len(events),
    )

def _requirement_response(
    requirement,
) -> CustomerRequirementResponse:
    """Build a requirement response with its assigned customer summary."""
    profile = requirement.customer_profile
    lead = requirement.lead

    # Prefer the registered customer profile; fall back to the lead.
    contact = (
        profile.contact
        if profile is not None
        else lead.contact if lead is not None else None
    )

    customer_name = None
    customer_email = None
    customer_phone = None

    if contact is not None:
        customer_name = (
            " ".join(
                part
                for part in (contact.first_name, contact.last_name)
                if part
            )
            or contact.email
            or contact.phone
        )
        customer_email = contact.email
        customer_phone = contact.phone

    response = CustomerRequirementResponse.model_validate(requirement)
    response.customer_name = customer_name
    response.customer_email = customer_email
    response.customer_phone = customer_phone
    return response

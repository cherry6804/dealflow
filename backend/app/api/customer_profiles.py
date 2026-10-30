"""Customer Profile API routes for DealFlow."""

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.customer_profiles.schemas import (
    CustomerProfileCreateRequest,
    CustomerProfileListResponse,
    CustomerProfileReplaceRequest,
    CustomerProfileResponse,
    CustomerProfileUpdateRequest,
)
from app.customer_profiles.service import (
    create_customer_profile,
    deactivate_customer_profile,
    get_customer_profile,
    list_customer_profiles,
    replace_customer_profile,
    update_customer_profile,
)
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext


router = APIRouter(
    prefix="/api/v1/customer-profiles",
    tags=["customer-profiles"],
)


@router.post(
    "",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_profile_endpoint(
    payload: CustomerProfileCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("contacts.create"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerProfileResponse:
    """Explicitly register an existing Contact as a Customer."""
    try:
        profile = create_customer_profile(
            db=db,
            organization_id=tenant_context.organization_id,
            payload=payload,
        )

        if profile is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contact not found.",
            )

        db.commit()

    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Contact is already registered as a Customer.",
        ) from exc

    profile = get_customer_profile(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_profile_id=profile.id,
    )

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Customer Profile could not be retrieved after creation.",
        )

    return CustomerProfileResponse.model_validate(profile)


@router.get(
    "",
    response_model=CustomerProfileListResponse,
    status_code=status.HTTP_200_OK,
)
def list_customer_profiles_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1, max_length=320),
    is_active: bool | None = Query(default=True),
    tenant_context: TenantContext = Depends(
        require_permission("contacts.read"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerProfileListResponse:
    """List and search Customer Profiles within the verified tenant."""
    profiles, total = list_customer_profiles(
        db=db,
        organization_id=tenant_context.organization_id,
        page=page,
        page_size=page_size,
        search=search,
        is_active=is_active,
    )

    total_pages = ceil(total / page_size) if total else 0

    return CustomerProfileListResponse(
        items=[
            CustomerProfileResponse.model_validate(profile)
            for profile in profiles
        ],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


@router.get(
    "/{customer_profile_id}",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_200_OK,
)
def get_customer_profile_endpoint(
    customer_profile_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("contacts.read"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerProfileResponse:
    """Retrieve a Customer Profile within the verified tenant."""
    profile = get_customer_profile(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_profile_id=customer_profile_id,
    )

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer Profile not found.",
        )

    return CustomerProfileResponse.model_validate(profile)


@router.put(
    "/{customer_profile_id}",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_200_OK,
)
def replace_customer_profile_endpoint(
    customer_profile_id: UUID,
    payload: CustomerProfileReplaceRequest,
    tenant_context: TenantContext = Depends(
        require_permission("contacts.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerProfileResponse:
    """Replace the editable fields of a Customer Profile."""
    profile = replace_customer_profile(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_profile_id=customer_profile_id,
        payload=payload,
    )

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer Profile not found.",
        )

    db.commit()

    profile = get_customer_profile(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_profile_id=customer_profile_id,
    )

    return CustomerProfileResponse.model_validate(profile)


@router.patch(
    "/{customer_profile_id}",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_200_OK,
)
def update_customer_profile_endpoint(
    customer_profile_id: UUID,
    payload: CustomerProfileUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("contacts.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerProfileResponse:
    """Partially update a Customer Profile."""
    if not payload.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one field must be provided for an update.",
        )

    profile = update_customer_profile(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_profile_id=customer_profile_id,
        payload=payload,
    )

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer Profile not found.",
        )

    db.commit()

    profile = get_customer_profile(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_profile_id=customer_profile_id,
    )

    return CustomerProfileResponse.model_validate(profile)


@router.delete(
    "/{customer_profile_id}",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_200_OK,
)
def deactivate_customer_profile_endpoint(
    customer_profile_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("contacts.update"),
    ),
    db: Session = Depends(get_db_session),
) -> CustomerProfileResponse:
    """Deactivate a Customer Profile without physically deleting it."""
    profile = deactivate_customer_profile(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_profile_id=customer_profile_id,
    )

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer Profile not found.",
        )

    db.commit()

    profile = get_customer_profile(
        db=db,
        organization_id=tenant_context.organization_id,
        customer_profile_id=customer_profile_id,
    )

    return CustomerProfileResponse.model_validate(profile)

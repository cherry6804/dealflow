
"""FastAPI routes for referral management."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.referrals.schemas import (
    ReferralCreateRequest,
    ReferralListResponse,
    ReferralResponse,
    ReferralStatus,
    ReferralUpdateRequest,
)
from app.referrals.service import (
    create_referral,
    deactivate_referral,
    get_referral,
    list_referrals,
    update_referral,
)
from app.tenant.dependencies import TenantContext


router = APIRouter(tags=["referrals"])


def _commit_and_refresh(
    db: Session,
    referral,
) -> ReferralResponse:
    """Commit a referral change and return the refreshed record."""
    db.commit()
    db.refresh(referral)
    return ReferralResponse.model_validate(referral)


@router.post(
    "/api/v1/referrals",
    response_model=ReferralResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_referral_endpoint(
    payload: ReferralCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("referrals.create")
    ),
    db: Session = Depends(get_db_session),
) -> ReferralResponse:
    """Create a referral in the active organization."""
    try:
        referral = create_referral(
            db,
            organization_id=tenant_context.organization_id,
            current_user_id=tenant_context.membership.user_id,
            payload=payload,
        )
        return _commit_and_refresh(db, referral)

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
            detail="The referral could not be saved.",
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.get(
    "/api/v1/referrals",
    response_model=ReferralListResponse,
)
def list_referrals_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200),
    referral_status: ReferralStatus | None = Query(
        default=None,
        alias="status",
    ),
    tenant_context: TenantContext = Depends(
        require_permission("referrals.read")
    ),
    db: Session = Depends(get_db_session),
) -> ReferralListResponse:
    """List active referrals in the current organization."""
    items, total = list_referrals(
        db,
        organization_id=tenant_context.organization_id,
        page=page,
        page_size=page_size,
        search=search,
        status=referral_status,
    )

    return ReferralListResponse(
        items=[
            ReferralResponse.model_validate(referral)
            for referral in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/api/v1/referrals/{referral_id}",
    response_model=ReferralResponse,
)
def get_referral_endpoint(
    referral_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("referrals.read")
    ),
    db: Session = Depends(get_db_session),
) -> ReferralResponse:
    """Retrieve a referral from the active organization."""
    referral = get_referral(
        db,
        organization_id=tenant_context.organization_id,
        referral_id=referral_id,
    )

    if referral is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referral not found.",
        )

    return ReferralResponse.model_validate(referral)


@router.patch(
    "/api/v1/referrals/{referral_id}",
    response_model=ReferralResponse,
)
def update_referral_endpoint(
    referral_id: UUID,
    payload: ReferralUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("referrals.update")
    ),
    db: Session = Depends(get_db_session),
) -> ReferralResponse:
    """Update a referral in the active organization."""
    try:
        referral = update_referral(
            db,
            organization_id=tenant_context.organization_id,
            referral_id=referral_id,
            current_user_id=tenant_context.membership.user_id,
            payload=payload,
        )

        if referral is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Referral not found.",
            )

        return _commit_and_refresh(db, referral)

    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except HTTPException:
        raise

    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The referral could not be updated.",
        ) from exc

    except Exception:
        db.rollback()
        raise


@router.delete(
    "/api/v1/referrals/{referral_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def deactivate_referral_endpoint(
    referral_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("referrals.update")
    ),
    db: Session = Depends(get_db_session),
) -> Response:
    """Soft-delete a referral without physically removing its record."""
    try:
        referral = deactivate_referral(
            db,
            organization_id=tenant_context.organization_id,
            referral_id=referral_id,
            current_user_id=tenant_context.membership.user_id,
        )

        if referral is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Referral not found.",
            )

        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except HTTPException:
        raise

    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The referral could not be deactivated.",
        ) from exc

    except Exception:
        db.rollback()
        raise

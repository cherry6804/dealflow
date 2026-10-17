
"""FastAPI routes for deal commission management."""

from __future__ import annotations

from uuid import UUID
from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.models.deal import Deal
from app.db.session import get_db_session
from app.deal_commissions.schemas import (
    DealCommissionCreateRequest,
    DealCommissionListResponse,
    DealCommissionPaymentRequest,
    DealCommissionResponse,
    DealCommissionUpdateRequest,
)
from app.deal_commissions.service import (
    agree_deal_commission,
    calculate_commission_amount,
    cancel_deal_commission,
    create_deal_commission,
    get_deal_commission,
    list_deal_commissions,
    mark_deal_commission_paid,
    update_deal_commission,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(tags=["deal-commissions"])


def _response(db: Session, commission) -> DealCommissionResponse:
    """Build a response with the current deal-based commission calculation."""
    deal = db.scalar(
        select(Deal).where(
            Deal.id == commission.deal_id,
            Deal.organization_id == commission.organization_id,
        )
    )
    result = DealCommissionResponse.model_validate(commission)
    result.calculated_amount = calculate_commission_amount(
        commission,
        deal.expected_value if deal is not None else None,
    )
    return result


def _commit_and_refresh(db: Session, commission) -> DealCommissionResponse:
    db.commit()
    db.refresh(commission)
    return _response(db, commission)


@router.post(
    "/api/v1/deals/{deal_id}/commissions",
    response_model=DealCommissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_deal_commission_endpoint(
    deal_id: UUID,
    payload: DealCommissionCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("commission.create")
    ),
    db: Session = Depends(get_db_session),
) -> DealCommissionResponse:
    """Create proposed commission terms for a deal."""
    try:
        commission = create_deal_commission(
            db,
            organization_id=tenant_context.organization_id,
            deal_id=deal_id,
            current_user_id=tenant_context.membership.user_id,
            payload=payload,
        )
        if commission is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deal not found.",
            )
        return _commit_and_refresh(db, commission)
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The commission could not be saved.",
        ) from exc
    except Exception:
        db.rollback()
        raise


@router.get(
    "/api/v1/deals/{deal_id}/commissions",
    response_model=DealCommissionListResponse,
)
def list_deal_commissions_endpoint(
    deal_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("commission.read")
    ),
    db: Session = Depends(get_db_session),
) -> DealCommissionListResponse:
    """List commissions for a deal in the active organization."""
    result = list_deal_commissions(
        db,
        organization_id=tenant_context.organization_id,
        deal_id=deal_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deal not found.",
        )

    items, total = result
    return DealCommissionListResponse(
        items=[_response(db, item) for item in items],
        total=total,
    )


@router.get(
    "/api/v1/commissions/{commission_id}",
    response_model=DealCommissionResponse,
)
def get_deal_commission_endpoint(
    commission_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("commission.read")
    ),
    db: Session = Depends(get_db_session),
) -> DealCommissionResponse:
    """Retrieve a commission from the active organization."""
    commission = get_deal_commission(
        db,
        organization_id=tenant_context.organization_id,
        commission_id=commission_id,
    )
    if commission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commission not found.",
        )
    return _response(db, commission)


@router.patch(
    "/api/v1/commissions/{commission_id}",
    response_model=DealCommissionResponse,
)
def update_deal_commission_endpoint(
    commission_id: UUID,
    payload: DealCommissionUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("commission.update")
    ),
    db: Session = Depends(get_db_session),
) -> DealCommissionResponse:
    """Update proposed or agreed commission terms."""
    try:
        commission = update_deal_commission(
            db,
            organization_id=tenant_context.organization_id,
            commission_id=commission_id,
            current_user_id=tenant_context.membership.user_id,
            payload=payload,
        )
        if commission is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Commission not found.",
            )
        return _commit_and_refresh(db, commission)
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
            detail="The commission could not be updated.",
        ) from exc
    except Exception:
        db.rollback()
        raise


@router.post(
    "/api/v1/commissions/{commission_id}/agree",
    response_model=DealCommissionResponse,
)
def agree_deal_commission_endpoint(
    commission_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("commission.update")
    ),
    db: Session = Depends(get_db_session),
) -> DealCommissionResponse:
    """Record agreement to proposed commission terms."""
    try:
        commission = agree_deal_commission(
            db,
            organization_id=tenant_context.organization_id,
            commission_id=commission_id,
            current_user_id=tenant_context.membership.user_id,
        )
        if commission is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Commission not found.",
            )
        return _commit_and_refresh(db, commission)
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
            detail="The commission could not be agreed.",
        ) from exc
    except Exception:
        db.rollback()
        raise


@router.post(
    "/api/v1/commissions/{commission_id}/mark-paid",
    response_model=DealCommissionResponse,
)
def mark_deal_commission_paid_endpoint(
    commission_id: UUID,
    payload: DealCommissionPaymentRequest,
    tenant_context: TenantContext = Depends(
        require_permission("commission.update")
    ),
    db: Session = Depends(get_db_session),
) -> DealCommissionResponse:
    """Record payment for an agreed commission."""
    try:
        commission = mark_deal_commission_paid(
            db,
            organization_id=tenant_context.organization_id,
            commission_id=commission_id,
            current_user_id=tenant_context.membership.user_id,
            payment_reference=payload.payment_reference,
        )
        if commission is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Commission not found.",
            )
        return _commit_and_refresh(db, commission)
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
            detail="The commission payment could not be recorded.",
        ) from exc
    except Exception:
        db.rollback()
        raise


@router.post(
    "/api/v1/commissions/{commission_id}/cancel",
    response_model=DealCommissionResponse,
)
def cancel_deal_commission_endpoint(
    commission_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("commission.update")
    ),
    db: Session = Depends(get_db_session),
) -> DealCommissionResponse:
    """Cancel proposed or agreed commission terms."""
    try:
        commission = cancel_deal_commission(
            db,
            organization_id=tenant_context.organization_id,
            commission_id=commission_id,
            current_user_id=tenant_context.membership.user_id,
        )
        if commission is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Commission not found.",
            )
        return _commit_and_refresh(db, commission)
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
            detail="The commission could not be cancelled.",
        ) from exc
    except Exception:
        db.rollback()
        raise

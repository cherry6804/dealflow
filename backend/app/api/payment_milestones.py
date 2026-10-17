
"""FastAPI routes for deal payment milestones."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.payment_milestones.schemas import (
    PaymentMilestoneCreateRequest,
    PaymentMilestoneListResponse,
    PaymentMilestoneMarkPaidRequest,
    PaymentMilestoneResponse,
    PaymentMilestoneUpdateRequest,
)
from app.payment_milestones.service import (
    cancel_payment_milestone,
    create_payment_milestone,
    get_payment_milestone,
    list_payment_milestones,
    mark_payment_milestone_paid,
    update_payment_milestone,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(tags=["payment-milestones"])


def _commit_and_refresh(
    db: Session,
    milestone,
) -> PaymentMilestoneResponse:
    """Commit a milestone change and return the refreshed record."""
    db.commit()
    db.refresh(milestone)
    return PaymentMilestoneResponse.model_validate(milestone)


@router.post(
    "/api/v1/deals/{deal_id}/payment-milestones",
    response_model=PaymentMilestoneResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_payment_milestone_endpoint(
    deal_id: UUID,
    payload: PaymentMilestoneCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("payment_milestones.create")
    ),
    db: Session = Depends(get_db_session),
) -> PaymentMilestoneResponse:
    """Create a milestone for a deal in the active organization."""
    try:
        milestone = create_payment_milestone(
            db,
            organization_id=tenant_context.organization_id,
            deal_id=deal_id,
            current_user_id=tenant_context.membership.user_id,
            payload=payload,
        )
        if milestone is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deal not found.",
            )
        return _commit_and_refresh(db, milestone)
    except HTTPException:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The payment milestone could not be saved.",
        ) from exc
    except Exception:
        db.rollback()
        raise


@router.get(
    "/api/v1/deals/{deal_id}/payment-milestones",
    response_model=PaymentMilestoneListResponse,
)
def list_payment_milestones_endpoint(
    deal_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("payment_milestones.read")
    ),
    db: Session = Depends(get_db_session),
) -> PaymentMilestoneListResponse:
    """List milestones for a deal in the active organization."""
    result = list_payment_milestones(
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
    return PaymentMilestoneListResponse(
        items=[
            PaymentMilestoneResponse.model_validate(item)
            for item in items
        ],
        total=total,
    )


@router.get(
    "/api/v1/payment-milestones/{milestone_id}",
    response_model=PaymentMilestoneResponse,
)
def get_payment_milestone_endpoint(
    milestone_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("payment_milestones.read")
    ),
    db: Session = Depends(get_db_session),
) -> PaymentMilestoneResponse:
    """Retrieve a milestone from the active organization."""
    milestone = get_payment_milestone(
        db,
        organization_id=tenant_context.organization_id,
        milestone_id=milestone_id,
    )
    if milestone is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment milestone not found.",
        )
    return PaymentMilestoneResponse.model_validate(milestone)


@router.patch(
    "/api/v1/payment-milestones/{milestone_id}",
    response_model=PaymentMilestoneResponse,
)
def update_payment_milestone_endpoint(
    milestone_id: UUID,
    payload: PaymentMilestoneUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("payment_milestones.update")
    ),
    db: Session = Depends(get_db_session),
) -> PaymentMilestoneResponse:
    """Update an editable pending milestone."""
    try:
        milestone = update_payment_milestone(
            db,
            organization_id=tenant_context.organization_id,
            milestone_id=milestone_id,
            payload=payload,
        )
        if milestone is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment milestone not found.",
            )
        return _commit_and_refresh(db, milestone)
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
            detail="The payment milestone could not be updated.",
        ) from exc
    except Exception:
        db.rollback()
        raise


@router.post(
    "/api/v1/payment-milestones/{milestone_id}/mark-paid",
    response_model=PaymentMilestoneResponse,
)
def mark_payment_milestone_paid_endpoint(
    milestone_id: UUID,
    payload: PaymentMilestoneMarkPaidRequest,
    tenant_context: TenantContext = Depends(
        require_permission("payment_milestones.update")
    ),
    db: Session = Depends(get_db_session),
) -> PaymentMilestoneResponse:
    """Record payment completion for a pending milestone."""
    try:
        milestone = mark_payment_milestone_paid(
            db,
            organization_id=tenant_context.organization_id,
            milestone_id=milestone_id,
            current_user_id=tenant_context.membership.user_id,
            payment_reference=payload.payment_reference,
        )
        if milestone is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment milestone not found.",
            )
        return _commit_and_refresh(db, milestone)
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
            detail="The payment could not be recorded.",
        ) from exc
    except Exception:
        db.rollback()
        raise


@router.post(
    "/api/v1/payment-milestones/{milestone_id}/cancel",
    response_model=PaymentMilestoneResponse,
)
def cancel_payment_milestone_endpoint(
    milestone_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("payment_milestones.update")
    ),
    db: Session = Depends(get_db_session),
) -> PaymentMilestoneResponse:
    """Cancel a pending payment milestone."""
    try:
        milestone = cancel_payment_milestone(
            db,
            organization_id=tenant_context.organization_id,
            milestone_id=milestone_id,
        )
        if milestone is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment milestone not found.",
            )
        return _commit_and_refresh(db, milestone)
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
            detail="The milestone could not be cancelled.",
        ) from exc
    except Exception:
        db.rollback()
        raise


"""FastAPI routes for DealFlow deal operations."""

from __future__ import annotations

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.deals.schemas import (
    DealCreateRequest,
    DealListResponse,
    DealResponse,
    DealStage,
    DealStageHistoryResponse,
    DealStageTransitionRequest,
)
from app.deals.service import (
    create_deal,
    get_deal,
    list_deals,
    transition_deal_stage,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/deals", tags=["deals"])


@router.post(
    "",
    response_model=DealResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_deal_endpoint(
    payload: DealCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("deals.create")
    ),
    db: Session = Depends(get_db_session),
) -> DealResponse:
    """Create a deal within the verified organization."""
    try:
        deal = create_deal(
            db=db,
            organization_id=tenant_context.organization_id,
            current_user_id=tenant_context.membership.user_id,
            payload=payload,
        )
        if deal is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Customer, property, or lead reference was not found "
                    "in this organization."
                ),
            )

        db.commit()
        db.refresh(deal)
        return DealResponse.model_validate(deal)

    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The deal could not be saved because of a data conflict.",
        ) from exc
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise


@router.get("", response_model=DealListResponse)
def list_deals_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    stage: DealStage | None = Query(default=None),
    owner_user_id: UUID | None = Query(default=None),
    tenant_context: TenantContext = Depends(
        require_permission("deals.read")
    ),
    db: Session = Depends(get_db_session),
) -> DealListResponse:
    """List deals belonging only to the verified organization."""
    items, total = list_deals(
        db,
        organization_id=tenant_context.organization_id,
        page=page,
        page_size=page_size,
        stage=stage,
        owner_user_id=owner_user_id,
    )

    return DealListResponse(
        items=[DealResponse.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
    )


@router.get("/{deal_id}", response_model=DealResponse)
def get_deal_endpoint(
    deal_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("deals.read")
    ),
    db: Session = Depends(get_db_session),
) -> DealResponse:
    """Return a deal only when it belongs to the verified organization."""
    deal = get_deal(
        db,
        organization_id=tenant_context.organization_id,
        deal_id=deal_id,
    )
    if deal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deal not found.",
        )
    return DealResponse.model_validate(deal)


@router.patch(
    "/{deal_id}/stage",
    response_model=DealResponse,
)
def transition_deal_stage_endpoint(
    deal_id: UUID,
    payload: DealStageTransitionRequest,
    tenant_context: TenantContext = Depends(
        require_permission("deals.update")
    ),
    db: Session = Depends(get_db_session),
) -> DealResponse:
    """Progress a deal and record its stage history."""
    try:
        deal = transition_deal_stage(
            db=db,
            organization_id=tenant_context.organization_id,
            deal_id=deal_id,
            actor_user_id=tenant_context.membership.user_id,
            target_stage=payload.stage,
            reason=payload.reason,
        )

        if deal is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deal not found.",
            )

        db.commit()
        db.refresh(deal)
        return DealResponse.model_validate(deal)

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
            detail="The stage transition could not be saved.",
        ) from exc
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

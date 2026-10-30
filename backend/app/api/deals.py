
"""FastAPI routes for DealFlow deal operations."""

from __future__ import annotations

from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import enforce_permission, require_permission
from app.automation_rules.execution_service import (
    execute_deal_created_automations,
)
from app.db.models.deal import Deal
from app.db.session import get_db_session
from app.deals.schemas import (
    DealCreateRequest,
    DealListResponse,
    DealResponse,
    DealStage,
    DealStageTransitionRequest,
    DealUpdateRequest,
)
from app.deals.service import (
    CLOSED_STAGES,
    DealClosedError,
    create_deal,
    get_deal,
    list_deals,
    transition_deal_stage,
    update_deal,
)
from app.notifications.service import create_notification
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/deals", tags=["deals"])


def _notify_deal_owner(
    db: Session,
    *,
    organization_id: UUID,
    deal: Deal,
    event_type: str,
    title: str,
    message: str,
    event_key: str,
) -> None:
    """Create a preference-aware notification in the current transaction."""
    create_notification(
        db,
        organization_id=organization_id,
        recipient_user_id=deal.owner_user_id,
        event_type=event_type,
        title=title,
        message=message,
        resource_type="deal",
        resource_id=str(deal.id),
        event_key=event_key,
    )


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
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> DealResponse:
    """Create a deal, notify its owner, and execute matching automations."""
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

        _notify_deal_owner(
            db,
            organization_id=tenant_context.organization_id,
            deal=deal,
            event_type="DEAL_CREATED",
            title="New deal created",
            message=f"A new deal has been created in stage {deal.stage}.",
            event_key=f"deal:{deal.id}:created",
        )

        # Deal creation, notification, and matching automations share
        # this transaction. The execution service does not commit.
        execute_deal_created_automations(
            db,
            organization_id=tenant_context.organization_id,
            deal=deal,
            user_context=user_context,
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
    "/{deal_id}",
    response_model=DealResponse,
)
def update_deal_endpoint(
    deal_id: UUID,
    payload: DealUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("deals.update")
    ),
    db: Session = Depends(get_db_session),
) -> DealResponse:
    """Update a deal's editable fields. Closed deals are read-only."""
    try:
        deal = update_deal(
            db=db,
            organization_id=tenant_context.organization_id,
            deal_id=deal_id,
            payload=payload,
        )
        if deal is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deal not found.",
            )
        db.commit()
    except DealClosedError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
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
    """Transition a deal, record history, and notify its owner."""
    # Closing a deal is a separate permission from moving it through the
    # pipeline, so an update-only role cannot win or lose a deal.
    if payload.stage.value in CLOSED_STAGES:
        enforce_permission(
            db,
            tenant_context=tenant_context,
            permission_key="deals.close",
        )

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

        new_stage = deal.stage

        if new_stage == DealStage.CLOSED_WON.value:
            event_type = "DEAL_CLOSED_WON"
            title = "Deal won"
            message = "Your deal has been marked as closed won."
        elif new_stage == DealStage.CLOSED_LOST.value:
            event_type = "DEAL_CLOSED_LOST"
            title = "Deal lost"
            message = "Your deal has been marked as closed lost."
        else:
            event_type = "DEAL_STAGE_CHANGED"
            title = "Deal stage updated"
            message = f"Your deal has moved to the {new_stage} stage."

        _notify_deal_owner(
            db,
            organization_id=tenant_context.organization_id,
            deal=deal,
            event_type=event_type,
            title=title,
            message=message,
            event_key=f"deal:{deal.id}:stage:{new_stage}",
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

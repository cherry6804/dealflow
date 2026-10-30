
"""FastAPI routes for deal negotiation state and history."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.deals.negotiation_schemas import (
    NegotiationCreateRequest,
    NegotiationHistoryListResponse,
    NegotiationHistoryResponse,
    NegotiationResponse,
    NegotiationUpdateRequest,
)
from app.deals.negotiation_service import (
    InvalidNegotiationChangeError,
    NegotiationAlreadyExistsError,
    create_negotiation,
    get_negotiation,
    list_negotiation_history,
    update_negotiation,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/deals", tags=["deal-negotiations"])


@router.post(
    "/{deal_id}/negotiation",
    response_model=NegotiationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_negotiation_endpoint(
    deal_id: UUID,
    payload: NegotiationCreateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("deal_negotiations.update")
    ),
    db: Session = Depends(get_db_session),
) -> NegotiationResponse:
    """Create the initial negotiation state and history entry."""
    try:
        negotiation = create_negotiation(
            db,
            organization_id=tenant_context.organization_id,
            deal_id=deal_id,
            actor_user_id=tenant_context.membership.user_id,
            state=payload.state,
            note=payload.note,
        )
        if negotiation is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deal not found.",
            )

        db.commit()
        db.refresh(negotiation)
        return NegotiationResponse.model_validate(negotiation)

    except NegotiationAlreadyExistsError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The negotiation could not be saved because of a data conflict.",
        ) from exc
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise


@router.get(
    "/{deal_id}/negotiation",
    response_model=NegotiationResponse,
)
def get_negotiation_endpoint(
    deal_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("deal_negotiations.read")
    ),
    db: Session = Depends(get_db_session),
) -> NegotiationResponse:
    """Retrieve the current negotiation state."""
    negotiation = get_negotiation(
        db,
        organization_id=tenant_context.organization_id,
        deal_id=deal_id,
    )
    if negotiation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deal negotiation not found.",
        )

    return NegotiationResponse.model_validate(negotiation)


@router.get(
    "/{deal_id}/negotiation/history",
    response_model=NegotiationHistoryListResponse,
)
def get_negotiation_history_endpoint(
    deal_id: UUID,
    tenant_context: TenantContext = Depends(
        require_permission("deal_negotiations.read")
    ),
    db: Session = Depends(get_db_session),
) -> NegotiationHistoryListResponse:
    """Retrieve negotiation changes in chronological order."""
    history = list_negotiation_history(
        db,
        organization_id=tenant_context.organization_id,
        deal_id=deal_id,
    )
    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deal negotiation not found.",
        )

    return NegotiationHistoryListResponse(
        items=[
            NegotiationHistoryResponse.model_validate(item)
            for item in history
        ],
        total=len(history),
    )


@router.patch(
    "/{deal_id}/negotiation",
    response_model=NegotiationResponse,
)
def update_negotiation_endpoint(
    deal_id: UUID,
    payload: NegotiationUpdateRequest,
    tenant_context: TenantContext = Depends(
        require_permission("deal_negotiations.update")
    ),
    db: Session = Depends(get_db_session),
) -> NegotiationResponse:
    """Change negotiation state and append a history record."""
    try:
        negotiation = update_negotiation(
            db,
            organization_id=tenant_context.organization_id,
            deal_id=deal_id,
            actor_user_id=tenant_context.membership.user_id,
            state=payload.state,
            note=payload.note,
        )
        if negotiation is None:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deal negotiation not found.",
            )

        db.commit()
        db.refresh(negotiation)
        return NegotiationResponse.model_validate(negotiation)

    except InvalidNegotiationChangeError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The negotiation could not be updated because of a data conflict.",
        ) from exc
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

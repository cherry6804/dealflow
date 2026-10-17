
"""Business operations for deal commissions."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.deal import Deal
from app.db.models.deal_commission import DealCommission
from app.deal_commissions.schemas import (
    DealCommissionCreateRequest,
    DealCommissionUpdateRequest,
)


def create_deal_commission(
    db: Session,
    *,
    organization_id: UUID,
    deal_id: UUID,
    current_user_id: UUID,
    payload: DealCommissionCreateRequest,
) -> DealCommission | None:
    """Create commission terms for a deal in the active organization."""
    deal_exists = db.scalar(
        select(Deal.id).where(
            Deal.id == deal_id,
            Deal.organization_id == organization_id,
        )
    )
    if deal_exists is None:
        return None

    commission = DealCommission(
        organization_id=organization_id,
        deal_id=deal_id,
        commission_type=payload.commission_type,
        fixed_amount=payload.fixed_amount,
        rate_percent=payload.rate_percent,
        currency=payload.currency,
        terms=payload.terms,
        status=DealCommission.STATUS_PROPOSED,
        created_by_user_id=current_user_id,
        updated_by_user_id=current_user_id,
    )
    db.add(commission)
    db.flush()
    db.refresh(commission)
    return commission


def list_deal_commissions(
    db: Session,
    *,
    organization_id: UUID,
    deal_id: UUID,
) -> tuple[list[DealCommission], int] | None:
    """List commissions for a deal belonging to the active organization."""
    if db.scalar(
        select(Deal.id).where(
            Deal.id == deal_id,
            Deal.organization_id == organization_id,
        )
    ) is None:
        return None

    statement = (
        select(DealCommission)
        .where(
            DealCommission.organization_id == organization_id,
            DealCommission.deal_id == deal_id,
        )
        .order_by(DealCommission.created_at, DealCommission.id)
    )
    items = list(db.scalars(statement).all())

    total = db.scalar(
        select(func.count())
        .select_from(DealCommission)
        .where(
            DealCommission.organization_id == organization_id,
            DealCommission.deal_id == deal_id,
        )
    ) or 0

    return items, total


def get_deal_commission(
    db: Session,
    *,
    organization_id: UUID,
    commission_id: UUID,
) -> DealCommission | None:
    """Retrieve a commission within the active organization."""
    return db.scalar(
        select(DealCommission).where(
            DealCommission.id == commission_id,
            DealCommission.organization_id == organization_id,
        )
    )


def update_deal_commission(
    db: Session,
    *,
    organization_id: UUID,
    commission_id: UUID,
    current_user_id: UUID,
    payload: DealCommissionUpdateRequest,
) -> DealCommission | None:
    """Update commission terms before payment or cancellation."""
    commission = db.scalar(
        select(DealCommission)
        .where(
            DealCommission.id == commission_id,
            DealCommission.organization_id == organization_id,
        )
        .with_for_update()
    )
    if commission is None:
        return None

    if commission.status not in {
        DealCommission.STATUS_PROPOSED,
        DealCommission.STATUS_AGREED,
    }:
        raise ValueError("Only proposed or agreed commissions can be edited.")

    changes = payload.model_dump(exclude_unset=True)

    commission_type = changes.get(
        "commission_type", commission.commission_type
    )
    fixed_amount = changes.get("fixed_amount", commission.fixed_amount)
    rate_percent = changes.get("rate_percent", commission.rate_percent)

    if commission_type == "FIXED":
        if fixed_amount is None or rate_percent is not None:
            raise ValueError(
                "FIXED commissions require fixed_amount and forbid rate_percent."
            )
    elif commission_type == "PERCENTAGE":
        if rate_percent is None or fixed_amount is not None:
            raise ValueError(
                "PERCENTAGE commissions require rate_percent and forbid fixed_amount."
            )
    else:
        raise ValueError("Unsupported commission type.")

    for field, value in changes.items():
        setattr(commission, field, value)

    # Changing terms after agreement requires agreement to be recorded again.
    if commission.status == DealCommission.STATUS_AGREED:
        commission.status = DealCommission.STATUS_PROPOSED
        commission.agreed_at = None

    commission.updated_by_user_id = current_user_id

    db.flush()
    db.refresh(commission)
    return commission


def agree_deal_commission(
    db: Session,
    *,
    organization_id: UUID,
    commission_id: UUID,
    current_user_id: UUID,
) -> DealCommission | None:
    """Record agreement to proposed commission terms."""
    commission = db.scalar(
        select(DealCommission)
        .where(
            DealCommission.id == commission_id,
            DealCommission.organization_id == organization_id,
        )
        .with_for_update()
    )
    if commission is None:
        return None

    if commission.status != DealCommission.STATUS_PROPOSED:
        raise ValueError("Only proposed commissions can be agreed.")

    commission.status = DealCommission.STATUS_AGREED
    commission.agreed_at = datetime.now(timezone.utc)
    commission.updated_by_user_id = current_user_id

    db.flush()
    db.refresh(commission)
    return commission


def mark_deal_commission_paid(
    db: Session,
    *,
    organization_id: UUID,
    commission_id: UUID,
    current_user_id: UUID,
    payment_reference: str | None,
) -> DealCommission | None:
    """Record payment for an agreed commission."""
    commission = db.scalar(
        select(DealCommission)
        .where(
            DealCommission.id == commission_id,
            DealCommission.organization_id == organization_id,
        )
        .with_for_update()
    )
    if commission is None:
        return None

    if commission.status != DealCommission.STATUS_AGREED:
        raise ValueError("Only agreed commissions can be marked as paid.")

    commission.status = DealCommission.STATUS_PAID
    commission.paid_at = datetime.now(timezone.utc)
    commission.payment_reference = payment_reference
    commission.updated_by_user_id = current_user_id

    db.flush()
    db.refresh(commission)
    return commission


def cancel_deal_commission(
    db: Session,
    *,
    organization_id: UUID,
    commission_id: UUID,
    current_user_id: UUID,
) -> DealCommission | None:
    """Cancel a proposed or agreed commission."""
    commission = db.scalar(
        select(DealCommission)
        .where(
            DealCommission.id == commission_id,
            DealCommission.organization_id == organization_id,
        )
        .with_for_update()
    )
    if commission is None:
        return None

    if commission.status not in {
        DealCommission.STATUS_PROPOSED,
        DealCommission.STATUS_AGREED,
    }:
        raise ValueError("Only proposed or agreed commissions can be cancelled.")

    commission.status = DealCommission.STATUS_CANCELLED
    commission.updated_by_user_id = current_user_id

    db.flush()
    db.refresh(commission)
    return commission


def calculate_commission_amount(
    commission: DealCommission,
    deal_expected_value: Decimal | None,
) -> Decimal | None:
    """Calculate the commission amount when the required deal value exists."""
    if commission.commission_type == DealCommission.TYPE_FIXED:
        return commission.fixed_amount

    if deal_expected_value is None or commission.rate_percent is None:
        return None

    return (deal_expected_value * commission.rate_percent / Decimal("100")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


"""Business operations for payment milestones."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.deal import Deal
from app.db.models.payment_milestone import PaymentMilestone
from app.payment_milestones.schemas import (
    PaymentMilestoneCreateRequest,
    PaymentMilestoneUpdateRequest,
)


def create_payment_milestone(
    db: Session,
    *,
    organization_id: UUID,
    deal_id: UUID,
    current_user_id: UUID,
    payload: PaymentMilestoneCreateRequest,
) -> PaymentMilestone | None:
    """Create a milestone only for a deal in the active organization."""
    deal = db.scalar(
        select(Deal.id).where(
            Deal.id == deal_id,
            Deal.organization_id == organization_id,
        )
    )
    if deal is None:
        return None

    milestone = PaymentMilestone(
        organization_id=organization_id,
        deal_id=deal_id,
        name=payload.name,
        amount=payload.amount,
        currency=payload.currency,
        due_at=payload.due_at,
        notes=payload.notes,
        status=PaymentMilestone.STATUS_PENDING,
        created_by_user_id=current_user_id,
    )
    db.add(milestone)
    db.flush()
    db.refresh(milestone)
    return milestone


def list_payment_milestones(
    db: Session,
    *,
    organization_id: UUID,
    deal_id: UUID,
) -> tuple[list[PaymentMilestone], int] | None:
    """List milestones for a deal in the active organization."""
    deal_exists = db.scalar(
        select(Deal.id).where(
            Deal.id == deal_id,
            Deal.organization_id == organization_id,
        )
    )
    if deal_exists is None:
        return None

    statement = (
        select(PaymentMilestone)
        .where(
            PaymentMilestone.organization_id == organization_id,
            PaymentMilestone.deal_id == deal_id,
        )
        .order_by(
            PaymentMilestone.due_at,
            PaymentMilestone.created_at,
            PaymentMilestone.id,
        )
    )
    items = list(db.scalars(statement).all())

    total = db.scalar(
        select(func.count())
        .select_from(PaymentMilestone)
        .where(
            PaymentMilestone.organization_id == organization_id,
            PaymentMilestone.deal_id == deal_id,
        )
    ) or 0

    return items, total


def get_payment_milestone(
    db: Session,
    *,
    organization_id: UUID,
    milestone_id: UUID,
) -> PaymentMilestone | None:
    """Get a milestone within the active organization."""
    return db.scalar(
        select(PaymentMilestone).where(
            PaymentMilestone.id == milestone_id,
            PaymentMilestone.organization_id == organization_id,
        )
    )


def update_payment_milestone(
    db: Session,
    *,
    organization_id: UUID,
    milestone_id: UUID,
    payload: PaymentMilestoneUpdateRequest,
) -> PaymentMilestone | None:
    """Update a pending milestone's editable fields."""
    milestone = db.scalar(
        select(PaymentMilestone)
        .where(
            PaymentMilestone.id == milestone_id,
            PaymentMilestone.organization_id == organization_id,
        )
        .with_for_update()
    )
    if milestone is None:
        return None

    if milestone.status != PaymentMilestone.STATUS_PENDING:
        raise ValueError("Only pending milestones can be edited.")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(milestone, field, value)

    db.flush()
    db.refresh(milestone)
    return milestone


def mark_payment_milestone_paid(
    db: Session,
    *,
    organization_id: UUID,
    milestone_id: UUID,
    current_user_id: UUID,
    payment_reference: str | None,
) -> PaymentMilestone | None:
    """Mark a pending milestone as paid and record the actor and timestamp."""
    milestone = db.scalar(
        select(PaymentMilestone)
        .where(
            PaymentMilestone.id == milestone_id,
            PaymentMilestone.organization_id == organization_id,
        )
        .with_for_update()
    )
    if milestone is None:
        return None

    if milestone.status != PaymentMilestone.STATUS_PENDING:
        raise ValueError("Only pending milestones can be marked as paid.")

    milestone.status = PaymentMilestone.STATUS_PAID
    milestone.paid_at = datetime.now(timezone.utc)
    milestone.paid_by_user_id = current_user_id
    milestone.payment_reference = payment_reference

    db.flush()
    db.refresh(milestone)
    return milestone


def cancel_payment_milestone(
    db: Session,
    *,
    organization_id: UUID,
    milestone_id: UUID,
) -> PaymentMilestone | None:
    """Cancel a pending milestone."""
    milestone = db.scalar(
        select(PaymentMilestone)
        .where(
            PaymentMilestone.id == milestone_id,
            PaymentMilestone.organization_id == organization_id,
        )
        .with_for_update()
    )
    if milestone is None:
        return None

    if milestone.status != PaymentMilestone.STATUS_PENDING:
        raise ValueError("Only pending milestones can be cancelled.")

    milestone.status = PaymentMilestone.STATUS_CANCELLED
    db.flush()
    db.refresh(milestone)
    return milestone

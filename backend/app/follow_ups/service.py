"""Follow-up creation service operations for DealFlow."""

from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.follow_ups.schemas import (
    FollowUpCreateRequest,
    FollowUpRescheduleRequest,
)


def create_follow_up(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
    lead_id: UUID,
    payload: FollowUpCreateRequest,
) -> FollowUp | None:
    """Create a pending follow-up for a lead in the verified organization.

    Return None when the lead does not belong to the organization.
    Raise ValueError when the requested owner is not an active member
    of the organization.
    """

    lead_statement = select(Lead.id).where(
        Lead.id == lead_id,
        Lead.organization_id == organization_id,
    )

    if db.scalar(lead_statement) is None:
        return None

    owner_user_id = payload.owner_user_id or current_user_id

    owner_statement = select(Membership.id).where(
        Membership.user_id == owner_user_id,
        Membership.organization_id == organization_id,
        Membership.is_active.is_(True),
    )

    if db.scalar(owner_statement) is None:
        raise ValueError(
            "Follow-up owner must be an active member of this organization."
        )

    follow_up = FollowUp(
        organization_id=organization_id,
        lead_id=lead_id,
        owner_user_id=owner_user_id,
        follow_up_type=payload.follow_up_type,
        title=payload.title,
        description=payload.description,
        due_at=payload.due_at,
        status=FollowUp.STATUS_PENDING,
    )

    db.add(follow_up)
    db.flush()
    db.refresh(follow_up)

    return follow_up


def complete_follow_up(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
    follow_up_id: UUID,
) -> FollowUp | None:
    """Complete a pending follow-up in the verified organization.

    Return None when the follow-up does not belong to the organization.
    Raise ValueError when the follow-up is not pending.
    """
    statement = select(FollowUp).where(
        FollowUp.id == follow_up_id,
        FollowUp.organization_id == organization_id,
    )
    follow_up = db.scalar(statement)

    if follow_up is None:
        return None

    if follow_up.status != FollowUp.STATUS_PENDING:
        raise ValueError("Only pending follow-ups can be completed.")

    follow_up.status = FollowUp.STATUS_COMPLETED
    follow_up.completed_at = datetime.now(timezone.utc)
    follow_up.completed_by_user_id = current_user_id

    db.flush()
    db.refresh(follow_up)

    return follow_up


def reschedule_follow_up(
    db: Session,
    *,
    organization_id: UUID,
    follow_up_id: UUID,
    payload: FollowUpRescheduleRequest,
) -> FollowUp | None:
    """Reschedule a pending follow-up in the verified organization.

    Return None when the follow-up does not belong to the organization.
    Raise ValueError when the follow-up is not pending.
    """
    statement = select(FollowUp).where(
        FollowUp.id == follow_up_id,
        FollowUp.organization_id == organization_id,
    )
    follow_up = db.scalar(statement)

    if follow_up is None:
        return None

    if follow_up.status != FollowUp.STATUS_PENDING:
        raise ValueError("Only pending follow-ups can be rescheduled.")

    follow_up.due_at = payload.due_at

    db.flush()
    db.refresh(follow_up)

    return follow_up

"""Follow-up creation service operations for DealFlow."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.follow_ups.schemas import FollowUpCreateRequest


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
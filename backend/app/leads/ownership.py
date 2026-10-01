"""Lead ownership validation for DealFlow."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.membership import Membership


def validate_lead_owner(
    db: Session,
    *,
    organization_id: UUID,
    owner_user_id: UUID | None,
) -> None:
    """
    Validate that a Lead owner is eligible for the supplied organization.

    A null owner means the Lead is intentionally unassigned.

    A non-null owner must:
    - have a Membership in the organization;
    - have an active Membership.
    """
    if owner_user_id is None:
        return

    statement = select(Membership).where(
        Membership.organization_id == organization_id,
        Membership.user_id == owner_user_id,
        Membership.is_active.is_(True),
    )

    membership = db.scalar(statement)

    if membership is None:
        raise ValueError("Lead owner must belong to the organization.")
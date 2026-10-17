
"""Service operations for DealFlow deals."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.customer_profile import CustomerProfile
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.property import Property
from app.db.models.deal import Deal
from app.deals.schemas import DealCreateRequest, DealStage


def create_deal(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
    payload: DealCreateRequest,
) -> Deal | None:
    """Create a deal using only references in the verified organization."""

    customer = db.scalar(
        select(CustomerProfile.id).where(
            CustomerProfile.id == payload.customer_profile_id,
            CustomerProfile.organization_id == organization_id,
            CustomerProfile.is_active.is_(True),
        )
    )
    if customer is None:
        return None

    property_record = db.scalar(
        select(Property.id).where(
            Property.id == payload.property_id,
            Property.organization_id == organization_id,
        )
    )
    if property_record is None:
        return None

    if payload.lead_id is not None:
        lead = db.scalar(
            select(Lead.id).where(
                Lead.id == payload.lead_id,
                Lead.organization_id == organization_id,
                Lead.is_active.is_(True),
            )
        )
        if lead is None:
            return None

    owner_user_id = payload.owner_user_id or current_user_id
    owner_membership = db.scalar(
        select(Membership.id).where(
            Membership.user_id == owner_user_id,
            Membership.organization_id == organization_id,
            Membership.is_active.is_(True),
        )
    )
    if owner_membership is None:
        raise ValueError("Deal owner must be an active member of the organization.")

    deal = Deal(
        organization_id=organization_id,
        customer_profile_id=payload.customer_profile_id,
        property_id=payload.property_id,
        lead_id=payload.lead_id,
        owner_user_id=owner_user_id,
        stage=payload.stage.value,
        expected_value=payload.expected_value,
        currency=payload.currency,
        notes=payload.notes,
    )
    db.add(deal)
    db.flush()
    db.refresh(deal)
    return deal


def get_deal(
    db: Session,
    *,
    organization_id: UUID,
    deal_id: UUID,
) -> Deal | None:
    """Return a deal only if it belongs to the verified organization."""
    return db.scalar(
        select(Deal).where(
            Deal.id == deal_id,
            Deal.organization_id == organization_id,
        )
    )


def list_deals(
    db: Session,
    *,
    organization_id: UUID,
    page: int = 1,
    page_size: int = 20,
    stage: DealStage | None = None,
    owner_user_id: UUID | None = None,
) -> tuple[list[Deal], int]:
    """List organization-scoped deals with optional filters."""
    statement = select(Deal).where(
        Deal.organization_id == organization_id
    )

    count_statement = select(func.count()).select_from(Deal).where(
        Deal.organization_id == organization_id
    )

    if stage is not None:
        statement = statement.where(Deal.stage == stage.value)
        count_statement = count_statement.where(Deal.stage == stage.value)

    if owner_user_id is not None:
        statement = statement.where(Deal.owner_user_id == owner_user_id)
        count_statement = count_statement.where(
            Deal.owner_user_id == owner_user_id
        )

    total = db.scalar(count_statement) or 0

    items = list(
        db.scalars(
            statement
            .order_by(Deal.created_at.desc(), Deal.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total

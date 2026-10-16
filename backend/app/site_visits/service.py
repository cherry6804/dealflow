"""Service operations for scheduling and listing DealFlow site visits."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.customer_profile import CustomerProfile
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.property import Property
from app.db.models.site_visit import SiteVisit
from app.site_visits.schemas import SiteVisitCreateRequest


def create_site_visit(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
    payload: SiteVisitCreateRequest,
) -> SiteVisit | None:
    """Schedule a visit for records belonging to the verified organization."""
    property_statement = select(Property.id).where(
        Property.id == payload.property_id,
        Property.organization_id == organization_id,
    )
    if db.scalar(property_statement) is None:
        return None

    if payload.lead_id is not None:
        lead_statement = select(Lead.id).where(
            Lead.id == payload.lead_id,
            Lead.organization_id == organization_id,
            Lead.is_active.is_(True),
        )
        if db.scalar(lead_statement) is None:
            return None

    if payload.customer_profile_id is not None:
        customer_statement = select(CustomerProfile.id).where(
            CustomerProfile.id == payload.customer_profile_id,
            CustomerProfile.organization_id == organization_id,
            CustomerProfile.is_active.is_(True),
        )
        if db.scalar(customer_statement) is None:
            return None

    owner_user_id = payload.owner_user_id or current_user_id
    owner_statement = select(Membership.id).where(
        Membership.user_id == owner_user_id,
        Membership.organization_id == organization_id,
        Membership.is_active.is_(True),
    )
    if db.scalar(owner_statement) is None:
        raise ValueError("Site visit owner must be an active member of this organization.")

    site_visit = SiteVisit(
        organization_id=organization_id,
        property_id=payload.property_id,
        lead_id=payload.lead_id,
        customer_profile_id=payload.customer_profile_id,
        owner_user_id=owner_user_id,
        scheduled_at=payload.scheduled_at,
        ends_at=payload.ends_at,
        status=SiteVisit.STATUS_SCHEDULED,
        outcome=None,
        notes=payload.notes,
    )
    db.add(site_visit)
    db.flush()
    db.refresh(site_visit)
    return site_visit


def list_site_visits(
    db: Session,
    *,
    organization_id: UUID,
    page: int = 1,
    page_size: int = 10,
    status_filter: str | None = None,
) -> tuple[list[SiteVisit], int]:
    """Return a paginated, organization-scoped list of site visits."""
    allowed_statuses = {
        SiteVisit.STATUS_SCHEDULED,
        SiteVisit.STATUS_COMPLETED,
        SiteVisit.STATUS_CANCELLED,
        SiteVisit.STATUS_NO_SHOW,
    }
    if status_filter is not None and status_filter not in allowed_statuses:
        raise ValueError("Invalid site visit status filter.")

    filters = [SiteVisit.organization_id == organization_id]
    if status_filter is not None:
        filters.append(SiteVisit.status == status_filter)

    total = db.scalar(select(func.count()).select_from(SiteVisit).where(*filters)) or 0
    statement = (
        select(SiteVisit)
        .where(*filters)
        .order_by(SiteVisit.scheduled_at.desc(), SiteVisit.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(db.scalars(statement).all()), int(total)

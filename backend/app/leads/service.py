"""Lead service-layer operations for DealFlow."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.contact import Contact
from app.db.models.lead import Lead
from app.leads.lifecycle import (
    validate_status_outcome,
    validate_status_transition,
)
from app.leads.ownership import validate_lead_owner
from app.leads.schemas import (
    LeadCreateRequest,
    LeadListQuery,
    LeadUpdateRequest,
)


def create_lead(
    db: Session,
    *,
    organization_id: UUID,
    payload: LeadCreateRequest,
) -> Lead | None:
    """Create a Lead within the verified tenant."""
    contact_statement = select(Contact).where(
        Contact.id == payload.contact_id,
        Contact.organization_id == organization_id,
    )

    contact = db.scalar(contact_statement)

    if contact is None:
        return None

    lead = Lead(
        organization_id=organization_id,
        contact_id=payload.contact_id,
        status=Lead.STATUS_NEW,
        interest=payload.interest,
        outcome=payload.outcome,
        next_action=payload.next_action,
        next_action_at=payload.next_action_at,
        owner_user_id=None,
        is_active=True,
    )

    db.add(lead)
    db.flush()
    db.refresh(lead)

    return lead


def get_lead(
    db: Session,
    *,
    organization_id: UUID,
    lead_id: UUID,
) -> Lead | None:
    """Retrieve a Lead within the verified tenant."""
    statement = select(Lead).where(
        Lead.id == lead_id,
        Lead.organization_id == organization_id,
    )

    return db.scalar(statement)


def update_lead(
    db: Session,
    *,
    organization_id: UUID,
    lead_id: UUID,
    payload: LeadUpdateRequest,
) -> Lead | None:
    """Update a Lead within the verified tenant."""
    lead = get_lead(
        db=db,
        organization_id=organization_id,
        lead_id=lead_id,
    )

    if lead is None:
        return None

    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        db.refresh(lead)
        return lead

    if "is_active" in updates and updates["is_active"] is None:
        raise ValueError("is_active cannot be null.")

    requested_status = updates.get(
        "status",
        lead.status,
    )

    requested_outcome = updates.get(
        "outcome",
        lead.outcome,
    )

    validate_status_transition(
        current_status=lead.status,
        new_status=requested_status,
    )

    validate_status_outcome(
        status=requested_status,
        outcome=requested_outcome,
    )

    if "owner_user_id" in updates:
        validate_lead_owner(
            db=db,
            organization_id=organization_id,
            owner_user_id=updates["owner_user_id"],
        )

    for field_name, value in updates.items():
        setattr(
            lead,
            field_name,
            value,
        )

    db.flush()
    db.refresh(lead)

    return lead


def list_leads(
    db: Session,
    *,
    organization_id: UUID,
    query: LeadListQuery,
) -> tuple[list[Lead], int]:
    """List Leads within the supplied organization."""
    filters = [
        Lead.organization_id == organization_id,
    ]

    if query.is_active is not None:
        filters.append(
            Lead.is_active == query.is_active,
        )

    if query.status is not None:
        filters.append(
            Lead.status == query.status,
        )

    if query.interest is not None:
        filters.append(
            Lead.interest == query.interest,
        )

    if query.outcome is not None:
        filters.append(
            Lead.outcome == query.outcome,
        )

    if query.owner_user_id is not None:
        filters.append(
            Lead.owner_user_id == query.owner_user_id,
        )

    if query.search is not None:
        search_term = f"%{query.search.strip()}%"

        filters.append(
            or_(
                Lead.next_action.ilike(search_term),
                Contact.first_name.ilike(search_term),
                Contact.last_name.ilike(search_term),
                Contact.email.ilike(search_term),
                Contact.phone.ilike(search_term),
            )
        )

    count_statement = (
        select(func.count())
        .select_from(Lead)
        .join(
            Contact,
            (Contact.id == Lead.contact_id)
            & (
                Contact.organization_id
                == Lead.organization_id
            ),
        )
        .where(*filters)
    )

    total = db.scalar(count_statement) or 0

    offset = (
        (query.page - 1)
        * query.page_size
    )

    statement = (
        select(Lead)
        .join(
            Contact,
            (Contact.id == Lead.contact_id)
            & (
                Contact.organization_id
                == Lead.organization_id
            ),
        )
        .where(*filters)
        .order_by(
            Lead.created_at.desc(),
            Lead.id.desc(),
        )
        .offset(offset)
        .limit(query.page_size)
    )

    leads = list(
        db.scalars(statement).all()
    )

    return leads, total
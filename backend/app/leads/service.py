"""Lead service-layer operations for DealFlow."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.contact import Contact
from app.db.models.lead import Lead
from app.leads.schemas import LeadCreateRequest


def create_lead(
    db: Session,
    *,
    organization_id: UUID,
    payload: LeadCreateRequest,
) -> Lead | None:
    """
    Create a Lead within the verified tenant.

    The organization is always supplied by the verified tenant context.
    The Contact must belong to the same organization.
    """
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
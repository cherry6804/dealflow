"""Lead service-layer operations for DealFlow."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.activity import Activity
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
    actor_id: UUID,
    lead_id: UUID,
    payload: LeadUpdateRequest,
) -> Lead | None:
    """Update a Lead and record status, owner, and next-action changes."""
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

    # Capture persisted values before applying requested changes.
    previous_status = lead.status
    previous_owner_user_id = lead.owner_user_id
    previous_next_action = lead.next_action
    previous_next_action_at = lead.next_action_at

    requested_status = updates.get(
        "status",
        previous_status,
    )

    requested_outcome = updates.get(
        "outcome",
        lead.outcome,
    )

    validate_status_transition(
        current_status=previous_status,
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

    # Create activities only for fields explicitly supplied and actually changed.
    status_changed = (
        "status" in updates
        and updates["status"] != previous_status
    )

    owner_changed = (
        "owner_user_id" in updates
        and updates["owner_user_id"] != previous_owner_user_id
    )

    next_action_changed = (
        "next_action" in updates
        and updates["next_action"] != previous_next_action
    )

    next_action_at_changed = (
        "next_action_at" in updates
        and updates["next_action_at"] != previous_next_action_at
    )

    # Apply all requested lead changes.
    for field_name, value in updates.items():
        setattr(
            lead,
            field_name,
            value,
        )

    # Record status changes in the same transaction.
    if status_changed:
        db.add(
            Activity(
                organization_id=organization_id,
                lead_id=lead.id,
                actor_id=actor_id,
                activity_type=Activity.TYPE_STATUS_CHANGE,
                title="Lead status changed",
                description=(
                    f"Status changed from {previous_status} "
                    f"to {lead.status}."
                ),
                details={
                    "old_status": previous_status,
                    "new_status": lead.status,
                },
            )
        )

    # Record ownership changes in the same transaction.
    if owner_changed:
        db.add(
            Activity(
                organization_id=organization_id,
                lead_id=lead.id,
                actor_id=actor_id,
                activity_type=Activity.TYPE_OWNER_CHANGE,
                title="Lead owner changed",
                description="The lead owner was changed.",
                details={
                    "old_owner_user_id": (
                        str(previous_owner_user_id)
                        if previous_owner_user_id is not None
                        else None
                    ),
                    "new_owner_user_id": (
                        str(lead.owner_user_id)
                        if lead.owner_user_id is not None
                        else None
                    ),
                },
            )
        )

    # Record next-action text changes.
    if next_action_changed:
        db.add(
            Activity(
                organization_id=organization_id,
                lead_id=lead.id,
                actor_id=actor_id,
                activity_type=Activity.TYPE_OTHER,
                title="Lead next action changed",
                description="The lead's next action was changed.",
                details={
                    "field": "next_action",
                    "old_next_action": previous_next_action,
                    "new_next_action": lead.next_action,
                },
            )
        )

    # Record scheduling changes independently, including clearing a date.
    if next_action_at_changed:
        db.add(
            Activity(
                organization_id=organization_id,
                lead_id=lead.id,
                actor_id=actor_id,
                activity_type=Activity.TYPE_OTHER,
                title="Lead follow-up schedule changed",
                description="The lead's follow-up schedule was changed.",
                details={
                    "field": "next_action_at",
                    "old_next_action_at": (
                        previous_next_action_at.isoformat()
                        if previous_next_action_at is not None
                        else None
                    ),
                    "new_next_action_at": (
                        lead.next_action_at.isoformat()
                        if lead.next_action_at is not None
                        else None
                    ),
                },
            )
        )

    # Flush without committing. The API endpoint commits the lead and
    # generated activities together.
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
"""Business services for the DealFlow Contact domain."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.contacts.schemas import (
    ContactCreateRequest,
    ContactListQuery,
    ContactUpdateRequest,
)
from app.db.models.contact import Contact


def create_contact(
    db: Session,
    *,
    organization_id: UUID,
    payload: ContactCreateRequest,
) -> Contact:
    """Create a Contact owned by the supplied verified organization."""
    contact = Contact(
        organization_id=organization_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        phone=payload.phone,
        is_active=True,
    )
    db.add(contact)
    db.flush()
    db.refresh(contact)
    return contact


def get_contact(
    db: Session,
    *,
    organization_id: UUID,
    contact_id: UUID,
) -> Contact | None:
    """Retrieve a Contact only within the supplied organization."""
    statement = select(Contact).where(
        Contact.id == contact_id,
        Contact.organization_id == organization_id,
    )
    return db.scalar(statement)


def update_contact(
    db: Session,
    *,
    organization_id: UUID,
    contact_id: UUID,
    payload: ContactUpdateRequest,
) -> Contact | None:
    """Partially update a Contact within the supplied organization."""
    contact = get_contact(
        db=db,
        organization_id=organization_id,
        contact_id=contact_id,
    )

    if contact is None:
        return None

    update_data = payload.model_dump(exclude_unset=True)

    for field_name, value in update_data.items():
        setattr(contact, field_name, value)

    db.flush()
    db.refresh(contact)

    return contact


def list_contacts(
    db: Session,
    *,
    organization_id: UUID,
    query: ContactListQuery,
) -> tuple[list[Contact], int]:
    """List Contacts within the supplied organization."""
    filters = [
        Contact.organization_id == organization_id,
    ]

    if query.is_active is not None:
        filters.append(Contact.is_active == query.is_active)

    if query.search is not None:
        search_term = f"%{query.search.strip()}%"
        filters.append(
            or_(
                Contact.first_name.ilike(search_term),
                Contact.last_name.ilike(search_term),
                Contact.email.ilike(search_term),
                Contact.phone.ilike(search_term),
            )
        )

    count_statement = select(func.count()).select_from(Contact).where(*filters)
    total = db.scalar(count_statement) or 0

    offset = (query.page - 1) * query.page_size

    statement = (
        select(Contact)
        .where(*filters)
        .order_by(
            Contact.created_at.desc(),
            Contact.id.desc(),
        )
        .offset(offset)
        .limit(query.page_size)
    )

    contacts = list(db.scalars(statement).all())

    return contacts, total
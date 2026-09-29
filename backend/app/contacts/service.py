"""Business services for the DealFlow Contact domain."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contacts.schemas import ContactCreateRequest
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
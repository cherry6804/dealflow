"""Business services for the DealFlow Contact domain."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.contacts.schemas import (
    ContactCreateRequest,
    ContactListQuery,
    ContactUpdateRequest,
)
from app.db.models.contact import Contact
from app.imports.duplicate_detection import (
    normalize_email,
    normalize_phone,
)


class ContactDuplicateError(ValueError):
    """Raised when a contact identifier is already used in an organization."""

    def __init__(self, fields: list[Literal["email", "phone"]]) -> None:
        self.fields = fields
        super().__init__(
            "A contact with this email or phone number already exists "
            "in this organization."
        )


def _find_duplicate_identifiers(
    db: Session,
    *,
    organization_id: UUID,
    email: object,
    phone: object,
    exclude_contact_id: UUID | None = None,
) -> list[Literal["email", "phone"]]:
    """Find conflicting identifiers within the same organization."""
    email_key = normalize_email(email)
    phone_key = normalize_phone(phone)

    if not email_key and not phone_key:
        return []

    statement = select(Contact.email, Contact.phone).where(
        Contact.organization_id == organization_id
    )

    if exclude_contact_id is not None:
        statement = statement.where(Contact.id != exclude_contact_id)

    duplicate_fields: list[Literal["email", "phone"]] = []

    for existing_email, existing_phone in db.execute(statement).all():
        if (
            email_key
            and normalize_email(existing_email) == email_key
            and "email" not in duplicate_fields
        ):
            duplicate_fields.append("email")

        if (
            phone_key
            and normalize_phone(existing_phone) == phone_key
            and "phone" not in duplicate_fields
        ):
            duplicate_fields.append("phone")

        if len(duplicate_fields) == 2:
            break

    return duplicate_fields


def create_contact(
    db: Session,
    *,
    organization_id: UUID,
    payload: ContactCreateRequest,
    import_batch_id: UUID | None = None,
    source_row_number: int | None = None,
    imported_at: datetime | None = None,
) -> Contact:
    """Create a tenant-owned Contact with optional import provenance."""
    duplicate_fields = _find_duplicate_identifiers(
        db,
        organization_id=organization_id,
        email=payload.email,
        phone=payload.phone,
    )

    if duplicate_fields:
        raise ContactDuplicateError(duplicate_fields)

    contact = Contact(
        organization_id=organization_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        phone=payload.phone,
        is_active=True,
        import_batch_id=import_batch_id,
        source_row_number=source_row_number,
        imported_at=imported_at,
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

    duplicate_fields = _find_duplicate_identifiers(
        db,
        organization_id=organization_id,
        email=update_data.get("email", contact.email),
        phone=update_data.get("phone", contact.phone),
        exclude_contact_id=contact.id,
    )

    if duplicate_fields:
        raise ContactDuplicateError(duplicate_fields)

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
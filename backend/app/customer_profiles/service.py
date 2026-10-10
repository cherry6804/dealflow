"""Business services for the DealFlow Customer Profile domain."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
from app.customer_profiles.schemas import (
    CustomerProfileCreateRequest,
    CustomerProfileReplaceRequest,
    CustomerProfileUpdateRequest,
)


def create_customer_profile(
    db: Session,
    *,
    organization_id: UUID,
    payload: CustomerProfileCreateRequest,
) -> CustomerProfile | None:
    """Register an existing tenant-owned Contact as a Customer.

    Returns None when the Contact does not exist in the tenant.
    Raises ValueError when the Contact already has a Customer Profile.
    """
    contact = db.scalar(
        select(Contact).where(
            Contact.id == payload.contact_id,
            Contact.organization_id == organization_id,
        )
    )

    if contact is None:
        return None

    existing_profile = db.scalar(
        select(CustomerProfile.id).where(
            CustomerProfile.contact_id == contact.id
        )
    )

    if existing_profile is not None:
        raise ValueError("This Contact is already registered as a Customer.")

    profile = CustomerProfile(
        organization_id=organization_id,
        contact_id=contact.id,
        customer_notes=payload.customer_notes,
        is_active=True,
    )
    db.add(profile)
    db.flush()

    return get_customer_profile(
        db,
        organization_id=organization_id,
        customer_profile_id=profile.id,
    )


def get_customer_profile(
    db: Session,
    *,
    organization_id: UUID,
    customer_profile_id: UUID,
) -> CustomerProfile | None:
    """Retrieve a Customer Profile within the supplied tenant."""
    statement = (
        select(CustomerProfile)
        .options(selectinload(CustomerProfile.contact))
        .where(
            CustomerProfile.id == customer_profile_id,
            CustomerProfile.organization_id == organization_id,
        )
    )
    return db.scalar(statement)


def list_customer_profiles(
    db: Session,
    *,
    organization_id: UUID,
    page: int,
    page_size: int,
    search: str | None = None,
    is_active: bool | None = True,
) -> tuple[list[CustomerProfile], int]:
    """List Customer Profiles within the supplied tenant."""
    filters = [CustomerProfile.organization_id == organization_id]

    if is_active is not None:
        filters.append(CustomerProfile.is_active == is_active)

    if search is not None:
        search_term = f"%{search.strip()}%"
        filters.append(
            or_(
                Contact.first_name.ilike(search_term),
                Contact.last_name.ilike(search_term),
                Contact.email.ilike(search_term),
                Contact.phone.ilike(search_term),
                CustomerProfile.customer_notes.ilike(search_term),
            )
        )

    count_statement = (
        select(func.count())
        .select_from(CustomerProfile)
        .join(Contact, Contact.id == CustomerProfile.contact_id)
        .where(*filters)
    )
    total = db.scalar(count_statement) or 0

    statement = (
        select(CustomerProfile)
        .join(Contact, Contact.id == CustomerProfile.contact_id)
        .options(selectinload(CustomerProfile.contact))
        .where(*filters)
        .order_by(CustomerProfile.created_at.desc(), CustomerProfile.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    return list(db.scalars(statement).all()), total


def update_customer_profile(
    db: Session,
    *,
    organization_id: UUID,
    customer_profile_id: UUID,
    payload: CustomerProfileUpdateRequest,
) -> CustomerProfile | None:
    """Partially update a Customer Profile within the supplied tenant."""
    profile = get_customer_profile(
        db,
        organization_id=organization_id,
        customer_profile_id=customer_profile_id,
    )

    if profile is None:
        return None

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field_name, value)

    db.flush()
    db.refresh(profile)

    return get_customer_profile(
        db,
        organization_id=organization_id,
        customer_profile_id=customer_profile_id,
    )


def replace_customer_profile(
    db: Session,
    *,
    organization_id: UUID,
    customer_profile_id: UUID,
    payload: CustomerProfileReplaceRequest,
) -> CustomerProfile | None:
    """Replace editable Customer Profile fields within the supplied tenant."""
    profile = get_customer_profile(
        db,
        organization_id=organization_id,
        customer_profile_id=customer_profile_id,
    )

    if profile is None:
        return None

    profile.customer_notes = payload.customer_notes
    profile.is_active = payload.is_active

    db.flush()
    db.refresh(profile)

    return get_customer_profile(
        db,
        organization_id=organization_id,
        customer_profile_id=customer_profile_id,
    )


def deactivate_customer_profile(
    db: Session,
    *,
    organization_id: UUID,
    customer_profile_id: UUID,
) -> CustomerProfile | None:
    """Safely deactivate a Customer Profile instead of physically deleting it."""
    profile = get_customer_profile(
        db,
        organization_id=organization_id,
        customer_profile_id=customer_profile_id,
    )

    if profile is None:
        return None

    profile.is_active = False
    db.flush()
    db.refresh(profile)

    return get_customer_profile(
        db,
        organization_id=organization_id,
        customer_profile_id=customer_profile_id,
    )

"""Business operations for tenant-scoped referrals."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
from app.db.models.deal import Deal
from app.db.models.referral import Referral
from app.referrals.schemas import ReferralCreateRequest, ReferralUpdateRequest


def _association_exists(
    db: Session,
    model: type,
    record_id: UUID,
    organization_id: UUID,
) -> bool:
    """Return whether an association belongs to the active organization."""
    return (
        db.scalar(
            select(model.id).where(
                model.id == record_id,
                model.organization_id == organization_id,
            )
        )
        is not None
    )


def _validate_associations(
    db: Session,
    *,
    organization_id: UUID,
    customer_profile_id: UUID | None,
    referrer_contact_id: UUID | None,
    deal_id: UUID | None,
) -> None:
    """Prevent referral associations from crossing organization boundaries."""
    associations = (
        (
            CustomerProfile,
            customer_profile_id,
            "Customer profile",
        ),
        (
            Contact,
            referrer_contact_id,
            "Referring contact",
        ),
        (
            Deal,
            deal_id,
            "Deal",
        ),
    )

    for model, record_id, label in associations:
        if record_id is not None and not _association_exists(
            db, model, record_id, organization_id
        ):
            raise ValueError(
                f"{label} was not found in the active organization."
            )


def create_referral(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
    payload: ReferralCreateRequest,
) -> Referral:
    """Create a referral inside the active organization."""
    _validate_associations(
        db,
        organization_id=organization_id,
        customer_profile_id=payload.customer_profile_id,
        referrer_contact_id=payload.referrer_contact_id,
        deal_id=payload.deal_id,
    )

    referral = Referral(
        organization_id=organization_id,
        customer_profile_id=payload.customer_profile_id,
        referrer_contact_id=payload.referrer_contact_id,
        deal_id=payload.deal_id,
        referral_name=payload.referral_name,
        referral_phone=payload.referral_phone,
        referral_email=str(payload.referral_email) if payload.referral_email else None,
        status=payload.status,
        notes=payload.notes,
        created_by_user_id=current_user_id,
        updated_by_user_id=current_user_id,
    )
    db.add(referral)
    db.flush()
    db.refresh(referral)
    return referral


def list_referrals(
    db: Session,
    *,
    organization_id: UUID,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    status: str | None = None,
) -> tuple[list[Referral], int]:
    """List active referrals with organization-scoped filters."""
    statement = select(Referral).where(
        Referral.organization_id == organization_id,
        Referral.is_active.is_(True),
    )

    if search:
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Referral.referral_name.ilike(pattern),
                Referral.referral_phone.ilike(pattern),
                Referral.referral_email.ilike(pattern),
            )
        )

    if status:
        statement = statement.where(Referral.status == status)

    total = db.scalar(
        select(func.count()).select_from(statement.subquery())
    ) or 0

    items = list(
        db.scalars(
            statement.order_by(
                Referral.created_at.desc(),
                Referral.id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return items, total


def get_referral(
    db: Session,
    *,
    organization_id: UUID,
    referral_id: UUID,
    include_inactive: bool = False,
) -> Referral | None:
    """Get a referral without exposing another organization's records."""
    statement = select(Referral).where(
        Referral.id == referral_id,
        Referral.organization_id == organization_id,
    )
    if not include_inactive:
        statement = statement.where(Referral.is_active.is_(True))
    return db.scalar(statement)


def update_referral(
    db: Session,
    *,
    organization_id: UUID,
    referral_id: UUID,
    current_user_id: UUID,
    payload: ReferralUpdateRequest,
) -> Referral | None:
    """Update a referral and validate its resulting associations."""
    referral = db.scalar(
        select(Referral)
        .where(
            Referral.id == referral_id,
            Referral.organization_id == organization_id,
            Referral.is_active.is_(True),
        )
        .with_for_update()
    )
    if referral is None:
        return None

    changes = payload.model_dump(exclude_unset=True)

    resulting_customer_id = changes.get(
        "customer_profile_id", referral.customer_profile_id
    )
    resulting_contact_id = changes.get(
        "referrer_contact_id", referral.referrer_contact_id
    )
    resulting_deal_id = changes.get("deal_id", referral.deal_id)

    if not any(
        (resulting_customer_id, resulting_contact_id, resulting_deal_id)
    ):
        raise ValueError(
            "A referral must remain associated with a customer, "
            "referring contact, or deal."
        )

    _validate_associations(
        db,
        organization_id=organization_id,
        customer_profile_id=resulting_customer_id,
        referrer_contact_id=resulting_contact_id,
        deal_id=resulting_deal_id,
    )

    for field, value in changes.items():
        if field == "referral_email":
            value = str(value) if value is not None else None
        setattr(referral, field, value)

    referral.updated_by_user_id = current_user_id
    db.flush()
    db.refresh(referral)
    return referral


def deactivate_referral(
    db: Session,
    *,
    organization_id: UUID,
    referral_id: UUID,
    current_user_id: UUID,
) -> Referral | None:
    """Soft-deactivate a referral, preserving its history."""
    referral = db.scalar(
        select(Referral)
        .where(
            Referral.id == referral_id,
            Referral.organization_id == organization_id,
            Referral.is_active.is_(True),
        )
        .with_for_update()
    )
    if referral is None:
        return None

    referral.is_active = False
    referral.updated_by_user_id = current_user_id
    db.flush()
    db.refresh(referral)
    return referral

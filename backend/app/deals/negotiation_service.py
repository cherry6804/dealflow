
"""Tenant-scoped service operations for deal negotiations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.deal import Deal
from app.db.models.deal_negotiation import (
    DealNegotiation,
    DealNegotiationHistory,
)
from app.deals.negotiation_schemas import NegotiationState


class NegotiationAlreadyExistsError(Exception):
    """Raised when a deal already has a negotiation record."""


class InvalidNegotiationChangeError(Exception):
    """Raised when a negotiation transition violates business rules."""


# Explicit business transition policy.
# COMPLETED and CANCELLED can only be reopened to IN_PROGRESS.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "IN_PROGRESS": {
        "WAITING_ON_CUSTOMER",
        "WAITING_ON_SELLER",
        "TERMS_AGREED",
        "STALLED",
        "CANCELLED",
    },
    "WAITING_ON_CUSTOMER": {
        "IN_PROGRESS",
        "WAITING_ON_SELLER",
        "TERMS_AGREED",
        "STALLED",
        "CANCELLED",
    },
    "WAITING_ON_SELLER": {
        "IN_PROGRESS",
        "WAITING_ON_CUSTOMER",
        "TERMS_AGREED",
        "STALLED",
        "CANCELLED",
    },
    "STALLED": {
        "IN_PROGRESS",
        "WAITING_ON_CUSTOMER",
        "WAITING_ON_SELLER",
        "TERMS_AGREED",
        "CANCELLED",
    },
    "TERMS_AGREED": {
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    },
    "COMPLETED": {"IN_PROGRESS"},
    "CANCELLED": {"IN_PROGRESS"},
}


def get_negotiation(
    db: Session,
    *,
    organization_id: UUID,
    deal_id: UUID,
) -> DealNegotiation | None:
    """Get a negotiation through a deal in the active organization."""
    deal_exists = db.scalar(
        select(Deal.id).where(
            Deal.id == deal_id,
            Deal.organization_id == organization_id,
        )
    )
    if deal_exists is None:
        return None

    return db.scalar(
        select(DealNegotiation).where(
            DealNegotiation.deal_id == deal_id,
            DealNegotiation.organization_id == organization_id,
        )
    )


def create_negotiation(
    db: Session,
    *,
    organization_id: UUID,
    deal_id: UUID,
    actor_user_id: UUID,
    state: NegotiationState,
    note: str | None,
) -> DealNegotiation | None:
    """Create the initial negotiation and history entry.

    The caller owns the transaction and must commit or roll back.
    """
    deal_exists = db.scalar(
        select(Deal.id).where(
            Deal.id == deal_id,
            Deal.organization_id == organization_id,
        )
    )
    if deal_exists is None:
        return None

    existing = db.scalar(
        select(DealNegotiation.id).where(
            DealNegotiation.deal_id == deal_id,
            DealNegotiation.organization_id == organization_id,
        )
    )
    if existing is not None:
        raise NegotiationAlreadyExistsError(
            "A negotiation already exists for this deal."
        )

    if state == NegotiationState.CANCELLED and not note:
        raise InvalidNegotiationChangeError(
            "A reason is required when cancelling a negotiation."
        )

    negotiation = DealNegotiation(
        organization_id=organization_id,
        deal_id=deal_id,
        state=state.value,
        updated_by_user_id=actor_user_id,
    )
    db.add(negotiation)
    db.flush()

    db.add(
        DealNegotiationHistory(
            organization_id=organization_id,
            negotiation_id=negotiation.id,
            from_state=None,
            to_state=state.value,
            actor_user_id=actor_user_id,
            note=note,
        )
    )
    db.flush()
    db.refresh(negotiation)
    return negotiation


def update_negotiation(
    db: Session,
    *,
    organization_id: UUID,
    deal_id: UUID,
    actor_user_id: UUID,
    state: NegotiationState,
    note: str | None,
) -> DealNegotiation | None:
    """Validate, update and audit a negotiation transition atomically."""
    negotiation = db.scalar(
        select(DealNegotiation)
        .join(
            Deal,
            (Deal.id == DealNegotiation.deal_id)
            & (
                Deal.organization_id
                == DealNegotiation.organization_id
            ),
        )
        .where(
            Deal.id == deal_id,
            Deal.organization_id == organization_id,
            DealNegotiation.organization_id == organization_id,
        )
        .with_for_update()
    )
    if negotiation is None:
        return None

    previous_state = negotiation.state
    next_state = state.value

    if previous_state == next_state:
        raise InvalidNegotiationChangeError(
            "The negotiation is already in the requested state."
        )

    if next_state not in ALLOWED_TRANSITIONS.get(previous_state, set()):
        raise InvalidNegotiationChangeError(
            f"Transition from {previous_state} to {next_state} "
            "is not allowed."
        )

    # Cancellation must always include a reason.
    if next_state == "CANCELLED" and not note:
        raise InvalidNegotiationChangeError(
            "A reason is required when cancelling a negotiation."
        )

    # Reopening a completed/cancelled negotiation must be explicit
    # and auditable. Returning from agreed terms to negotiation also
    # requires a reason for renegotiating.
    requires_reason = (
        previous_state in {"COMPLETED", "CANCELLED"}
        or (
            previous_state == "TERMS_AGREED"
            and next_state == "IN_PROGRESS"
        )
    )
    if requires_reason and not note:
        raise InvalidNegotiationChangeError(
            "A reason is required when reopening or renegotiating."
        )

    negotiation.state = next_state
    negotiation.updated_by_user_id = actor_user_id

    db.add(
        DealNegotiationHistory(
            organization_id=organization_id,
            negotiation_id=negotiation.id,
            from_state=previous_state,
            to_state=next_state,
            actor_user_id=actor_user_id,
            note=note,
        )
    )
    db.flush()
    db.refresh(negotiation)
    return negotiation


def list_negotiation_history(
    db: Session,
    *,
    organization_id: UUID,
    deal_id: UUID,
) -> list[DealNegotiationHistory] | None:
    """List history chronologically for a tenant-owned deal."""
    negotiation = get_negotiation(
        db,
        organization_id=organization_id,
        deal_id=deal_id,
    )
    if negotiation is None:
        return None

    return list(
        db.scalars(
            select(DealNegotiationHistory)
            .where(
                DealNegotiationHistory.organization_id == organization_id,
                DealNegotiationHistory.negotiation_id == negotiation.id,
            )
            .order_by(
                DealNegotiationHistory.created_at.asc(),
                DealNegotiationHistory.id.asc(),
            )
        ).all()
    )

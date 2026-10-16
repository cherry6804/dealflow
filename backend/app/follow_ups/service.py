"""Follow-up creation service operations for DealFlow."""

from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.db.models.site_visit import SiteVisit
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.follow_ups.schemas import (
    BulkFollowUpItemResult,
    BulkFollowUpRequest,
    BulkFollowUpRescheduleRequest,
    FollowUpCreateRequest,
    FollowUpRescheduleRequest,
)

def create_follow_up(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
    lead_id: UUID,
    payload: FollowUpCreateRequest,
) -> FollowUp | None:
    """Create a pending follow-up for a lead in the verified organization.

    Return None when the lead does not belong to the organization.
    Raise ValueError when the requested owner is not an active member
    of the organization.
    """

    lead_statement = select(Lead.id).where(
        Lead.id == lead_id,
        Lead.organization_id == organization_id,
    )

    if db.scalar(lead_statement) is None:
        return None

    owner_user_id = payload.owner_user_id or current_user_id

    owner_statement = select(Membership.id).where(
        Membership.user_id == owner_user_id,
        Membership.organization_id == organization_id,
        Membership.is_active.is_(True),
    )

    if db.scalar(owner_statement) is None:
        raise ValueError(
            "Follow-up owner must be an active member of this organization."
        )

    follow_up = FollowUp(
        organization_id=organization_id,
        lead_id=lead_id,
        owner_user_id=owner_user_id,
        follow_up_type=payload.follow_up_type,
        title=payload.title,
        description=payload.description,
        due_at=payload.due_at,
        status=FollowUp.STATUS_PENDING,
    )

    db.add(follow_up)
    db.flush()
    db.refresh(follow_up)

    return follow_up

def create_site_visit_follow_up(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
    site_visit_id: UUID,
    payload: FollowUpCreateRequest,
) -> FollowUp | None:
    """Create one follow-up from an eligible completed site visit."""
    statement = select(SiteVisit).where(
        SiteVisit.id == site_visit_id,
        SiteVisit.organization_id == organization_id,
    )
    site_visit = db.scalar(statement)

    if site_visit is None:
        return None

    if (
        site_visit.status != SiteVisit.STATUS_COMPLETED
        or site_visit.outcome != "FOLLOW_UP_REQUIRED"
    ):
        raise ValueError(
            "A follow-up can only be created for a completed visit "
            "with the FOLLOW_UP_REQUIRED outcome."
        )

    if site_visit.lead_id is None:
        raise ValueError(
            "This site visit has no linked lead. "
            "A follow-up requires a lead."
        )

    existing_statement = select(FollowUp.id).where(
        FollowUp.organization_id == organization_id,
        FollowUp.site_visit_id == site_visit_id,
    )
    if db.scalar(existing_statement) is not None:
        raise ValueError(
            "A follow-up already exists for this site visit."
        )

    follow_up = create_follow_up(
        db,
        organization_id=organization_id,
        current_user_id=current_user_id,
        lead_id=site_visit.lead_id,
        payload=payload,
    )

    if follow_up is None:
        return None

    follow_up.site_visit_id = site_visit.id
    db.flush()
    db.refresh(follow_up)

    return follow_up

def complete_follow_up(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
    follow_up_id: UUID,
) -> FollowUp | None:
    """Complete a pending follow-up in the verified organization.

    Return None when the follow-up does not belong to the organization.
    Raise ValueError when the follow-up is not pending.
    """
    statement = select(FollowUp).where(
        FollowUp.id == follow_up_id,
        FollowUp.organization_id == organization_id,
    )
    follow_up = db.scalar(statement)

    if follow_up is None:
        return None

    if follow_up.status != FollowUp.STATUS_PENDING:
        raise ValueError("Only pending follow-ups can be completed.")

    follow_up.status = FollowUp.STATUS_COMPLETED
    follow_up.completed_at = datetime.now(timezone.utc)
    follow_up.completed_by_user_id = current_user_id

    db.flush()
    db.refresh(follow_up)

    return follow_up


def reschedule_follow_up(
    db: Session,
    *,
    organization_id: UUID,
    follow_up_id: UUID,
    payload: FollowUpRescheduleRequest,
) -> FollowUp | None:
    """Reschedule a pending follow-up in the verified organization.

    Return None when the follow-up does not belong to the organization.
    Raise ValueError when the follow-up is not pending.
    """
    statement = select(FollowUp).where(
        FollowUp.id == follow_up_id,
        FollowUp.organization_id == organization_id,
    )
    follow_up = db.scalar(statement)

    if follow_up is None:
        return None

    if follow_up.status != FollowUp.STATUS_PENDING:
        raise ValueError("Only pending follow-ups can be rescheduled.")

    follow_up.due_at = payload.due_at

    db.flush()
    db.refresh(follow_up)

    return follow_up

def list_follow_ups(
    db: Session,
    *,
    organization_id: UUID,
    due_before: datetime | None = None,
    overdue_only: bool = False,
) -> list[FollowUp]:
    """List pending follow-ups belonging to the verified tenant."""
    statement = select(FollowUp).where(
        FollowUp.organization_id == organization_id,
        FollowUp.status == FollowUp.STATUS_PENDING,
    )

    if due_before is not None:
        statement = statement.where(
            FollowUp.due_at < due_before,
        )

    if overdue_only:
        statement = statement.where(
            FollowUp.due_at < func.now(),
        )

    statement = statement.order_by(
        FollowUp.due_at.asc(),
        FollowUp.id.asc(),
    )

    return list(db.scalars(statement).all())


def bulk_complete_follow_ups(
    db: Session,
    *,
    organization_id: UUID,
    current_user_id: UUID,
    payload: BulkFollowUpRequest,
) -> list[BulkFollowUpItemResult]:
    """Complete selected pending follow-ups independently."""

    results: list[BulkFollowUpItemResult] = []

    for follow_up_id in payload.follow_up_ids:
        with db.begin_nested():
            statement = select(FollowUp).where(
                FollowUp.id == follow_up_id,
                FollowUp.organization_id == organization_id,
            )
            follow_up = db.scalar(statement)

            if follow_up is None:
                results.append(
                    BulkFollowUpItemResult(
                        follow_up_id=follow_up_id,
                        success=False,
                        message="Follow-up not found.",
                    )
                )
                continue

            if follow_up.status != FollowUp.STATUS_PENDING:
                results.append(
                    BulkFollowUpItemResult(
                        follow_up_id=follow_up_id,
                        success=False,
                        message="Only pending follow-ups can be completed.",
                    )
                )
                continue

            follow_up.status = FollowUp.STATUS_COMPLETED
            follow_up.completed_at = datetime.now(timezone.utc)
            follow_up.completed_by_user_id = current_user_id

            db.flush()
            db.refresh(follow_up)

            results.append(
                BulkFollowUpItemResult(
                    follow_up_id=follow_up_id,
                    success=True,
                    message="Follow-up completed successfully.",
                    follow_up=follow_up,
                )
            )

    return results


def bulk_reschedule_follow_ups(
    db: Session,
    *,
    organization_id: UUID,
    payload: BulkFollowUpRescheduleRequest,
) -> list[BulkFollowUpItemResult]:
    """Reschedule selected pending follow-ups independently."""

    results: list[BulkFollowUpItemResult] = []

    for follow_up_id in payload.follow_up_ids:
        with db.begin_nested():
            statement = select(FollowUp).where(
                FollowUp.id == follow_up_id,
                FollowUp.organization_id == organization_id,
            )
            follow_up = db.scalar(statement)

            if follow_up is None:
                results.append(
                    BulkFollowUpItemResult(
                        follow_up_id=follow_up_id,
                        success=False,
                        message="Follow-up not found.",
                    )
                )
                continue

            if follow_up.status != FollowUp.STATUS_PENDING:
                results.append(
                    BulkFollowUpItemResult(
                        follow_up_id=follow_up_id,
                        success=False,
                        message="Only pending follow-ups can be rescheduled.",
                    )
                )
                continue

            follow_up.due_at = payload.due_at

            db.flush()
            db.refresh(follow_up)

            results.append(
                BulkFollowUpItemResult(
                    follow_up_id=follow_up_id,
                    success=True,
                    message="Follow-up rescheduled successfully.",
                    follow_up=follow_up,
                )
            )

    return results

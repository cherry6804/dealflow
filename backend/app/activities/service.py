"""Activity service-layer operations for DealFlow."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.activities.schemas import ActivityCreateRequest
from app.db.models.activity import Activity
from app.db.models.lead import Lead

def create_activity(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    lead_id: UUID,
    payload: ActivityCreateRequest,
) -> Activity | None:
    """Create an activity for a lead owned by the verified organization."""

    lead_statement = select(Lead.id).where(
        Lead.id == lead_id,
        Lead.organization_id == organization_id,
    )

    if db.scalar(lead_statement) is None:
        return None

    activity_values: dict[str, object] = {
        "organization_id": organization_id,
        "lead_id": lead_id,
        "actor_id": actor_id,
        "activity_type": payload.activity_type,
        "title": payload.title,
        "description": payload.description,
        "details": payload.details,
    }

    if payload.occurred_at is not None:
        activity_values["occurred_at"] = payload.occurred_at

    activity = Activity(**activity_values)

    db.add(activity)
    db.flush()
    db.refresh(activity)

    return activity


def list_lead_activities(
    db: Session,
    *,
    organization_id: UUID,
    lead_id: UUID,
) -> list[Activity] | None:
    """Return a lead's activities in deterministic timeline order."""

    lead_statement = select(Lead.id).where(
        Lead.id == lead_id,
        Lead.organization_id == organization_id,
    )

    if db.scalar(lead_statement) is None:
        return None

    activity_statement = (
        select(Activity)
        .where(
            Activity.organization_id == organization_id,
            Activity.lead_id == lead_id,
        )
        .order_by(
            Activity.occurred_at.asc(),
            Activity.id.asc(),
        )
    )

    return list(db.scalars(activity_statement).all())

def list_recent_activities(
    db: Session,
    *,
    organization_id: UUID,
    limit: int = 10,
) -> list[Activity]:
    """Return the most recent activities for one organization."""

    activity_statement = (
        select(Activity)
        .where(Activity.organization_id == organization_id)
        .options(joinedload(Activity.actor))
        .order_by(
            Activity.occurred_at.desc(),
            Activity.id.desc(),
        )
        .limit(limit)
    )

    return list(db.scalars(activity_statement).all())
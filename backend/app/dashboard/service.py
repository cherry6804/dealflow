"""Bounded, tenant-scoped aggregates for the Today dashboard.

Every query filters by the verified organization and joins related rows only
within that organization. Lists are capped at LIST_LIMIT items per bucket, and
counts come from the database, so the response size does not grow with data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.dashboard.schemas import (
    DealSummary,
    FollowUpItem,
    FollowUpSummary,
    LeadActionItem,
    LeadActionSummary,
    PipelineValue,
)
from app.db.models.contact import Contact
from app.db.models.deal import Deal
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead

LIST_LIMIT = 10
OPEN_DEAL_STAGES = ("NEW", "QUALIFICATION", "NEGOTIATION", "BOOKING")
ALL_DEAL_STAGES = (*OPEN_DEAL_STAGES, "CLOSED_WON", "CLOSED_LOST")
CLOSED_LEAD_STATUSES = (Lead.STATUS_WON, Lead.STATUS_LOST)


def deal_pipeline_summary(db: Session, *, organization_id: UUID) -> DealSummary:
    """Count deals per stage and total expected value of open deals per currency."""
    stage_rows = db.execute(
        select(Deal.stage, func.count())
        .where(Deal.organization_id == organization_id)
        .group_by(Deal.stage)
    ).all()
    by_stage = {stage: 0 for stage in ALL_DEAL_STAGES}
    for stage, count in stage_rows:
        if stage in by_stage:
            by_stage[stage] = count

    value_rows = db.execute(
        select(Deal.currency, func.sum(Deal.expected_value))
        .where(
            Deal.organization_id == organization_id,
            Deal.stage.in_(OPEN_DEAL_STAGES),
            Deal.expected_value.isnot(None),
        )
        .group_by(Deal.currency)
        .order_by(Deal.currency)
    ).all()

    return DealSummary(
        by_stage=by_stage,
        open_value_by_currency=[
            PipelineValue(currency=currency, total=f"{Decimal(total):.2f}")
            for currency, total in value_rows
        ],
    )


def _contact_name(first_name: str | None, last_name: str | None) -> str:
    return " ".join(part for part in (first_name, last_name) if part) or "Contact unavailable"


def follow_up_summary(
    db: Session,
    *,
    organization_id: UUID,
    day_start: datetime,
    day_end: datetime,
) -> FollowUpSummary:
    """Bucket pending follow-ups into overdue, today and upcoming."""
    overdue = FollowUp.due_at < day_start
    today = and_(FollowUp.due_at >= day_start, FollowUp.due_at < day_end)
    upcoming = FollowUp.due_at >= day_end

    scope = (
        FollowUp.organization_id == organization_id,
        FollowUp.status == FollowUp.STATUS_PENDING,
        Lead.is_active.is_(True),
        Lead.status.not_in(CLOSED_LEAD_STATUSES),
    )

    def scoped_query(*columns):
        return (
            select(*columns)
            .select_from(FollowUp)
            .join(
                Lead,
                and_(
                    Lead.id == FollowUp.lead_id,
                    Lead.organization_id == FollowUp.organization_id,
                ),
            )
            .join(
                Contact,
                and_(
                    Contact.id == Lead.contact_id,
                    Contact.organization_id == Lead.organization_id,
                ),
            )
        )

    counts = db.execute(
        scoped_query(
            func.count().filter(overdue),
            func.count().filter(today),
            func.count().filter(upcoming),
        ).where(*scope)
    ).one()

    item_columns = (
        FollowUp.id,
        FollowUp.title,
        FollowUp.follow_up_type,
        FollowUp.due_at,
        FollowUp.lead_id,
        Contact.first_name,
        Contact.last_name,
        Lead.interest,
    )

    def items_for(bucket):
        rows = db.execute(
            scoped_query(*item_columns)
            .where(*scope, bucket)
            .order_by(FollowUp.due_at.asc(), FollowUp.id.asc())
            .limit(LIST_LIMIT)
        ).all()
        return [
            FollowUpItem(
                id=row.id,
                title=row.title,
                follow_up_type=row.follow_up_type,
                due_at=row.due_at,
                lead_id=row.lead_id,
                contact_name=_contact_name(row.first_name, row.last_name),
                interest=row.interest,
            )
            for row in rows
        ]

    return FollowUpSummary(
        overdue_count=counts[0],
        today_count=counts[1],
        upcoming_count=counts[2],
        overdue=items_for(overdue),
        today=items_for(today),
        upcoming=items_for(upcoming),
    )


def lead_action_summary(
    db: Session,
    *,
    organization_id: UUID,
    day_start: datetime,
    day_end: datetime,
) -> LeadActionSummary:
    """Bucket active leads' next actions into overdue and today."""
    overdue = Lead.next_action_at < day_start
    today = and_(Lead.next_action_at >= day_start, Lead.next_action_at < day_end)

    scope = (
        Lead.organization_id == organization_id,
        Lead.is_active.is_(True),
        Lead.status.not_in(CLOSED_LEAD_STATUSES),
        Lead.next_action_at.isnot(None),
        func.length(func.trim(Lead.next_action)) > 0,
    )

    def scoped_query(*columns):
        return (
            select(*columns)
            .select_from(Lead)
            .join(
                Contact,
                and_(
                    Contact.id == Lead.contact_id,
                    Contact.organization_id == Lead.organization_id,
                ),
            )
        )

    counts = db.execute(
        scoped_query(
            func.count().filter(overdue),
            func.count().filter(today),
        ).where(*scope)
    ).one()

    item_columns = (
        Lead.id,
        Lead.next_action,
        Lead.next_action_at,
        Lead.status,
        Lead.interest,
        Contact.first_name,
        Contact.last_name,
    )

    def items_for(bucket):
        rows = db.execute(
            scoped_query(*item_columns)
            .where(*scope, bucket)
            .order_by(Lead.next_action_at.asc(), Lead.id.asc())
            .limit(LIST_LIMIT)
        ).all()
        return [
            LeadActionItem(
                lead_id=row.id,
                contact_name=_contact_name(row.first_name, row.last_name),
                action=row.next_action,
                due_at=row.next_action_at,
                status=row.status,
                interest=row.interest,
            )
            for row in rows
        ]

    return LeadActionSummary(
        overdue_count=counts[0],
        today_count=counts[1],
        overdue=items_for(overdue),
        today=items_for(today),
    )

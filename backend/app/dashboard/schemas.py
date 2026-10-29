"""Response schemas for the Today dashboard summary."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class PipelineValue(BaseModel):
    """Expected value of open deals in one currency."""

    currency: str
    total: str


class DealSummary(BaseModel):
    """Deal counts by stage, and the value of open deals by currency."""

    by_stage: dict[str, int]
    open_value_by_currency: list[PipelineValue]


class FollowUpItem(BaseModel):
    """A pending follow-up on an active, open lead."""

    id: UUID
    title: str
    follow_up_type: str
    due_at: datetime
    lead_id: UUID
    contact_name: str
    interest: str | None


class FollowUpSummary(BaseModel):
    """Pending follow-ups bucketed against the requested day."""

    overdue_count: int
    today_count: int
    upcoming_count: int
    overdue: list[FollowUpItem]
    today: list[FollowUpItem]
    upcoming: list[FollowUpItem]


class LeadActionItem(BaseModel):
    """A lead's next action that is due on or before the requested day."""

    lead_id: UUID
    contact_name: str
    action: str
    due_at: datetime
    status: str
    interest: str | None


class LeadActionSummary(BaseModel):
    """Lead next actions bucketed against the requested day."""

    overdue_count: int
    today_count: int
    overdue: list[LeadActionItem]
    today: list[LeadActionItem]


class DashboardAccess(BaseModel):
    """Which dashboard sections the caller may see."""

    deals: bool
    follow_ups: bool
    lead_actions: bool


class DashboardSummaryResponse(BaseModel):
    """Tenant-scoped dashboard data. Denied sections are null."""

    day_start: datetime
    day_end: datetime
    access: DashboardAccess
    deals: DealSummary | None
    follow_ups: FollowUpSummary | None
    lead_actions: LeadActionSummary | None

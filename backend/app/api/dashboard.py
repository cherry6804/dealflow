"""Dashboard summary endpoint for the Today view."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.authz.dependencies import permission_granted
from app.dashboard.schemas import DashboardAccess, DashboardSummaryResponse
from app.dashboard.service import (
    deal_pipeline_summary,
    follow_up_summary,
    lead_action_summary,
)
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext, get_tenant_context

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

MAX_WINDOW = timedelta(days=2)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{name} must include a timezone.",
        )


@router.get("/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    day_start: datetime = Query(...),
    day_end: datetime = Query(...),
    tenant_context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db_session),
) -> DashboardSummaryResponse:
    """Summarize deals, follow-ups and lead actions for the verified organization.

    The client passes the start and end of its local day. Each section is
    returned only when the caller holds the permission behind it.
    """
    _require_aware(day_start, "day_start")
    _require_aware(day_end, "day_end")
    if day_end <= day_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="day_end must be after day_start.",
        )
    if day_end - day_start > MAX_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The dashboard window cannot exceed two days.",
        )

    organization_id = tenant_context.organization_id
    can_read_deals = permission_granted(
        db, tenant_context=tenant_context, permission_key="deals.read"
    )
    can_read_leads = permission_granted(
        db, tenant_context=tenant_context, permission_key="leads.read"
    )

    return DashboardSummaryResponse(
        day_start=day_start,
        day_end=day_end,
        access=DashboardAccess(
            deals=can_read_deals,
            follow_ups=can_read_leads,
            lead_actions=can_read_leads,
        ),
        deals=(
            deal_pipeline_summary(db, organization_id=organization_id)
            if can_read_deals
            else None
        ),
        follow_ups=(
            follow_up_summary(
                db,
                organization_id=organization_id,
                day_start=day_start,
                day_end=day_end,
            )
            if can_read_leads
            else None
        ),
        lead_actions=(
            lead_action_summary(
                db,
                organization_id=organization_id,
                day_start=day_start,
                day_end=day_end,
            )
            if can_read_leads
            else None
        ),
    )

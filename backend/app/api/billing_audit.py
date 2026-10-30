
"""Tenant-protected billing reconciliation audit API."""

from __future__ import annotations
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.models.billing_reconciliation_record import (
    BillingReconciliationRecord,
)
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext

router = APIRouter(
    prefix="/api/v1/billing/audit/reconciliations",
    tags=["billing-audit"],
)


class ReconciliationRecordResponse(BaseModel):
    """Public representation of a reconciliation audit record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    webhook_event_id: UUID
    organization_id: UUID | None
    status: str
    summary: str
    details: dict
    reconciled_at: datetime
    created_at: datetime


class ReconciliationRecordListResponse(BaseModel):
    """Paginated reconciliation audit records."""

    items: list[ReconciliationRecordResponse]
    limit: int
    offset: int


@router.get(
    "",
    response_model=ReconciliationRecordListResponse,
)
def get_reconciliation_records(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(
        require_permission("billing.audit.read")
    ),
    db: Session = Depends(get_db_session),
) -> ReconciliationRecordListResponse:
    """List reconciliation records for the authenticated organization."""
    records = db.query(BillingReconciliationRecord).filter(
        BillingReconciliationRecord.organization_id == tenant.organization_id
    ).order_by(
        BillingReconciliationRecord.created_at.desc(),
        BillingReconciliationRecord.id.desc(),
    ).limit(limit).offset(offset).all()

    return ReconciliationRecordListResponse(
        items=[
            ReconciliationRecordResponse.model_validate(record)
            for record in records
        ],
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{record_id}",
    response_model=ReconciliationRecordResponse,
)
def get_reconciliation_record(
    record_id: UUID,
    tenant: TenantContext = Depends(
        require_permission("billing.audit.read")
    ),
    db: Session = Depends(get_db_session),
) -> ReconciliationRecordResponse:
    """Get one reconciliation record within the authenticated organization."""
    record = db.query(BillingReconciliationRecord).filter(
        BillingReconciliationRecord.id == record_id,
        BillingReconciliationRecord.organization_id == tenant.organization_id,
    ).first()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Billing reconciliation record not found.",
        )

    return ReconciliationRecordResponse.model_validate(record)

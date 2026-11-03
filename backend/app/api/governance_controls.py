"""Approvals, channel policy and contact do-not-disturb API (DFR1-006).

Permissions: ``governance.approvals.request`` to ask and to list, ``governance.approvals.decide`` to approve or
reject, ``governance.channels.read`` to view and ``governance.channels.manage`` to change channel settings.
Every route is organization-scoped through the tenant context.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.dependencies import require_permission
from app.db.models.approval_request import ApprovalRequest
from app.db.models.channel_policy import ChannelPolicy
from app.db.session import get_db_session
from app.governance.approvals import (
    REASON_APPROVAL_EXPIRED,
    REASON_APPROVAL_NOT_FOUND,
    ApprovalError,
    ApprovalInvalidError,
    decide_approval,
    list_approvals,
    request_approval,
)
from app.governance.channel_policy import (
    ChannelPolicyError,
    ChannelPolicyInput,
    set_channel_policy,
    set_contact_do_not_disturb,
)
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])

ChannelName = Literal["whatsapp", "email", "sms", "voice"]


class ApprovalCreate(BaseModel):
    capability_key: str = Field(..., min_length=1, max_length=64)
    resource_type: str = Field(..., min_length=1, max_length=64)
    resource_id: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, object]
    expires_in_seconds: int = Field(..., ge=60, le=604800)


class ApprovalDecision(BaseModel):
    approve: bool


class ApprovalResponse(BaseModel):
    id: UUID
    capability_key: str
    resource_type: str
    resource_id: str
    payload_hash: str
    status: str
    requested_by_user_id: UUID
    requested_at: datetime
    expires_at: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    consumed_at: datetime | None


def _approval_response(row: ApprovalRequest) -> ApprovalResponse:
    return ApprovalResponse(
        id=row.id,
        capability_key=row.capability_key,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        payload_hash=row.payload_hash,
        status=row.status,
        requested_by_user_id=row.requested_by_user_id,
        requested_at=row.requested_at,
        expires_at=row.expires_at,
        decided_by_user_id=row.decided_by_user_id,
        decided_at=row.decided_at,
        consumed_at=row.consumed_at,
    )


@router.post("/approvals", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
def create_approval(
    payload: ApprovalCreate,
    tenant: TenantContext = Depends(require_permission("governance.approvals.request")),
    db: Session = Depends(get_db_session),
) -> ApprovalResponse:
    try:
        row = request_approval(
            db,
            organization_id=tenant.organization_id,
            requester_user_id=tenant.membership.user_id,
            capability_key=payload.capability_key,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            payload=payload.payload,
            ttl=timedelta(seconds=payload.expires_in_seconds),
        )
    except ApprovalInvalidError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from None
    db.commit()
    return _approval_response(row)


@router.get("/approvals", response_model=list[ApprovalResponse])
def list_approval_requests(
    tenant: TenantContext = Depends(require_permission("governance.approvals.request")),
    db: Session = Depends(get_db_session),
) -> list[ApprovalResponse]:
    return [_approval_response(row) for row in list_approvals(db, organization_id=tenant.organization_id)]


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalResponse)
def decide_approval_request(
    approval_id: UUID,
    payload: ApprovalDecision,
    tenant: TenantContext = Depends(require_permission("governance.approvals.decide")),
    db: Session = Depends(get_db_session),
) -> ApprovalResponse:
    try:
        row = decide_approval(
            db,
            organization_id=tenant.organization_id,
            approver_user_id=tenant.membership.user_id,
            approval_id=approval_id,
            approve=payload.approve,
        )
    except ApprovalError as error:
        # An expiry is recorded even though the decision is refused, so it must persist.
        if error.reason_code == REASON_APPROVAL_EXPIRED:
            db.commit()
        else:
            db.rollback()
        code = status.HTTP_404_NOT_FOUND if error.reason_code == REASON_APPROVAL_NOT_FOUND else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=error.reason_code) from None
    db.commit()
    return _approval_response(row)


class ChannelPolicyBody(BaseModel):
    is_enabled: bool
    timezone: str = Field(..., min_length=1, max_length=64)
    messaging_days: int = Field(..., ge=0, le=127)
    messaging_start: time | None = None
    messaging_end: time | None = None
    quiet_start: time | None = None
    quiet_end: time | None = None


class ChannelPolicyResponse(ChannelPolicyBody):
    channel: ChannelName
    updated_at: datetime


def _policy_response(row: ChannelPolicy) -> ChannelPolicyResponse:
    return ChannelPolicyResponse(
        channel=row.channel,
        is_enabled=row.is_enabled,
        timezone=row.timezone,
        messaging_days=row.messaging_days,
        messaging_start=row.messaging_start,
        messaging_end=row.messaging_end,
        quiet_start=row.quiet_start,
        quiet_end=row.quiet_end,
        updated_at=row.updated_at,
    )


@router.get("/channel-policies", response_model=list[ChannelPolicyResponse])
def list_channel_policies(
    tenant: TenantContext = Depends(require_permission("governance.channels.read")),
    db: Session = Depends(get_db_session),
) -> list[ChannelPolicyResponse]:
    rows = db.scalars(
        select(ChannelPolicy)
        .where(ChannelPolicy.organization_id == tenant.organization_id)
        .order_by(ChannelPolicy.channel)
    ).all()
    return [_policy_response(row) for row in rows]


@router.put("/channel-policies/{channel}", response_model=ChannelPolicyResponse)
def put_channel_policy(
    channel: ChannelName,
    body: ChannelPolicyBody,
    tenant: TenantContext = Depends(require_permission("governance.channels.manage")),
    db: Session = Depends(get_db_session),
) -> ChannelPolicyResponse:
    policy = ChannelPolicyInput(
        channel=channel,
        is_enabled=body.is_enabled,
        timezone=body.timezone,
        messaging_days=body.messaging_days,
        messaging_start=body.messaging_start,
        messaging_end=body.messaging_end,
        quiet_start=body.quiet_start,
        quiet_end=body.quiet_end,
    )
    try:
        row = set_channel_policy(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            policy=policy,
        )
    except ChannelPolicyError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from None
    db.commit()
    return _policy_response(row)


class DoNotDisturbBody(BaseModel):
    enabled: bool


@router.put("/contacts/{contact_id}/do-not-disturb", response_model=DoNotDisturbBody)
def put_contact_do_not_disturb(
    contact_id: UUID,
    body: DoNotDisturbBody,
    tenant: TenantContext = Depends(require_permission("governance.channels.manage")),
    db: Session = Depends(get_db_session),
) -> DoNotDisturbBody:
    try:
        enabled = set_contact_do_not_disturb(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            contact_id=contact_id,
            enabled=body.enabled,
        )
    except ChannelPolicyError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
    db.commit()
    return DoNotDisturbBody(enabled=enabled)

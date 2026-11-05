"""Verified inbound webhooks over HTTP (DFR1-012).

Receiving: ``POST /api/v1/webhooks/inbound/{endpoint_id}``. This route has no user session. Its trust comes from the endpoint's
signature, which is verified before anything else is read. The response never says which organization the endpoint belongs to.

Administration: ``/api/v1/webhook-endpoints``. Creating, rotating and disabling an endpoint need ``webhook_endpoints.manage``, which is
granted to the system Owner role only. A signing secret is returned once, when it is created or rotated, and is never returned again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.config import get_settings
from app.db.models.inbound_webhook import InboundWebhookEndpoint
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext
from app.webhooks.envelope import MAX_BODY_BYTES
from app.webhooks.service import (
    PERMISSION,
    WebhookError,
    create_endpoint,
    disable_endpoint,
    ingest,
    list_endpoints,
    rotate_secret,
)

receiver_router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])
admin_router = APIRouter(prefix="/api/v1/webhook-endpoints", tags=["webhooks"])


class EndpointCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    provider_key: str = Field(min_length=2, max_length=40)
    verifier_key: str = Field(min_length=1, max_length=40)
    provider_connection_id: UUID | None = None


def _raise(error: WebhookError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _endpoint_body(row: InboundWebhookEndpoint) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "label": row.label,
        "provider_key": row.provider_key,
        "verifier_key": row.verifier_key,
        "status": row.status,
        "provider_connection_id": str(row.provider_connection_id)
        if row.provider_connection_id
        else None,
        "secret_version": row.secret_version,
        "rotated_at": row.rotated_at.isoformat() if row.rotated_at else None,
        "disabled_at": row.disabled_at.isoformat() if row.disabled_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@receiver_router.post("/inbound/{endpoint_id}")
async def receive_endpoint(
    endpoint_id: UUID, request: Request, db: Session = Depends(get_db_session)
) -> JSONResponse:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"status": "rejected", "reason": "body_size"},
        )
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"status": "rejected", "reason": "body_size"},
        )
    try:
        result = ingest(
            db,
            endpoint_id=endpoint_id,
            timestamp_header=request.headers.get("x-dealsflo-timestamp"),
            signature_header=request.headers.get("x-dealsflo-signature"),
            body=body,
            now=datetime.now(UTC),
            replay_window_seconds=get_settings().inbound_webhook_replay_window_seconds,
        )
    except SQLAlchemyError:
        # A database failure before commit writes nothing. The sender receives a retryable status.
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "failed", "reason": "temporarily_unavailable"},
        )
    return JSONResponse(status_code=result.status_code, content=result.body)


@admin_router.get("")
def list_endpoints_route(
    tenant: TenantContext = Depends(require_permission(PERMISSION)),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        rows = list_endpoints(
            db, organization_id=tenant.organization_id, actor_id=user_context.user.id
        )
    except WebhookError as error:
        _raise(error)
    return {"items": [_endpoint_body(row) for row in rows]}


@admin_router.post("", status_code=status.HTTP_201_CREATED)
def create_endpoint_route(
    payload: EndpointCreateRequest,
    tenant: TenantContext = Depends(require_permission(PERMISSION)),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row, secret = create_endpoint(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            label=payload.label,
            provider_key=payload.provider_key,
            verifier_key=payload.verifier_key,
            provider_connection_id=payload.provider_connection_id,
        )
        db.commit()
    except WebhookError as error:
        db.rollback()
        _raise(error)
    return dict(_endpoint_body(row), signing_secret=secret, secret_shown_once=True)


@admin_router.post("/{endpoint_id}/rotate")
def rotate_route(
    endpoint_id: UUID,
    tenant: TenantContext = Depends(require_permission(PERMISSION)),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row, secret = rotate_secret(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            endpoint_id=endpoint_id,
        )
        db.commit()
    except WebhookError as error:
        db.rollback()
        _raise(error)
    return dict(_endpoint_body(row), signing_secret=secret, secret_shown_once=True)


@admin_router.post("/{endpoint_id}/disable")
def disable_route(
    endpoint_id: UUID,
    tenant: TenantContext = Depends(require_permission(PERMISSION)),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = disable_endpoint(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            endpoint_id=endpoint_id,
        )
        db.commit()
    except WebhookError as error:
        db.rollback()
        _raise(error)
    return _endpoint_body(row)


__all__ = ["admin_router", "receiver_router"]

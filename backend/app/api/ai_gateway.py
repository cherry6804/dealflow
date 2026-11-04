"""Organization AI task routes: which provider and model each task uses (DFR1-015).

Reading requires ``governance.capabilities.read``. Changing a route requires ``governance.capabilities.manage``, which is
owner-only, so only the Owner can choose a provider or model. The API never accepts or returns a credential.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_gateway.routing import InvalidRouteError, set_route
from app.ai_gateway.tasks import TaskType
from app.authz.dependencies import require_permission
from app.db.models.ai_task_route import AiTaskRoute
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/ai/gateway", tags=["ai-gateway"])


class AiTaskRouteRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=120)
    # Optional fallback, given as a pair or not at all. Checked in the route writer.
    fallback_provider_key: str | None = Field(default=None, min_length=1, max_length=40)
    fallback_model: str | None = Field(default=None, min_length=1, max_length=120)


class AiTaskRouteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task: str
    provider_key: str
    model: str
    fallback_provider_key: str | None = None
    fallback_model: str | None = None
    updated_at: datetime


class AiTaskRouteListResponse(BaseModel):
    items: list[AiTaskRouteResponse]


@router.get("/routes", response_model=AiTaskRouteListResponse)
def list_routes(
    tenant: TenantContext = Depends(require_permission("governance.capabilities.read")),
    db: Session = Depends(get_db_session),
) -> AiTaskRouteListResponse:
    rows = db.scalars(
        select(AiTaskRoute)
        .where(AiTaskRoute.organization_id == tenant.organization_id)
        .order_by(AiTaskRoute.task)
    ).all()
    return AiTaskRouteListResponse(items=[AiTaskRouteResponse.model_validate(row) for row in rows])


@router.put("/routes/{task}", response_model=AiTaskRouteResponse)
def put_route(
    task: TaskType,
    body: AiTaskRouteRequest,
    tenant: TenantContext = Depends(require_permission("governance.capabilities.manage")),
    db: Session = Depends(get_db_session),
) -> AiTaskRouteResponse:
    try:
        row = set_route(
            db,
            organization_id=tenant.organization_id,
            actor_user_id=tenant.membership.user_id,
            task=task,
            provider_key=body.provider_key,
            model=body.model,
            fallback_provider_key=body.fallback_provider_key,
            fallback_model=body.fallback_model,
        )
    except InvalidRouteError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    db.commit()
    db.refresh(row)
    return AiTaskRouteResponse.model_validate(row)

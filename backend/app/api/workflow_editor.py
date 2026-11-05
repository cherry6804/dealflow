"""Workflow editor helpers over HTTP: the template catalogue, creating a draft from a template, and dry-run simulation (DFR1-026).

The catalogue needs ``workflows.read``. Creating a draft from a template and simulating a draft need ``workflows.manage``. Nothing here
publishes, runs or sends anything: a template creates a draft, and a simulation describes a draft. Every route is scoped to the
verified organization, and the request models refuse unknown fields.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext
from app.workflows.editor_service import create_from_template, simulate_draft
from app.workflows.service import WorkflowError
from app.workflows.templates import catalogue, template_summaries

router = APIRouter(prefix="/api/v1/automation", tags=["workflow-editor"])


class CreateFromTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any] = Field(default_factory=dict, max_length=20)


def _raise(error: WorkflowError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


@router.get("/workflow-templates")
def list_templates(
    _tenant: TenantContext = Depends(require_permission("workflows.read")),
) -> dict[str, Any]:
    return {"items": template_summaries(), "catalogue": catalogue()}


@router.post(
    "/workflow-templates/{template_key}/workflows", status_code=status.HTTP_201_CREATED
)
def create_from_template_endpoint(
    template_key: str,
    payload: CreateFromTemplateRequest,
    tenant: TenantContext = Depends(require_permission("workflows.manage")),
    db: Session = Depends(get_db_session),
    user_context: CurrentUserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    try:
        workflow = create_from_template(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            template_key=template_key,
            name=payload.name,
            description=payload.description,
        )
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "status": workflow.status,
        "revision": workflow.draft_revision,
    }


@router.post("/workflows/{workflow_id}/simulate")
def simulate_endpoint(
    workflow_id: UUID,
    payload: SimulateRequest,
    tenant: TenantContext = Depends(require_permission("workflows.manage")),
    db: Session = Depends(get_db_session),
    user_context: CurrentUserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    """Describe what the draft would do for the sample input. Nothing runs, is sent, is called or is written to the customer data."""
    try:
        result = simulate_draft(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            workflow_id=workflow_id,
            inputs=payload.input,
        )
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    return result


__all__ = ["router"]

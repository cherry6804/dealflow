"""Agent definitions, lifecycle, executions and approvals over HTTP (DFR1-019).

Every route is tenant-scoped by the verified organization and checks one permission. Errors name a stable reason and, for
validation, the problems found. They never echo a stored value, a document's content or a credential.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.runtime import cancel_execution, create_execution, decide_approval
from app.agents.service import (
    AgentError,
    archive,
    create_agent,
    get_agent,
    list_agents,
    list_versions,
    load_version,
    pause,
    preview,
    publish,
    resume,
    rollback,
    update_draft,
)
from app.ai_tools.registry import DEFAULT_REGISTRY
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.models.agent import Agent, AgentExecution, AgentExecutionStep, AgentVersion
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentCreateRequest(_Strict):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    configuration: dict[str, Any] = Field(default_factory=dict)
    owner_user_id: UUID | None = None


class AgentUpdateRequest(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    configuration: dict[str, Any] | None = None


class RollbackRequest(_Strict):
    version_number: int = Field(ge=1)


class ExecutionCreateRequest(_Strict):
    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=120)


class ApprovalDecisionRequest(_Strict):
    approve: bool


def _raise(error: AgentError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _agent_body(agent: Agent, version: AgentVersion | None) -> dict[str, Any]:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "description": agent.description,
        "status": agent.status,
        "owner_user_id": str(agent.owner_user_id),
        "created_by_user_id": str(agent.created_by_user_id),
        "current_version_number": version.version_number if version else None,
        "draft_configuration": agent.draft_configuration,
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
    }


def _version_body(version: AgentVersion) -> dict[str, Any]:
    return {
        "id": str(version.id),
        "version_number": version.version_number,
        "configuration": version.configuration,
        "validation_snapshot": version.validation_snapshot,
        "published_by_user_id": str(version.published_by_user_id),
        "published_at": version.published_at.isoformat(),
    }


def _execution_body(execution: AgentExecution, steps: list[AgentExecutionStep] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(execution.id),
        "agent_id": str(execution.agent_id),
        "agent_version_id": str(execution.agent_version_id),
        "status": execution.status,
        "failure_reason": execution.failure_reason,
        "initiated_by_user_id": str(execution.initiated_by_user_id),
        "correlation_id": execution.correlation_id,
        "steps_completed": execution.steps_completed,
        "tool_calls": execution.tool_calls,
        "model_calls": execution.model_calls,
        "output": execution.output,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
        "deadline_at": execution.deadline_at.isoformat() if execution.deadline_at else None,
        "cancel_requested": execution.cancel_requested_at is not None,
        "created_at": execution.created_at.isoformat(),
    }
    if steps is not None:
        body["steps"] = [
            {
                "index": step.step_index,
                "kind": step.kind,
                "status": step.status,
                "reason_code": step.reason_code,
                "attempts": step.attempts,
                "trace": step.trace,
                "started_at": step.started_at.isoformat(),
                "finished_at": step.finished_at.isoformat() if step.finished_at else None,
            }
            for step in steps
        ]
    return body


def _current_version(db: Session, tenant: TenantContext, agent: Agent) -> AgentVersion | None:
    return load_version(db, organization_id=tenant.organization_id, agent=agent)


@router.get("/tools")
def list_approved_tools(tenant: TenantContext = Depends(require_permission("agents.read"))) -> dict[str, Any]:
    """The tools an agent may be assigned. These are the typed registry's approved tools, nothing else."""
    registered = DEFAULT_REGISTRY.keys()
    items = []
    for key in registered:
        definition = DEFAULT_REGISTRY.get(key)
        assert definition is not None
        items.append({
            "key": key,
            "description": definition.description,
            "required_permission": definition.required_permission,
            "parameters": [{"name": p.name, "type": p.type.value, "required": p.required} for p in definition.parameters],
        })
    return {"items": items}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_agent_endpoint(
    payload: AgentCreateRequest,
    tenant: TenantContext = Depends(require_permission("agents.manage")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        agent = create_agent(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            name=payload.name,
            description=payload.description,
            configuration=payload.configuration,
            owner_user_id=payload.owner_user_id,
        )
        db.commit()
    except AgentError as error:
        db.rollback()
        _raise(error)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail={"reason": "agent_name_taken"}) from error
    return _agent_body(agent, None)


@router.get("")
def list_agents_endpoint(
    tenant: TenantContext = Depends(require_permission("agents.read")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    items = []
    for agent in list_agents(db, organization_id=tenant.organization_id):
        items.append(_agent_body(agent, _current_version(db, tenant, agent)))
    return {"items": items}


@router.get("/{agent_id}")
def get_agent_endpoint(
    agent_id: UUID,
    tenant: TenantContext = Depends(require_permission("agents.read")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        agent = get_agent(db, organization_id=tenant.organization_id, agent_id=agent_id)
    except AgentError as error:
        _raise(error)
    return _agent_body(agent, _current_version(db, tenant, agent))


@router.patch("/{agent_id}")
def update_agent_endpoint(
    agent_id: UUID,
    payload: AgentUpdateRequest,
    tenant: TenantContext = Depends(require_permission("agents.manage")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        agent = update_draft(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            agent_id=agent_id,
            name=payload.name,
            description=payload.description,
            configuration=payload.configuration,
        )
        db.commit()
    except AgentError as error:
        db.rollback()
        _raise(error)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail={"reason": "agent_name_taken"}) from error
    return _agent_body(agent, _current_version(db, tenant, agent))


@router.post("/{agent_id}/preview")
def preview_agent_endpoint(
    agent_id: UUID,
    tenant: TenantContext = Depends(require_permission("agents.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Describe the draft and whether it could be published now. No tool, model or provider is called."""
    try:
        result = preview(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, agent_id=agent_id)
        db.commit()
    except AgentError as error:
        db.rollback()
        _raise(error)
    return result


@router.post("/{agent_id}/publish", status_code=status.HTTP_201_CREATED)
def publish_agent_endpoint(
    agent_id: UUID,
    tenant: TenantContext = Depends(require_permission("agents.publish")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        version = publish(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, agent_id=agent_id)
        db.commit()
    except AgentError as error:
        db.rollback()
        _raise(error)
    return _version_body(version)


def _transition(db: Session, tenant: TenantContext, user_context: CurrentUserContext, action, agent_id: UUID) -> dict[str, Any]:
    try:
        agent = action(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, agent_id=agent_id)
        db.commit()
    except AgentError as error:
        db.rollback()
        _raise(error)
    return _agent_body(agent, _current_version(db, tenant, agent))


@router.post("/{agent_id}/pause")
def pause_agent_endpoint(agent_id: UUID, tenant: TenantContext = Depends(require_permission("agents.publish")),
                         user_context: CurrentUserContext = Depends(get_current_user_context),
                         db: Session = Depends(get_db_session)) -> dict[str, Any]:
    return _transition(db, tenant, user_context, pause, agent_id)


@router.post("/{agent_id}/resume")
def resume_agent_endpoint(agent_id: UUID, tenant: TenantContext = Depends(require_permission("agents.publish")),
                          user_context: CurrentUserContext = Depends(get_current_user_context),
                          db: Session = Depends(get_db_session)) -> dict[str, Any]:
    return _transition(db, tenant, user_context, resume, agent_id)


@router.post("/{agent_id}/archive")
def archive_agent_endpoint(agent_id: UUID, tenant: TenantContext = Depends(require_permission("agents.publish")),
                           user_context: CurrentUserContext = Depends(get_current_user_context),
                           db: Session = Depends(get_db_session)) -> dict[str, Any]:
    return _transition(db, tenant, user_context, archive, agent_id)


@router.post("/{agent_id}/rollback")
def rollback_agent_endpoint(
    agent_id: UUID,
    payload: RollbackRequest,
    tenant: TenantContext = Depends(require_permission("agents.publish")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        agent = rollback(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                         agent_id=agent_id, version_number=payload.version_number)
        db.commit()
    except AgentError as error:
        db.rollback()
        _raise(error)
    return _agent_body(agent, _current_version(db, tenant, agent))


@router.get("/{agent_id}/versions")
def list_versions_endpoint(
    agent_id: UUID,
    tenant: TenantContext = Depends(require_permission("agents.read")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        versions = list_versions(db, organization_id=tenant.organization_id, agent_id=agent_id)
    except AgentError as error:
        _raise(error)
    return {"items": [_version_body(version) for version in versions]}


@router.post("/{agent_id}/executions", status_code=status.HTTP_202_ACCEPTED)
def create_execution_endpoint(
    agent_id: UUID,
    payload: ExecutionCreateRequest,
    tenant: TenantContext = Depends(require_permission("agents.run")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Queue one execution. A repeated request with the same key and input returns the stored execution, not a new run."""
    try:
        execution, created = create_execution(
            db,
            organization_id=tenant.organization_id,
            agent_id=agent_id,
            user_context=user_context,
            input_values=payload.input,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
    except AgentError as error:
        db.rollback()
        _raise(error)
    body = _execution_body(execution)
    body["created"] = created
    return body


@router.get("/{agent_id}/executions")
def list_executions_endpoint(
    agent_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    tenant: TenantContext = Depends(require_permission("agents.read")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        get_agent(db, organization_id=tenant.organization_id, agent_id=agent_id)
    except AgentError as error:
        _raise(error)
    from sqlalchemy import select

    rows = db.scalars(
        select(AgentExecution)
        .where(AgentExecution.organization_id == tenant.organization_id, AgentExecution.agent_id == agent_id)
        .order_by(AgentExecution.created_at.desc())
        .limit(limit)
    ).all()
    return {"items": [_execution_body(row) for row in rows]}


@router.get("/executions/{execution_id}")
def get_execution_endpoint(
    execution_id: UUID,
    tenant: TenantContext = Depends(require_permission("agents.read")),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    from sqlalchemy import select

    execution = db.scalar(select(AgentExecution).where(
        AgentExecution.id == execution_id, AgentExecution.organization_id == tenant.organization_id))
    if execution is None:
        raise HTTPException(status_code=404, detail={"reason": "execution_not_found"})
    steps = list(db.scalars(select(AgentExecutionStep).where(
        AgentExecutionStep.execution_id == execution.id).order_by(AgentExecutionStep.step_index)).all())
    return _execution_body(execution, steps)


@router.post("/executions/{execution_id}/cancel")
def cancel_execution_endpoint(
    execution_id: UUID,
    tenant: TenantContext = Depends(require_permission("agents.run")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        execution = cancel_execution(db, organization_id=tenant.organization_id, execution_id=execution_id,
                                     user_context=user_context)
        db.commit()
    except AgentError as error:
        db.rollback()
        _raise(error)
    return _execution_body(execution)


@router.post("/executions/{execution_id}/steps/{step_index}/decision")
def decide_approval_endpoint(
    execution_id: UUID,
    step_index: int,
    payload: ApprovalDecisionRequest,
    tenant: TenantContext = Depends(require_permission("agents.approve")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        execution = decide_approval(db, organization_id=tenant.organization_id, execution_id=execution_id,
                                    step_index=step_index, user_context=user_context, approve=payload.approve)
        db.commit()
    except AgentError as error:
        db.rollback()
        _raise(error)
    return _execution_body(execution)


__all__ = ["router"]

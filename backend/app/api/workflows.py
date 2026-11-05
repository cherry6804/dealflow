"""Workflow definitions over HTTP (DFR1-023).

Reading needs ``workflows.read``. Drafts and validation need ``workflows.manage``. Publishing, pausing, resuming, rolling back and
archiving need ``workflows.publish``. Every route is scoped to the verified organization. The request models refuse unknown fields.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.authz.dependencies import require_permission
from app.db.models.workflow import (
    WorkflowDefinition,
    WorkflowLifecycleEvent,
    WorkflowVersion,
)
from app.db.session import get_db_session
from app.tenant.dependencies import TenantContext
from app.workflows.service import (
    WorkflowError,
    archive,
    create_workflow,
    get_workflow,
    has_unpublished_changes,
    list_history,
    list_versions,
    list_workflows,
    pause,
    publish,
    resume,
    rollback,
    update_draft,
    validate_draft,
)

router = APIRouter(prefix="/api/v1/automation/workflows", tags=["workflows"])


class WorkflowCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    configuration: dict[str, Any] | None = None


class WorkflowUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    configuration: dict[str, Any] | None = None


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_number: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


def _raise(error: WorkflowError) -> None:
    detail: dict[str, Any] = {"reason": error.reason}
    if error.problems:
        detail["problems"] = error.problems
    raise HTTPException(status_code=error.status, detail=detail) from error


def _summary(row: WorkflowDefinition) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "revision": row.draft_revision,
        "current_version_id": str(row.current_version_id) if row.current_version_id else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _detail(db: Session, row: WorkflowDefinition) -> dict[str, Any]:
    current = db.get(WorkflowVersion, row.current_version_id) if row.current_version_id else None
    return dict(
        _summary(row),
        draft=row.draft_configuration,
        has_unpublished_changes=has_unpublished_changes(db, row),
        current_version=_version_summary(current) if current else None,
    )


def _version_summary(version: WorkflowVersion) -> dict[str, Any]:
    return {
        "id": str(version.id),
        "version_number": version.version_number,
        "name": version.name,
        "content_hash": version.content_hash,
        "schema_version": version.schema_version,
        "required_permissions": version.required_permissions,
        "agent_references": version.agent_references,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "published_by_user_id": str(version.published_by_user_id),
    }


def _version_detail(version: WorkflowVersion) -> dict[str, Any]:
    return dict(_version_summary(version), description=version.description, configuration=version.configuration)


def _event_body(event: WorkflowLifecycleEvent) -> dict[str, Any]:
    return {
        "action": event.action,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "version_id": str(event.version_id) if event.version_id else None,
        "target_version_id": str(event.target_version_id) if event.target_version_id else None,
        "actor_user_id": str(event.actor_user_id),
        "reason": event.reason,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.get("")
def list_endpoint(
    tenant: TenantContext = Depends(require_permission("workflows.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        rows = list_workflows(db, organization_id=tenant.organization_id, actor_id=user_context.user.id)
    except WorkflowError as error:
        _raise(error)
    return {"items": [_summary(row) for row in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_endpoint(
    payload: WorkflowCreateRequest,
    tenant: TenantContext = Depends(require_permission("workflows.manage")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = create_workflow(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, name=payload.name,
                              description=payload.description, configuration=payload.configuration)
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    return _detail(db, row)


@router.get("/{workflow_id}")
def get_endpoint(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflows.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = get_workflow(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, workflow_id=workflow_id)
    except WorkflowError as error:
        _raise(error)
    return _detail(db, row)


@router.patch("/{workflow_id}")
def update_endpoint(
    workflow_id: UUID,
    payload: WorkflowUpdateRequest,
    tenant: TenantContext = Depends(require_permission("workflows.manage")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    fields = payload.model_fields_set
    try:
        row = update_draft(
            db,
            organization_id=tenant.organization_id,
            actor_id=user_context.user.id,
            workflow_id=workflow_id,
            expected_revision=payload.revision,
            name=payload.name,
            description=payload.description,
            configuration=payload.configuration,
            description_set="description" in fields,
        )
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    return _detail(db, row)


@router.post("/{workflow_id}/validate")
def validate_endpoint(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflows.manage")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        result = validate_draft(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                                workflow_id=workflow_id, user_context=user_context)
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    return result


@router.post("/{workflow_id}/publish")
def publish_endpoint(
    workflow_id: UUID,
    response: Response,
    tenant: TenantContext = Depends(require_permission("workflows.publish")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Publish the draft. Returns 201 with a new version, or 200 with the current version when the draft is unchanged."""
    try:
        version, created = publish(db, organization_id=tenant.organization_id, actor_id=user_context.user.id,
                                   workflow_id=workflow_id, user_context=user_context)
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return dict(_version_detail(version), created=created)


def _lifecycle(action, *, workflow_id: UUID, tenant: TenantContext, user_context: CurrentUserContext,
               db: Session) -> dict[str, Any]:
    try:
        row = action(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, workflow_id=workflow_id)
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    return _detail(db, row)


@router.post("/{workflow_id}/pause")
def pause_endpoint(
    workflow_id: UUID,
    payload: ReasonRequest | None = None,
    tenant: TenantContext = Depends(require_permission("workflows.publish")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = pause(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, workflow_id=workflow_id,
                    reason=payload.reason if payload else None)
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    return _detail(db, row)


@router.post("/{workflow_id}/resume")
def resume_endpoint(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflows.publish")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = resume(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, workflow_id=workflow_id,
                     user_context=user_context)
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    return _detail(db, row)


@router.post("/{workflow_id}/archive")
def archive_endpoint(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflows.publish")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return _lifecycle(archive, workflow_id=workflow_id, tenant=tenant, user_context=user_context, db=db)


@router.post("/{workflow_id}/rollback")
def rollback_endpoint(
    workflow_id: UUID,
    payload: RollbackRequest,
    tenant: TenantContext = Depends(require_permission("workflows.publish")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        row = rollback(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, workflow_id=workflow_id,
                       version_number=payload.version_number, user_context=user_context)
        db.commit()
    except WorkflowError as error:
        db.rollback()
        _raise(error)
    return _detail(db, row)


@router.get("/{workflow_id}/versions")
def versions_endpoint(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflows.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        rows = list_versions(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, workflow_id=workflow_id)
    except WorkflowError as error:
        _raise(error)
    return {"items": [_version_summary(row) for row in rows]}


@router.get("/{workflow_id}/versions/{version_number}")
def version_detail_endpoint(
    workflow_id: UUID,
    version_number: int,
    tenant: TenantContext = Depends(require_permission("workflows.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        rows = list_versions(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, workflow_id=workflow_id)
    except WorkflowError as error:
        _raise(error)
    row = next((item for item in rows if item.version_number == version_number), None)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"reason": "version_not_found"})
    return _version_detail(row)


@router.get("/{workflow_id}/history")
def history_endpoint(
    workflow_id: UUID,
    tenant: TenantContext = Depends(require_permission("workflows.read")),
    user_context: CurrentUserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        rows = list_history(db, organization_id=tenant.organization_id, actor_id=user_context.user.id, workflow_id=workflow_id)
    except WorkflowError as error:
        _raise(error)
    return {"items": [_event_body(row) for row in rows]}


__all__ = ["router"]

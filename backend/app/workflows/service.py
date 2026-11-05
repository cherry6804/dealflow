"""Workflow definitions: drafts, validation, publishing, pause, resume, rollback and archive (DFR1-023).

Every operation runs in the caller's organization and checks the caller's permission on the server. Mutations lock the definition
row, so two members editing or publishing at once cannot interleave. A draft edit carries the revision it was based on, and a stale
revision is refused. Publishing writes a new immutable version, unless the draft matches the current version, in which case nothing
changes. Rollback moves the current pointer to an earlier version after the publish checks pass again. Every transition writes a
lifecycle event and an independent audit record. No operation here executes a workflow.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.attribution import user_attribution
from app.audit.independent import OUTCOME_COMPLETED, persist_independent_audit_event
from app.auth.dependencies import CurrentUserContext
from app.db.models.workflow import (
    WorkflowDefinition,
    WorkflowLifecycleEvent,
    WorkflowVersion,
)
from app.governance.execution_gate import actor_permission_granted
from app.workflows.publish_checks import (
    agent_references,
    publish_problems,
    required_permissions,
)
from app.workflows.schema import (
    SCHEMA_VERSION,
    WorkflowValidationError,
    normalise_workflow_configuration,
    require_publishable,
)

AUDIT_EVENT = "workflow"
MAX_NAME = 120
MAX_DESCRIPTION = 1000

REASON_NOT_FOUND = "workflow_not_found"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_REVISION_CONFLICT = "revision_conflict"
REASON_NAME_TAKEN = "workflow_name_taken"
REASON_ARCHIVED = "workflow_archived"
REASON_INVALID_STATE = "invalid_state"
REASON_VERSION_NOT_FOUND = "version_not_found"
REASON_INVALID_TARGET = "invalid_rollback_target"
REASON_INVALID_CONFIGURATION = "invalid_configuration"
REASON_PUBLISH_BLOCKED = "publish_blocked"


class WorkflowError(Exception):
    def __init__(self, reason: str, problems: list[dict[str, str]] | None = None, *, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problems = problems or []
        self.status = status


def content_hash(name: str, description: str | None, configuration: dict[str, Any]) -> str:
    payload = {"name": name, "description": description, "configuration": configuration}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _require(db: Session, *, organization_id: UUID, actor_id: UUID, permission: str) -> None:
    if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id, permission_key=permission):
        raise WorkflowError(REASON_PERMISSION_DENIED, status=403)


def _clean_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > MAX_NAME:
        raise WorkflowError(REASON_INVALID_CONFIGURATION, [{"path": "name", "message": "A name of 1 to 120 characters is required."}],
                            status=422)
    return cleaned


def _clean_description(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if len(value) > MAX_DESCRIPTION:
        raise WorkflowError(REASON_INVALID_CONFIGURATION,
                            [{"path": "description", "message": "The description must be 1000 characters or fewer."}], status=422)
    return value.strip()


def _normalise(configuration: object) -> dict[str, Any]:
    try:
        return normalise_workflow_configuration(configuration)
    except WorkflowValidationError as error:
        raise WorkflowError(REASON_INVALID_CONFIGURATION, error.problems, status=422) from error


def _audit(db: Session, *, organization_id: UUID, actor_id: UUID, workflow: WorkflowDefinition, action: str,
           metadata: dict[str, Any]) -> None:
    # Identifiers, statuses and version numbers only. The configuration itself is stored on the definition and the version.
    persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=actor_id),
        event_type=AUDIT_EVENT,
        action=action,
        decision="allowed",
        outcome=OUTCOME_COMPLETED,
        permission_key="workflows.manage",
        resource_type="workflow",
        resource_id=str(workflow.id),
        metadata=metadata,
    )


def _event(db: Session, *, workflow: WorkflowDefinition, actor_id: UUID, action: str, from_status: str | None,
           to_status: str, version_id: UUID | None = None, target_version_id: UUID | None = None,
           reason: str | None = None) -> None:
    db.add(WorkflowLifecycleEvent(
        organization_id=workflow.organization_id,
        workflow_id=workflow.id,
        action=action,
        from_status=from_status,
        to_status=to_status,
        version_id=version_id,
        target_version_id=target_version_id,
        actor_user_id=actor_id,
        reason=(reason or "").strip()[:500] or None,
    ))
    db.flush()


def _lock(db: Session, *, organization_id: UUID, workflow_id: UUID) -> WorkflowDefinition:
    workflow = db.scalar(select(WorkflowDefinition).where(
        WorkflowDefinition.id == workflow_id,
        WorkflowDefinition.organization_id == organization_id,
    ).with_for_update())
    if workflow is None:
        raise WorkflowError(REASON_NOT_FOUND, status=404)
    return workflow


def _current_version(db: Session, workflow: WorkflowDefinition) -> WorkflowVersion | None:
    if workflow.current_version_id is None:
        return None
    return db.get(WorkflowVersion, workflow.current_version_id)


def has_unpublished_changes(db: Session, workflow: WorkflowDefinition) -> bool:
    current = _current_version(db, workflow)
    draft_hash = content_hash(workflow.name, workflow.description, workflow.draft_configuration)
    return current is None or current.content_hash != draft_hash


def list_workflows(db: Session, *, organization_id: UUID, actor_id: UUID) -> list[WorkflowDefinition]:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.read")
    return list(db.scalars(select(WorkflowDefinition).where(
        WorkflowDefinition.organization_id == organization_id
    ).order_by(WorkflowDefinition.name, WorkflowDefinition.id)).all())


def get_workflow(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID) -> WorkflowDefinition:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.read")
    workflow = db.scalar(select(WorkflowDefinition).where(
        WorkflowDefinition.id == workflow_id,
        WorkflowDefinition.organization_id == organization_id,
    ))
    if workflow is None:
        raise WorkflowError(REASON_NOT_FOUND, status=404)
    return workflow


def create_workflow(db: Session, *, organization_id: UUID, actor_id: UUID, name: str, description: str | None,
                    configuration: object) -> WorkflowDefinition:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.manage")
    clean_name = _clean_name(name)
    canonical = _normalise(configuration if configuration is not None else {"schema_version": SCHEMA_VERSION})
    workflow = WorkflowDefinition(
        organization_id=organization_id,
        name=clean_name,
        description=_clean_description(description),
        status=WorkflowDefinition.STATUS_DRAFT,
        draft_configuration=canonical,
        draft_revision=1,
        created_by_user_id=actor_id,
        updated_by_user_id=actor_id,
    )
    db.add(workflow)
    try:
        db.flush()
    except IntegrityError as error:
        raise WorkflowError(REASON_NAME_TAKEN, status=409) from error
    _event(db, workflow=workflow, actor_id=actor_id, action="created", from_status=None, to_status="draft")
    _audit(db, organization_id=organization_id, actor_id=actor_id, workflow=workflow, action="workflow.created", metadata={})
    return workflow


def update_draft(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID, expected_revision: int,
                 name: str | None, description: str | None, configuration: object | None,
                 description_set: bool) -> WorkflowDefinition:
    """Edit the draft. The draft is validated before it is stored. A published version is never touched by an edit."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.manage")
    workflow = _lock(db, organization_id=organization_id, workflow_id=workflow_id)
    if workflow.status == WorkflowDefinition.STATUS_ARCHIVED:
        raise WorkflowError(REASON_ARCHIVED)
    if expected_revision != workflow.draft_revision:
        raise WorkflowError(REASON_REVISION_CONFLICT, [{"path": "revision", "message": "The draft changed. Reload and try again."}])
    new_name = _clean_name(name) if name is not None else workflow.name
    new_description = _clean_description(description) if description_set else workflow.description
    new_configuration = _normalise(configuration) if configuration is not None else workflow.draft_configuration
    if (new_name, new_description, new_configuration) == (workflow.name, workflow.description, workflow.draft_configuration):
        return workflow
    try:
        with db.begin_nested():
            workflow.name = new_name
            workflow.description = new_description
            workflow.draft_configuration = new_configuration
            workflow.draft_revision += 1
            workflow.updated_by_user_id = actor_id
            workflow.updated_at = datetime.now(UTC)
            db.flush()
    except IntegrityError as error:
        raise WorkflowError(REASON_NAME_TAKEN) from error
    _event(db, workflow=workflow, actor_id=actor_id, action="draft_saved", from_status=workflow.status,
           to_status=workflow.status)
    _audit(db, organization_id=organization_id, actor_id=actor_id, workflow=workflow, action="workflow.draft_saved",
           metadata={"revision": workflow.draft_revision})
    return workflow


def validate_draft(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID,
                   user_context: CurrentUserContext | None = None) -> dict[str, Any]:
    """Check the draft as it would be published, without changing anything. Returns the problems found."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.manage")
    workflow = _lock_read(db, organization_id=organization_id, workflow_id=workflow_id)
    problems = require_publishable(workflow.draft_configuration, name=workflow.name, description=workflow.description)
    if workflow.draft_configuration.get("steps"):
        problems.extend(publish_problems(db, organization_id=organization_id, actor_id=actor_id,
                                         configuration=workflow.draft_configuration, user_context=user_context))
    return {"valid": not problems, "problems": problems, "revision": workflow.draft_revision}


def _lock_read(db: Session, *, organization_id: UUID, workflow_id: UUID) -> WorkflowDefinition:
    workflow = db.scalar(select(WorkflowDefinition).where(
        WorkflowDefinition.id == workflow_id, WorkflowDefinition.organization_id == organization_id))
    if workflow is None:
        raise WorkflowError(REASON_NOT_FOUND, status=404)
    return workflow


def publish(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID,
            user_context: CurrentUserContext | None = None) -> tuple[WorkflowVersion, bool]:
    """Publish the draft as a new immutable version. Returns ``(version, created)``. An unchanged draft returns the current version."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.publish")
    workflow = _lock(db, organization_id=organization_id, workflow_id=workflow_id)
    if workflow.status == WorkflowDefinition.STATUS_ARCHIVED:
        raise WorkflowError(REASON_ARCHIVED)
    problems = require_publishable(workflow.draft_configuration, name=workflow.name, description=workflow.description)
    problems.extend(publish_problems(db, organization_id=organization_id, actor_id=actor_id,
                                     configuration=workflow.draft_configuration, user_context=user_context))
    if problems:
        raise WorkflowError(REASON_PUBLISH_BLOCKED, problems)

    digest = content_hash(workflow.name, workflow.description, workflow.draft_configuration)
    current = _current_version(db, workflow)
    if current is not None and current.content_hash == digest:
        return current, False

    next_number = int(db.scalar(select(func.coalesce(func.max(WorkflowVersion.version_number), 0)).where(
        WorkflowVersion.workflow_id == workflow.id)) or 0) + 1
    version = WorkflowVersion(
        organization_id=organization_id,
        workflow_id=workflow.id,
        version_number=next_number,
        name=workflow.name,
        description=workflow.description,
        configuration=workflow.draft_configuration,
        content_hash=digest,
        schema_version=SCHEMA_VERSION,
        required_permissions=required_permissions(workflow.draft_configuration),
        agent_references=agent_references(workflow.draft_configuration),
        published_by_user_id=actor_id,
    )
    db.add(version)
    db.flush()
    previous = workflow.status
    workflow.current_version_id = version.id
    if previous != WorkflowDefinition.STATUS_PAUSED:
        # A paused workflow stays paused after a new version is published: pausing is an explicit decision.
        workflow.status = WorkflowDefinition.STATUS_PUBLISHED
    workflow.updated_at = datetime.now(UTC)
    db.flush()
    _event(db, workflow=workflow, actor_id=actor_id, action="published", from_status=previous,
           to_status=workflow.status, version_id=version.id)
    _audit(db, organization_id=organization_id, actor_id=actor_id, workflow=workflow, action="workflow.published",
           metadata={"version_number": version.version_number, "content_hash": digest})
    return version, True


def _transition(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID, action: str,
                allowed_from: tuple[str, ...], to_status: str, reason: str | None = None) -> WorkflowDefinition:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.publish")
    workflow = _lock(db, organization_id=organization_id, workflow_id=workflow_id)
    if workflow.status not in allowed_from:
        raise WorkflowError(REASON_INVALID_STATE, [{"path": "status", "message": f"A {workflow.status} workflow cannot be {action}."}])
    previous = workflow.status
    workflow.status = to_status
    workflow.updated_at = datetime.now(UTC)
    db.flush()
    _event(db, workflow=workflow, actor_id=actor_id, action=action, from_status=previous, to_status=to_status,
           version_id=workflow.current_version_id, reason=reason)
    _audit(db, organization_id=organization_id, actor_id=actor_id, workflow=workflow, action=f"workflow.{action}",
           metadata={"from_status": previous, "to_status": to_status})
    return workflow


def pause(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID, reason: str | None = None) -> WorkflowDefinition:
    return _transition(db, organization_id=organization_id, actor_id=actor_id, workflow_id=workflow_id, action="paused",
                       allowed_from=(WorkflowDefinition.STATUS_PUBLISHED,), to_status=WorkflowDefinition.STATUS_PAUSED,
                       reason=reason)


def resume(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID,
           user_context: CurrentUserContext | None = None) -> WorkflowDefinition:
    """Resume a paused workflow. The current version is checked again first, so a permission or entitlement lost since publish blocks it."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.publish")
    workflow = _lock(db, organization_id=organization_id, workflow_id=workflow_id)
    if workflow.status != WorkflowDefinition.STATUS_PAUSED:
        raise WorkflowError(REASON_INVALID_STATE, [{"path": "status", "message": f"A {workflow.status} workflow cannot be resumed."}])
    current = _current_version(db, workflow)
    if current is None:
        raise WorkflowError(REASON_INVALID_STATE, [{"path": "status", "message": "There is no published version to resume."}])
    problems = publish_problems(db, organization_id=organization_id, actor_id=actor_id, configuration=current.configuration,
                                user_context=user_context)
    if problems:
        raise WorkflowError(REASON_PUBLISH_BLOCKED, problems)
    previous = workflow.status
    workflow.status = WorkflowDefinition.STATUS_PUBLISHED
    workflow.updated_at = datetime.now(UTC)
    db.flush()
    _event(db, workflow=workflow, actor_id=actor_id, action="resumed", from_status=previous,
           to_status=WorkflowDefinition.STATUS_PUBLISHED, version_id=current.id)
    _audit(db, organization_id=organization_id, actor_id=actor_id, workflow=workflow, action="workflow.resumed",
           metadata={"version_number": current.version_number})
    return workflow


def rollback(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID,
             version_number: int, user_context: CurrentUserContext | None = None) -> WorkflowDefinition:
    """Point the workflow at an earlier immutable version. No version is created or changed; the target must pass the publish checks now."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.publish")
    workflow = _lock(db, organization_id=organization_id, workflow_id=workflow_id)
    if workflow.status not in (WorkflowDefinition.STATUS_PUBLISHED, WorkflowDefinition.STATUS_PAUSED):
        raise WorkflowError(REASON_INVALID_STATE, [{"path": "status", "message": f"A {workflow.status} workflow cannot be rolled back."}])
    target = db.scalar(select(WorkflowVersion).where(
        WorkflowVersion.workflow_id == workflow.id,
        WorkflowVersion.organization_id == organization_id,
        WorkflowVersion.version_number == version_number,
    ))
    if target is None:
        raise WorkflowError(REASON_VERSION_NOT_FOUND, status=404)
    if target.id == workflow.current_version_id:
        raise WorkflowError(REASON_INVALID_TARGET, [{"path": "version_number", "message": "That version is already current."}])
    problems = publish_problems(db, organization_id=organization_id, actor_id=actor_id, configuration=target.configuration,
                                user_context=user_context)
    if problems:
        raise WorkflowError(REASON_PUBLISH_BLOCKED, problems)
    previous_version = workflow.current_version_id
    workflow.current_version_id = target.id
    workflow.updated_at = datetime.now(UTC)
    db.flush()
    _event(db, workflow=workflow, actor_id=actor_id, action="rolled_back", from_status=workflow.status,
           to_status=workflow.status, version_id=previous_version, target_version_id=target.id)
    _audit(db, organization_id=organization_id, actor_id=actor_id, workflow=workflow, action="workflow.rolled_back",
           metadata={"target_version_number": target.version_number})
    return workflow


def archive(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID) -> WorkflowDefinition:
    return _transition(db, organization_id=organization_id, actor_id=actor_id, workflow_id=workflow_id, action="archived",
                       allowed_from=(WorkflowDefinition.STATUS_DRAFT, WorkflowDefinition.STATUS_PUBLISHED,
                                     WorkflowDefinition.STATUS_PAUSED),
                       to_status=WorkflowDefinition.STATUS_ARCHIVED)


def list_versions(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID) -> list[WorkflowVersion]:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.read")
    if db.scalar(select(WorkflowDefinition.id).where(
            WorkflowDefinition.id == workflow_id, WorkflowDefinition.organization_id == organization_id)) is None:
        raise WorkflowError(REASON_NOT_FOUND, status=404)
    return list(db.scalars(select(WorkflowVersion).where(
        WorkflowVersion.workflow_id == workflow_id,
        WorkflowVersion.organization_id == organization_id,
    ).order_by(WorkflowVersion.version_number.desc())).all())


def list_history(db: Session, *, organization_id: UUID, actor_id: UUID, workflow_id: UUID) -> list[WorkflowLifecycleEvent]:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="workflows.read")
    if db.scalar(select(WorkflowDefinition.id).where(
            WorkflowDefinition.id == workflow_id, WorkflowDefinition.organization_id == organization_id)) is None:
        raise WorkflowError(REASON_NOT_FOUND, status=404)
    return list(db.scalars(select(WorkflowLifecycleEvent).where(
        WorkflowLifecycleEvent.workflow_id == workflow_id,
        WorkflowLifecycleEvent.organization_id == organization_id,
    ).order_by(WorkflowLifecycleEvent.created_at, WorkflowLifecycleEvent.id)).all())

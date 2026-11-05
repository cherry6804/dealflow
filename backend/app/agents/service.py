"""Agent definitions, validation, versioning and lifecycle (DFR1-019).

Every operation runs in the caller's organization, for an authenticated actor who must hold the permission for the operation.
Publishing, resuming and rolling back repeat the checks that depend on the actor and the database: tool availability and each
tool's permission, knowledge access, the text model route, the AI capability, and the required execution limits. A published
version is written once and is never changed. A rollback moves the agent's pointer to an older version and creates no new one.

Each change writes an independent audit record in the caller's organization, attributed to the acting user.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.configuration import (
    ConfigurationError,
    normalise_configuration,
    require_publishable,
)
from app.agents.crm_action_catalogue import CRM_ACTIONS
from app.ai_gateway.routing import resolve_route
from app.ai_gateway.tasks import TaskType
from app.ai_tools.registry import DEFAULT_REGISTRY
from app.audit.attribution import user_attribution
from app.audit.independent import OUTCOME_COMPLETED, persist_independent_audit_event
from app.db.models.agent import Agent, AgentExecution, AgentVersion
from app.db.models.document import Document
from app.governance.execution_gate import actor_permission_granted
from app.governance.policy import REASON_EXECUTION_GATES_PENDING, evaluate_capability
from app.knowledge.service import ELIGIBLE_CLASSIFICATIONS

AGENT_CAPABILITY = "ai.agents"
AGENT_AUDIT_EVENT = "agent"

REASON_NOT_FOUND = "agent_not_found"
REASON_INVALID_STATE = "invalid_agent_state"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_PUBLISH_BLOCKED = "publish_blocked"
REASON_VERSION_NOT_FOUND = "version_not_found"
REASON_NAME_TAKEN = "agent_name_taken"


class AgentError(Exception):
    """A lifecycle or validation refusal. ``reason`` is stable; ``problems`` never echo a stored secret or a document's content."""

    def __init__(self, reason: str, problems: list[str] | None = None, *, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problems = problems or []
        self.status = status


def _audit(db: Session, *, organization_id: UUID, actor_id: UUID, action: str, agent: Agent,
           metadata: Mapping[str, object] | None = None) -> None:
    persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=actor_id),
        event_type=AGENT_AUDIT_EVENT,
        action=action,
        decision="allowed",
        outcome=OUTCOME_COMPLETED,
        permission_key=None,
        resource_type="agent",
        resource_id=str(agent.id),
        metadata=dict(metadata or {}, status=agent.status),
    )


def _require(db: Session, *, organization_id: UUID, actor_id: UUID, permission: str) -> None:
    if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id, permission_key=permission):
        raise AgentError(REASON_PERMISSION_DENIED, status=403)


def get_agent(db: Session, *, organization_id: UUID, agent_id: UUID) -> Agent:
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id))
    if agent is None:
        raise AgentError(REASON_NOT_FOUND, status=404)
    return agent


def list_agents(db: Session, *, organization_id: UUID) -> list[Agent]:
    return list(db.scalars(select(Agent).where(Agent.organization_id == organization_id).order_by(Agent.name)).all())


def list_versions(db: Session, *, organization_id: UUID, agent_id: UUID) -> list[AgentVersion]:
    get_agent(db, organization_id=organization_id, agent_id=agent_id)
    return list(db.scalars(
        select(AgentVersion)
        .where(AgentVersion.organization_id == organization_id, AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
    ).all())


def load_version(db: Session, *, organization_id: UUID, agent: Agent) -> AgentVersion | None:
    if agent.current_version_id is None:
        return None
    return db.scalar(select(AgentVersion).where(
        AgentVersion.id == agent.current_version_id,
        AgentVersion.organization_id == organization_id,
        AgentVersion.agent_id == agent.id,
    ))


def _canonical(raw: object) -> dict[str, Any]:
    try:
        return normalise_configuration(raw, registered_tools=frozenset(DEFAULT_REGISTRY.keys()))
    except ConfigurationError as error:
        raise AgentError("invalid_configuration", error.problems, status=422) from error


def _name_available(db: Session, *, organization_id: UUID, name: str, exclude: UUID | None = None) -> None:
    statement = select(Agent.id).where(Agent.organization_id == organization_id, func.lower(Agent.name) == name.lower())
    if exclude is not None:
        statement = statement.where(Agent.id != exclude)
    if db.scalar(statement) is not None:
        raise AgentError(REASON_NAME_TAKEN, status=409)


def create_agent(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    name: str,
    description: str | None,
    configuration: object,
    owner_user_id: UUID | None = None,
) -> Agent:
    """Create a draft agent. The creator is the owner unless an active member of the organization is named."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="agents.manage")
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 120:
        raise AgentError("invalid_name", ["The name must be 1 to 120 characters."], status=422)
    _name_available(db, organization_id=organization_id, name=cleaned)
    owner = owner_user_id or actor_id
    if owner != actor_id and not actor_permission_granted(
        db, organization_id=organization_id, user_id=owner, permission_key="agents.read"
    ):
        raise AgentError("invalid_owner", ["The owner must be an active member of the organization."], status=422)
    agent = Agent(
        organization_id=organization_id,
        name=cleaned,
        description=(description or "").strip() or None,
        status=Agent.STATUS_DRAFT,
        draft_configuration=_canonical(configuration),
        owner_user_id=owner,
        created_by_user_id=actor_id,
    )
    db.add(agent)
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="agent.created", agent=agent)
    return agent


def update_draft(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    agent_id: UUID,
    name: str | None = None,
    description: str | None = None,
    configuration: object | None = None,
) -> Agent:
    """Change the draft. The published version is untouched, whatever the status of the agent."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="agents.manage")
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id).with_for_update())
    if agent is None:
        raise AgentError(REASON_NOT_FOUND, status=404)
    if agent.status == Agent.STATUS_ARCHIVED:
        raise AgentError(REASON_INVALID_STATE, ["An archived agent cannot be edited."])
    if name is not None:
        cleaned = name.strip()
        if not cleaned or len(cleaned) > 120:
            raise AgentError("invalid_name", ["The name must be 1 to 120 characters."], status=422)
        _name_available(db, organization_id=organization_id, name=cleaned, exclude=agent.id)
        agent.name = cleaned
    if description is not None:
        agent.description = description.strip() or None
    if configuration is not None:
        agent.draft_configuration = _canonical(configuration)
    agent.updated_at = datetime.now(UTC)
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="agent.draft_updated", agent=agent)
    return agent


def validate_access(db: Session, *, organization_id: UUID, actor_id: UUID, configuration: Mapping[str, Any]) -> list[str]:
    """Problems that stop this configuration from running for this actor now. Empty when it may run.

    Checks, in order: each tool is still registered and the actor holds its permission; each knowledge source is available,
    eligible and scanned, and the actor may read documents; the text model route exists; the AI capability allows the
    organization to run agents (switches, entitlement, provider readiness).
    """
    problems: list[str] = []
    for tool_key in configuration.get("tools", []):
        definition = DEFAULT_REGISTRY.get(tool_key)
        if definition is None:
            problems.append(f"The tool {tool_key} is no longer available.")
        elif not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id,
                                          permission_key=definition.required_permission):
            problems.append(f"The actor lacks the permission for the tool {tool_key}.")
    for step in configuration.get("steps", []):
        if step.get("kind") != "crm_action":
            continue
        spec = CRM_ACTIONS.get(step.get("action"))
        if spec is None:
            problems.append("A CRM action in the plan is no longer available.")
            continue
        for permission in spec.permissions:
            if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id, permission_key=permission):
                problems.append(f"The actor lacks the permission for the action {spec.key}.")
    documents = configuration.get("knowledge_document_ids", [])
    if documents:
        if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id,
                                        permission_key="documents.read"):
            problems.append("The actor lacks the permission to read the knowledge sources.")
        eligible = db.scalars(select(Document.id).where(
            Document.organization_id == organization_id,
            Document.id.in_([UUID(item) for item in documents]),
            Document.status == Document.STATUS_AVAILABLE,
            Document.scan_status == Document.SCAN_CLEAN,
            Document.access_classification.in_(sorted(ELIGIBLE_CLASSIFICATIONS)),
        )).all()
        if len(set(eligible)) != len(set(documents)):
            problems.append("A knowledge source is missing, unavailable, not eligible or not scanned.")
    if configuration.get("steps") and resolve_route(db, organization_id=organization_id, task=TaskType.TEXT) is None:
        problems.append("No text model is routed for this organization.")
    decision = evaluate_capability(db, organization_id=organization_id, capability_key=AGENT_CAPABILITY)
    if not static_allowed(decision):
        problems.append(f"AI agents are not available now: {decision.reason_code}.")
    return problems


def static_allowed(decision) -> bool:
    """Whether the switches, entitlement and provider readiness allow the capability.

    ``execution_gates_pending`` means production approvals for AI execution are still missing. Publishing is allowed in that
    state, because a draft can be prepared before approval. Every execution is still refused at the execution gate until the
    approvals exist, so nothing runs unapproved.
    """
    return decision.allowed or decision.reason_code == REASON_EXECUTION_GATES_PENDING


def validate_for_publish(db: Session, *, organization_id: UUID, actor_id: UUID,
                         configuration: Mapping[str, Any]) -> dict[str, Any]:
    """Publish-time checks. Returns the validation snapshot stored with the version, or raises ``AgentError``."""
    problems = require_publishable(configuration)
    problems += validate_access(db, organization_id=organization_id, actor_id=actor_id, configuration=configuration)
    if problems:
        raise AgentError(REASON_PUBLISH_BLOCKED, problems, status=422)
    return {
        "validated_at": datetime.now(UTC).isoformat(),
        "tools": list(configuration.get("tools", [])),
        "knowledge_document_count": len(configuration.get("knowledge_document_ids", [])),
        "limits": dict(configuration.get("limits", {})),
        "route_task": TaskType.TEXT.value,
        "capability": AGENT_CAPABILITY,
    }


def publish(db: Session, *, organization_id: UUID, actor_id: UUID, agent_id: UUID) -> AgentVersion:
    """Freeze the draft as the next immutable version and make it current."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="agents.publish")
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id).with_for_update())
    if agent is None:
        raise AgentError(REASON_NOT_FOUND, status=404)
    if agent.status not in (Agent.STATUS_DRAFT, Agent.STATUS_PUBLISHED):
        raise AgentError(REASON_INVALID_STATE, [f"A {agent.status} agent cannot be published. Resume it first."])
    configuration = dict(agent.draft_configuration)
    snapshot = validate_for_publish(db, organization_id=organization_id, actor_id=actor_id, configuration=configuration)
    latest = db.scalar(select(func.max(AgentVersion.version_number)).where(AgentVersion.agent_id == agent.id)) or 0
    version = AgentVersion(
        organization_id=organization_id,
        agent_id=agent.id,
        version_number=latest + 1,
        configuration=configuration,
        validation_snapshot=snapshot,
        published_by_user_id=actor_id,
    )
    db.add(version)
    db.flush()
    agent.current_version_id = version.id
    agent.status = Agent.STATUS_PUBLISHED
    agent.updated_at = datetime.now(UTC)
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="agent.published", agent=agent,
           metadata={"version_number": version.version_number})
    return version


def pause(db: Session, *, organization_id: UUID, actor_id: UUID, agent_id: UUID) -> Agent:
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="agents.publish")
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id).with_for_update())
    if agent is None:
        raise AgentError(REASON_NOT_FOUND, status=404)
    if agent.status != Agent.STATUS_PUBLISHED:
        raise AgentError(REASON_INVALID_STATE, [f"A {agent.status} agent cannot be paused."])
    agent.status = Agent.STATUS_PAUSED
    agent.updated_at = datetime.now(UTC)
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="agent.paused", agent=agent)
    return agent


def resume(db: Session, *, organization_id: UUID, actor_id: UUID, agent_id: UUID) -> Agent:
    """Resume a paused agent after revalidating its current version for this actor."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="agents.publish")
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id).with_for_update())
    if agent is None:
        raise AgentError(REASON_NOT_FOUND, status=404)
    if agent.status != Agent.STATUS_PAUSED:
        raise AgentError(REASON_INVALID_STATE, [f"A {agent.status} agent cannot be resumed."])
    version = load_version(db, organization_id=organization_id, agent=agent)
    if version is None:
        raise AgentError(REASON_INVALID_STATE, ["The agent has no published version to resume."])
    problems = validate_access(db, organization_id=organization_id, actor_id=actor_id, configuration=version.configuration)
    if problems:
        raise AgentError(REASON_PUBLISH_BLOCKED, problems, status=422)
    agent.status = Agent.STATUS_PUBLISHED
    agent.updated_at = datetime.now(UTC)
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="agent.resumed", agent=agent)
    return agent


def archive(db: Session, *, organization_id: UUID, actor_id: UUID, agent_id: UUID) -> Agent:
    """Archive an agent. No new execution starts, and an execution in flight stops at its next step."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="agents.publish")
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id).with_for_update())
    if agent is None:
        raise AgentError(REASON_NOT_FOUND, status=404)
    if agent.status == Agent.STATUS_ARCHIVED:
        raise AgentError(REASON_INVALID_STATE, ["The agent is already archived."])
    agent.status = Agent.STATUS_ARCHIVED
    agent.archived_at = datetime.now(UTC)
    agent.updated_at = agent.archived_at
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="agent.archived", agent=agent)
    return agent


def rollback(db: Session, *, organization_id: UUID, actor_id: UUID, agent_id: UUID, version_number: int) -> Agent:
    """Point the agent at an earlier published version. Nothing is copied or edited, and the target is revalidated first."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="agents.publish")
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id).with_for_update())
    if agent is None:
        raise AgentError(REASON_NOT_FOUND, status=404)
    if agent.status == Agent.STATUS_ARCHIVED:
        raise AgentError(REASON_INVALID_STATE, ["An archived agent cannot be rolled back."])
    target = db.scalar(select(AgentVersion).where(
        AgentVersion.agent_id == agent.id,
        AgentVersion.organization_id == organization_id,
        AgentVersion.version_number == version_number,
    ))
    if target is None:
        raise AgentError(REASON_VERSION_NOT_FOUND, status=404)
    if target.id == agent.current_version_id:
        raise AgentError(REASON_INVALID_STATE, ["That version is already the current one."])
    problems = validate_access(db, organization_id=organization_id, actor_id=actor_id, configuration=target.configuration)
    if problems:
        raise AgentError(REASON_PUBLISH_BLOCKED, problems, status=422)
    agent.current_version_id = target.id
    agent.updated_at = datetime.now(UTC)
    db.flush()
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="agent.rolled_back", agent=agent,
           metadata={"version_number": version_number})
    return agent


def preview(db: Session, *, organization_id: UUID, actor_id: UUID, agent_id: UUID) -> dict[str, Any]:
    """Describe what the draft would do and whether it could be published now. Calls no tool, model or provider."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="agents.read")
    agent = get_agent(db, organization_id=organization_id, agent_id=agent_id)
    configuration = dict(agent.draft_configuration)
    problems = require_publishable(configuration)
    problems += validate_access(db, organization_id=organization_id, actor_id=actor_id, configuration=configuration)
    _audit(db, organization_id=organization_id, actor_id=actor_id, action="agent.previewed", agent=agent)
    return {
        "side_effects": False,
        "publishable": not problems,
        "problems": problems,
        "plan": [_describe_step(index, step) for index, step in enumerate(configuration.get("steps", []))],
        "limits": configuration.get("limits", {}),
    }


def _describe_step(index: int, step: Mapping[str, Any]) -> dict[str, Any]:
    if step["kind"] == "tool":
        return {"index": index, "kind": "tool", "tool": step["tool"], "argument_names": sorted(step.get("arguments", {}))}
    if step["kind"] == "knowledge":
        return {"index": index, "kind": "knowledge", "top_k": step["top_k"]}
    if step["kind"] == "model":
        return {"index": index, "kind": "model", "output_keys": sorted(step["output_schema"])}
    if step["kind"] == "crm_action":
        return {"index": index, "kind": "crm_action", "action": step["action"], "argument_names": sorted(step["arguments"])}
    return {"index": index, "kind": "approval"}


def execution_metrics(db: Session, *, organization_id: UUID, actor_id: UUID, agent_id: UUID) -> dict[str, Any]:
    """Execution counts by status and the most common failure reasons for one agent. Read only."""
    _require(db, organization_id=organization_id, actor_id=actor_id, permission="agents.read")
    get_agent(db, organization_id=organization_id, agent_id=agent_id)
    scope = (AgentExecution.organization_id == organization_id, AgentExecution.agent_id == agent_id)
    by_status = {
        status: count
        for status, count in db.execute(
            select(AgentExecution.status, func.count()).where(*scope).group_by(AgentExecution.status)
        ).all()
    }
    reasons = db.execute(
        select(AgentExecution.failure_reason, func.count())
        .where(*scope, AgentExecution.failure_reason.is_not(None))
        .group_by(AgentExecution.failure_reason)
        .order_by(func.count().desc(), AgentExecution.failure_reason)
        .limit(10)
    ).all()
    return {
        "agent_id": str(agent_id),
        "total": sum(by_status.values()),
        "by_status": by_status,
        "failure_reasons": [{"reason": reason, "count": count} for reason, count in reasons],
    }

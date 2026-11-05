"""Checks that need the database and so run at publish, resume and rollback time (DFR1-023).

A workflow's configuration may name permissions, agents and a product entitlement. None of these are trusted from the configuration.
Each one is checked here against the database, for the member doing the publish, and the check fails closed: if a check cannot be
completed, the publish is refused. Permissions are never granted by a workflow.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.crm_action_catalogue import CRM_ACTIONS, QUALIFICATION_RECORD
from app.auth.dependencies import CurrentUserContext
from app.db.models.agent import Agent, AgentVersion
from app.governance import policy as governance_policy
from app.governance.capabilities import AUTOMATION_WORKFLOWS
from app.governance.execution_gate import actor_permission_granted
from app.governance.policy import (
    REASON_ALLOWED,
    REASON_CAPABILITY_DISABLED,
    REASON_MASTER_DISABLED,
    evaluate_capability,
)

# Entitlement reasons that mean the product is not licensed or cannot be verified. Switch states do not block publishing: a
# definition can be prepared while automation is off. Execution is still gated by the switches in DFR1-024.
WORKFLOW_ENTITLEMENT = "workflow_automation"
NON_BLOCKING_ENTITLEMENT_REASONS = (REASON_ALLOWED, REASON_MASTER_DISABLED, REASON_CAPABILITY_DISABLED)


def required_permissions(configuration: dict[str, Any]) -> list[str]:
    """Every permission the workflow's actions need. Recorded on the version so the requirement is visible."""
    keys: set[str] = set()
    for step in configuration.get("steps", []):
        if step["type"] == "crm_action":
            keys.update(CRM_ACTIONS[step["action"]].permissions)
        if step["type"] == "approval":
            keys.add(step["approver_permission"])
    return sorted(keys)


def agent_references(configuration: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"step": step["id"], "agent_id": step["agent_id"], "inputs": sorted(step.get("arguments") or {})}
        for step in configuration.get("steps", [])
        if step["type"] == "agent"
    ]


def publish_problems(db: Session, *, organization_id: UUID, actor_id: UUID, configuration: dict[str, Any],
                     user_context: CurrentUserContext | None = None) -> list[dict[str, str]]:
    """Problems that stop this configuration from being published or run by this member now. Empty when it may be."""
    problems: list[dict[str, str]] = []
    for step in configuration.get("steps", []):
        if step["type"] == "crm_action" and step["action"] == QUALIFICATION_RECORD:
            # Qualification results belong to an agent execution. A workflow has none to record against.
            problems.append({"path": f"steps.{step['id']}.action",
                             "message": "This action records against an agent run and cannot be used in a workflow."})
        if step["type"] == "crm_action":
            spec = CRM_ACTIONS[step["action"]]
            for permission in spec.permissions:
                if not actor_permission_granted(db, organization_id=organization_id, user_id=actor_id, permission_key=permission):
                    problems.append({"path": f"steps.{step['id']}.action",
                                     "message": f"You do not hold the permission {permission} that {spec.key} needs."})
        if step["type"] == "approval" and not actor_permission_granted(
            db, organization_id=organization_id, user_id=actor_id, permission_key=step["approver_permission"]
        ):
            problems.append({"path": f"steps.{step['id']}.approver_permission",
                             "message": "You do not hold the permission this approval step needs."})
        if step["type"] == "agent":
            problems.extend(_agent_problems(db, organization_id=organization_id, step=step))

    # The organization snapshot is checked first, before the switches: a switched-off capability must not hide an unverified licence.
    verdict = governance_policy.organization_entitlement_verdict(
        db, organization_id=organization_id, feature_key=WORKFLOW_ENTITLEMENT)
    if not verdict.allowed:
        problems.append({"path": "entitlement",
                         "message": f"Workflow automation cannot be verified for this organization ({verdict.reason_code})."})
    else:
        decision = evaluate_capability(db, organization_id=organization_id, capability_key=AUTOMATION_WORKFLOWS,
                                       user_context=user_context)
        if decision.reason_code not in NON_BLOCKING_ENTITLEMENT_REASONS:
            problems.append({"path": "entitlement",
                             "message": f"Workflow automation cannot be verified for this organization ({decision.reason_code})."})
    return problems


def _agent_problems(db: Session, *, organization_id: UUID, step: dict[str, Any]) -> list[dict[str, str]]:
    path = f"steps.{step['id']}.agent_id"
    agent = db.scalar(select(Agent).where(Agent.id == UUID(step["agent_id"]), Agent.organization_id == organization_id))
    if agent is None:
        return [{"path": path, "message": "The agent does not exist in this organization."}]
    if agent.status != Agent.STATUS_PUBLISHED or agent.current_version_id is None:
        return [{"path": path, "message": "The agent is not published and active."}]
    version = db.get(AgentVersion, agent.current_version_id)
    if version is None or version.organization_id != organization_id:
        return [{"path": path, "message": "The agent has no valid published version."}]
    declared = {item["name"] for item in version.configuration.get("inputs", []) if item.get("required")}
    provided = set((step.get("arguments") or {}).keys())
    everything = {item["name"] for item in version.configuration.get("inputs", [])}
    problems: list[dict[str, str]] = []
    if not declared <= provided:
        problems.append({"path": f"steps.{step['id']}.arguments", "message": "The agent needs inputs this step does not provide."})
    if not provided <= everything:
        problems.append({"path": f"steps.{step['id']}.arguments", "message": "The step gives an input the agent does not declare."})
    return problems

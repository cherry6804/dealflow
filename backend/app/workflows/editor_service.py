"""Templates and simulation for the workflow editor (DFR1-026).

Both operations go through the lifecycle service's own checks: the member needs the permission, the organization scope is applied to
every read, and a template only creates a draft. Simulation reads the draft and changes nothing about it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.workflows.publish_checks import publish_problems
from app.workflows.schema import require_publishable
from app.workflows.service import (
    WorkflowError,
    _audit,
    _lock_read,
    _require,
    create_workflow,
)
from app.workflows.simulation import simulate, unknown_inputs
from app.workflows.templates import template_configuration

REASON_TEMPLATE_NOT_FOUND = "template_not_found"
REASON_SIMULATION_INVALID = "simulation_invalid"


def create_from_template(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    template_key: str,
    name: str,
    description: str | None,
) -> Any:
    """Create a draft from a catalogue template. The draft goes through the same validation as any draft."""
    _require(
        db,
        organization_id=organization_id,
        actor_id=actor_id,
        permission="workflows.manage",
    )
    configuration = template_configuration(template_key)
    if configuration is None:
        raise WorkflowError(REASON_TEMPLATE_NOT_FOUND, status=404)
    workflow = create_workflow(
        db,
        organization_id=organization_id,
        actor_id=actor_id,
        name=name,
        description=description,
        configuration=configuration,
    )
    _audit(
        db,
        organization_id=organization_id,
        actor_id=actor_id,
        workflow=workflow,
        action="workflow.created_from_template",
        metadata={"template": template_key},
    )
    return workflow


def simulate_draft(
    db: Session,
    *,
    organization_id: UUID,
    actor_id: UUID,
    workflow_id: UUID,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Describe what the draft would do for the sample inputs. Nothing is executed, sent, called or written except the audit line."""
    _require(
        db,
        organization_id=organization_id,
        actor_id=actor_id,
        permission="workflows.manage",
    )
    workflow = _lock_read(db, organization_id=organization_id, workflow_id=workflow_id)
    configuration = workflow.draft_configuration
    problems: list[dict[str, str]] = require_publishable(
        configuration, name=workflow.name, description=workflow.description
    )
    if configuration.get("steps"):
        problems.extend(
            publish_problems(
                db,
                organization_id=organization_id,
                actor_id=actor_id,
                configuration=configuration,
            )
        )
    problems.extend(unknown_inputs(configuration, inputs))
    _audit(
        db,
        organization_id=organization_id,
        actor_id=actor_id,
        workflow=workflow,
        action="workflow.simulated",
        metadata={
            "revision": workflow.draft_revision,
            "valid": not problems,
            "input_names": sorted(inputs),
        },
    )
    if problems:
        return {
            "valid": False,
            "problems": problems,
            "executed": False,
            "plan": [],
            "plan_truncated": False,
            "not_performed": [],
            "revision": workflow.draft_revision,
        }
    result = simulate(configuration, inputs)
    return dict(result, valid=True, problems=[], revision=workflow.draft_revision)


__all__ = [
    "REASON_SIMULATION_INVALID",
    "REASON_TEMPLATE_NOT_FOUND",
    "create_from_template",
    "simulate_draft",
]

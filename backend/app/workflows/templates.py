"""The workflow template catalogue (DFR1-026).

A template is a starting configuration in the canonical ``workflow.v1`` shape. It is not a second definition format and it is not
trusted: creating a workflow from a template runs the same normalisation, draft storage and publish checks as any other draft. A
template only ever creates a draft. Publishing still needs the publish permission and passes every publish check.

Templates use only the CRM actions the workflow schema allows and the trigger events the runtime declares. The missed-call template
is started manually because no missed-call event is emitted by the platform yet; it says so in its purpose.
"""

from __future__ import annotations

import copy
from typing import Any

from app.agents.crm_action_catalogue import CRM_ACTIONS
from app.workflows.schema import (
    APPROVER_PERMISSIONS,
    CATEGORIES,
    CONDITION_OPERATORS,
    STEP_TYPES,
    TRIGGER_EVENTS,
)

# A workflow may not record qualification results: they belong to an agent execution. The catalogue omits it.
REFUSED_IN_WORKFLOWS = frozenset({"qualification.record"})

_LIMITS: dict[str, int] = {
    "max_steps": 10,
    "max_duration_seconds": 600,
    "max_concurrent_runs": 2,
    "max_runs_per_hour": 100,
}
_LEAD_INPUT = [{"name": "lead_id", "type": "uuid", "required": True}]


def _template(
    title: str, description: str, configuration: dict[str, Any]
) -> dict[str, Any]:
    return {"title": title, "description": description, "configuration": configuration}


TEMPLATES: dict[str, dict[str, Any]] = {
    "new_lead": _template(
        "New lead",
        "When a lead is created, calculate its priority score.",
        {
            "schema_version": "workflow.v1",
            "category": "sales",
            "purpose": "When a lead is created, calculate its priority score.",
            "trigger": {"type": "event", "event": "lead.created"},
            "inputs": _LEAD_INPUT,
            "entry": "score_lead",
            "steps": [
                {
                    "id": "score_lead",
                    "type": "crm_action",
                    "action": "lead.calculate_priority",
                    "arguments": {"lead_id": "$input.lead_id"},
                },
            ],
            "outputs": {},
            "limits": _LIMITS,
        },
    ),
    "missed_call": _template(
        "Missed call",
        "After a missed call, wait fifteen minutes and then recalculate the lead's priority.",
        {
            "schema_version": "workflow.v1",
            "category": "sales",
            "purpose": "After a missed call, wait fifteen minutes and then recalculate the lead's priority. Started manually: "
            "the platform does not emit a missed-call event yet.",
            "trigger": {"type": "manual"},
            "inputs": _LEAD_INPUT,
            "entry": "wait_before_rescore",
            "steps": [
                {
                    "id": "wait_before_rescore",
                    "type": "delay",
                    "seconds": 900,
                    "next": "rescore_lead",
                },
                {
                    "id": "rescore_lead",
                    "type": "crm_action",
                    "action": "lead.calculate_priority",
                    "arguments": {"lead_id": "$input.lead_id"},
                },
            ],
            "outputs": {},
            "limits": _LIMITS,
        },
    ),
    "follow_up": _template(
        "Follow-up",
        "When a lead is updated, a member confirms the follow-up before the lead is rescored.",
        {
            "schema_version": "workflow.v1",
            "category": "sales",
            "purpose": "When a lead is updated, a member confirms the follow-up before the lead is rescored.",
            "trigger": {"type": "event", "event": "lead.updated"},
            "inputs": _LEAD_INPUT,
            "entry": "confirm_follow_up",
            "steps": [
                {
                    "id": "confirm_follow_up",
                    "type": "approval",
                    "approver_permission": "leads.update",
                    "reason": "Confirm the follow-up before the lead is rescored.",
                    "next": "rescore_lead",
                },
                {
                    "id": "rescore_lead",
                    "type": "crm_action",
                    "action": "lead.calculate_priority",
                    "arguments": {"lead_id": "$input.lead_id"},
                },
            ],
            "outputs": {},
            "limits": _LIMITS,
        },
    ),
    "site_visit": _template(
        "Site visit",
        "When a site visit is scheduled, recalculate the lead's priority score.",
        {
            "schema_version": "workflow.v1",
            "category": "sales",
            "purpose": "When a site visit is scheduled, recalculate the lead's priority score.",
            "trigger": {"type": "event", "event": "site_visit.scheduled"},
            "inputs": _LEAD_INPUT,
            "entry": "score_lead",
            "steps": [
                {
                    "id": "score_lead",
                    "type": "crm_action",
                    "action": "lead.calculate_priority",
                    "arguments": {"lead_id": "$input.lead_id"},
                },
            ],
            "outputs": {},
            "limits": _LIMITS,
        },
    ),
}


def catalogue() -> dict[str, Any]:
    """The choices the editor offers. Every value here is one the schema accepts."""
    return {
        "step_types": list(STEP_TYPES),
        "crm_actions": sorted(
            key for key in CRM_ACTIONS if key not in REFUSED_IN_WORKFLOWS
        ),
        "approver_permissions": list(APPROVER_PERMISSIONS),
        "trigger_events": list(TRIGGER_EVENTS),
        "condition_operators": list(CONDITION_OPERATORS),
        "categories": list(CATEGORIES),
    }


def template_summaries() -> list[dict[str, str]]:
    return [
        {"key": key, "title": item["title"], "description": item["description"]}
        for key, item in TEMPLATES.items()
    ]


def template_configuration(key: str) -> dict[str, Any] | None:
    """A fresh copy of a template's configuration, so a caller can never change the catalogue."""
    item = TEMPLATES.get(key)
    return copy.deepcopy(item["configuration"]) if item is not None else None


__all__ = ["TEMPLATES", "catalogue", "template_configuration", "template_summaries"]

"""Approved agent templates for lead intake and qualification (DFR1-021).

A template is a starting configuration, not executable code. Creating an agent from a template stores an ordinary draft, which
then goes through the same validation, publishing and execution rules as any other agent. A template names no permission, and an
agent never gains one from its template: every action checks the initiating member's permissions.

None of these templates sends a message or places a call. Customer communication is not part of this release's agents.
"""

from __future__ import annotations

from typing import Any

from app.agents.crm_action_catalogue import (
    INTAKE_PROCESS,
    INTAKE_RESOLVE_IDENTITY,
    LEAD_CALCULATE_PRIORITY,
    QUALIFICATION_RECORD,
)

RECEPTIONIST = "lead_receptionist"
IDENTITY_RESOLVER = "identity_resolver"
LEAD_SCORING = "lead_scoring"
QUALIFICATION = "lead_qualification"

_LIMITS: dict[str, int] = {
    "max_duration_seconds": 120,
    "max_steps": 6,
    "max_tool_calls": 1,
    "max_retries": 1,
    "max_output_characters": 4_000,
    "max_concurrent_executions": 2,
    "max_executions_per_hour": 100,
}


def _template(*, key: str, title: str, purpose: str, instructions: str, inputs: list[dict[str, Any]],
              steps: list[dict[str, Any]], tools: list[str]) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "configuration": {
            "category": "operations" if key != QUALIFICATION else "sales",
            "purpose": purpose,
            "instructions": instructions,
            "language": "en",
            "model_task": "text",
            "autonomy_level": "act",
            "approval_policy": "none",
            "trigger": {"type": "manual"},
            "tools": tools,
            "knowledge_document_ids": [],
            "inputs": inputs,
            "steps": steps,
            "limits": dict(_LIMITS),
        },
    }


TEMPLATES: dict[str, dict[str, Any]] = {
    RECEPTIONIST: _template(
        key=RECEPTIONIST,
        title="Lead receptionist",
        purpose="Capture an inbound enquiry as a CRM lead without guessing who the person is.",
        instructions="Process the stored enquiry through the intake service. Create a contact or lead only where the identity is "
                     "clear. Uncertain identities are left for a person to decide.",
        inputs=[{"name": "submission_id", "type": "uuid", "required": True}],
        steps=[{"kind": "crm_action", "action": INTAKE_PROCESS, "arguments": {"submission_id": "$input.submission_id"}}],
        tools=[],
    ),
    IDENTITY_RESOLVER: _template(
        key=IDENTITY_RESOLVER,
        title="Identity resolver",
        purpose="Report which existing contacts an enquiry may belong to, without changing any record.",
        instructions="Compare the stored enquiry with existing contacts and report the outcome. This agent never writes to the CRM.",
        inputs=[{"name": "submission_id", "type": "uuid", "required": True}],
        steps=[{"kind": "crm_action", "action": INTAKE_RESOLVE_IDENTITY,
                "arguments": {"submission_id": "$input.submission_id"}}],
        tools=[],
    ),
    LEAD_SCORING: _template(
        key=LEAD_SCORING,
        title="Lead scoring",
        purpose="Calculate and store the explainable priority of one lead using the approved scoring rules.",
        instructions="Run the DFR1-020 priority calculation for the lead. Report the score, band and method as stored.",
        inputs=[{"name": "lead_id", "type": "uuid", "required": True}],
        steps=[{"kind": "crm_action", "action": LEAD_CALCULATE_PRIORITY, "arguments": {"lead_id": "$input.lead_id"}}],
        tools=[],
    ),
    QUALIFICATION: _template(
        key=QUALIFICATION,
        title="Lead qualification",
        purpose="Qualify one lead: read its record, score it, suggest a next action, and record structured findings for review.",
        instructions="Use the stored score and the lead record. Facts come from the CRM. Any suggestion you give is unverified, "
                     "and a person reviews it before it is relied on.",
        inputs=[{"name": "lead_id", "type": "uuid", "required": True}],
        steps=[
            {"kind": "tool", "tool": "leads.get", "arguments": {"lead_id": "$input.lead_id"}},
            {"kind": "crm_action", "action": LEAD_CALCULATE_PRIORITY, "arguments": {"lead_id": "$input.lead_id"}},
            {"kind": "model",
             "prompt": "Suggest one next action for this lead in one short sentence. Use only the data block. Do not state any "
                       "fact that is not in it.",
             "output_schema": {"next_action": "string"}},
            {"kind": "crm_action", "action": QUALIFICATION_RECORD,
             "arguments": {"lead_id": "$input.lead_id", "score_id": "$step.1.score_id",
                           "suggestion": "$step.2.next_action"}},
        ],
        tools=["leads.get"],
    ),
}


def template_summaries() -> list[dict[str, Any]]:
    return [{"key": key, "title": item["title"], "purpose": item["configuration"]["purpose"],
             "tools": item["configuration"]["tools"], "steps": len(item["configuration"]["steps"])}
            for key, item in TEMPLATES.items()]

"""Dry-run simulation of a workflow draft (DFR1-026).

The simulation reads a validated configuration and describes the path a run would take. It is pure: it never calls the runtime, the
CRM action runner, an agent, the outbox, the approval gate or a provider, and it never writes a run, a task or a customer record. Every
result says ``executed: false`` and lists what was not performed.

Where a value is known from the supplied sample input, a condition is evaluated. Where it is not, both branches are shown. Approval
gates and explicit approval steps are shown as waiting, and the steps after them are shown as assuming the approval is granted; no
decision is made.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

MAX_PLAN_ENTRIES = 100
INPUT_REFERENCE = re.compile(r"^\$input\.([a-z][a-z0-9_]{0,39})$")
STEP_REFERENCE = re.compile(r"^\$steps\.[a-z][a-z0-9_]{0,39}\.[a-z][a-z0-9_]{0,39}$")

NOT_PERFORMED = [
    "CRM actions were not run and no CRM record was changed.",
    "No agent was run.",
    "No approval task was created and no decision was recorded.",
    "No run, outbox event, notification or audit trail of a run was created.",
    "No message, call, email or other communication was sent.",
    "No external provider or AI model was called and no AI budget was used.",
]


def _resolve_argument(value: object, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, str):
        match = INPUT_REFERENCE.match(value)
        if match:
            name = match.group(1)
            if name in inputs:
                return {"value": inputs[name], "source": "sample input"}
            return {"value": None, "source": f"input {name} not supplied"}
        if STEP_REFERENCE.match(value):
            return {
                "value": None,
                "source": "output of an earlier step, known only at run time",
            }
    return {"value": value, "source": "literal"}


def _evaluate(condition: Mapping[str, Any], inputs: Mapping[str, Any]) -> bool | None:
    """True or False when the left side is a supplied input, otherwise None (unknown until the run)."""
    match = INPUT_REFERENCE.match(str(condition.get("left", "")))
    if match is None or match.group(1) not in inputs:
        return None
    left = inputs[match.group(1)]
    operator = condition.get("operator")
    right = condition.get("right")
    try:
        if operator == "exists":
            return left is not None
        if operator == "eq":
            return left == right
        if operator == "neq":
            return left != right
        if operator == "in":
            return left in (right or [])
        if operator == "not_in":
            return left not in (right or [])
        if operator == "gt":
            return left > right
        if operator == "gte":
            return left >= right
        if operator == "lt":
            return left < right
        if operator == "lte":
            return left <= right
    except TypeError:
        return None
    return None


def _entry(step: Mapping[str, Any], branch: str, outcome: str) -> dict[str, Any]:
    return {
        "step_id": step["id"],
        "type": step["type"],
        "branch": branch,
        "outcome": outcome,
    }


def _walk(
    steps: Mapping[str, Mapping[str, Any]],
    step_id: str | None,
    inputs: Mapping[str, Any],
    branch: str,
    seen: frozenset[str],
    plan: list[dict[str, Any]],
) -> None:
    if step_id is None or len(plan) >= MAX_PLAN_ENTRIES:
        return
    step = steps.get(step_id)
    if step is None or step_id in seen:
        return
    seen = seen | {step_id}
    kind = step["type"]
    approval = step.get("approval") or (
        {
            "approver_permission": step.get("approver_permission"),
            "expires_after_seconds": step.get("expires_after_seconds"),
        }
        if kind == "approval"
        else None
    )

    if kind == "condition":
        result = _evaluate(step.get("condition") or {}, inputs)
        if result is True:
            plan.append(dict(_entry(step, branch, "branch_taken"), taken="then"))
            _walk(steps, step.get("then"), inputs, branch, seen, plan)
        elif result is False:
            plan.append(dict(_entry(step, branch, "branch_taken"), taken="else"))
            _walk(steps, step.get("else"), inputs, branch, seen, plan)
        else:
            plan.append(dict(_entry(step, branch, "branch_unknown"), taken="either"))
            _walk(steps, step.get("then"), inputs, f"{branch} > then", seen, plan)
            _walk(steps, step.get("else"), inputs, f"{branch} > else", seen, plan)
        return

    if kind == "delay":
        plan.append(
            dict(_entry(step, branch, "would_wait"), seconds=step.get("seconds"))
        )
    elif kind == "approval":
        plan.append(
            dict(
                _entry(step, branch, "would_wait_for_approval"),
                approver_permission=step.get("approver_permission"),
                expires_after_seconds=step.get("expires_after_seconds"),
                assumes="approval granted",
            )
        )
    else:
        arguments = {
            name: _resolve_argument(value, inputs)
            for name, value in (step.get("arguments") or {}).items()
        }
        target = step.get("action") if kind == "crm_action" else step.get("agent_id")
        outcome = "would_run" if approval is None else "would_wait_for_approval"
        extra: dict[str, Any] = {"target": target, "arguments": arguments}
        if approval is not None:
            extra.update(
                approver_permission=approval.get("approver_permission"),
                expires_after_seconds=approval.get("expires_after_seconds"),
                assumes="approval granted",
            )
        plan.append(dict(_entry(step, branch, outcome), **extra))
    _walk(steps, step.get("next"), inputs, branch, seen, plan)


def simulate(
    configuration: Mapping[str, Any], inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Describe the path of a validated configuration for the sample inputs. Nothing is executed."""
    steps = {step["id"]: step for step in configuration.get("steps", [])}
    plan: list[dict[str, Any]] = []
    _walk(steps, configuration.get("entry"), inputs, "main", frozenset(), plan)
    return {
        "executed": False,
        "plan": plan,
        "plan_truncated": len(plan) >= MAX_PLAN_ENTRIES,
        "not_performed": list(NOT_PERFORMED),
    }


def unknown_inputs(
    configuration: Mapping[str, Any], inputs: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Problems with the sample input: names the workflow does not declare, and required inputs that are missing."""
    declared = {item["name"]: item for item in configuration.get("inputs", [])}
    problems = [
        {
            "path": f"input.{name}",
            "message": "The workflow does not declare this input.",
        }
        for name in sorted(set(inputs) - set(declared))
    ]
    problems.extend(
        {"path": f"input.{name}", "message": "A required input is missing."}
        for name, item in sorted(declared.items())
        if item.get("required") and name not in inputs
    )
    return problems

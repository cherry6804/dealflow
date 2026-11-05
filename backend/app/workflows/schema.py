"""Typed, versioned workflow definitions (DFR1-023). Pure: no database access.

A workflow definition is plain JSON with a fixed shape (``workflow.v1``). Every object is checked against its allowed fields, so an
unknown field is rejected at any depth, and no field can carry code, a SQL fragment, an expression or an import path. This story
defines the schema and its validation. It does not execute workflows: the runtime, the trigger engine and timers belong to DFR1-024.

Step types (only these, each with a fixed configuration):

- ``crm_action``: one key from the CRM action catalogue shared with agents. Its arguments are references only.
- ``condition``: compares one reference with one literal from a fixed operator list, and branches to ``then`` or ``else``.
- ``agent``: invokes one published agent of the same organization, with inputs given as references.
- ``approval``: waits for a member with a named approval permission. The decision is taken by the runtime later.
- ``delay``: waits for a bounded number of seconds.

Structure: step identifiers are explicit and unique. Every branch target exists, every step is reachable from the entry step, the
graph has no cycle, and a reference may only name a step that comes before it on every path.

Everything here is a check on the configuration. Publishing also checks the things that live in the database (permissions, agent
state, product entitlement) in ``app/workflows/publish_checks.py``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.agents.crm_action_catalogue import CRM_ACTIONS

SCHEMA_VERSION = "workflow.v1"

CATEGORIES = ("sales", "operations", "research")
TRIGGER_MANUAL = "manual"
TRIGGER_EVENT = "event"
# Event names a trigger may declare. Declaring one is allowed; a trigger only fires once DFR1-024 provides the runtime.
TRIGGER_EVENTS = ("lead.created", "lead.updated", "site_visit.scheduled", "deal.created")
INPUT_TYPES = ("uuid", "string", "integer", "boolean")
STEP_TYPES = ("crm_action", "condition", "agent", "approval", "delay")
CONDITION_OPERATORS = ("eq", "neq", "in", "not_in", "exists", "gt", "gte", "lt", "lte")
ORDERED_OPERATORS = ("gt", "gte", "lt", "lte")
APPROVER_PERMISSIONS = ("leads.update", "requirements.update", "agents.approve")
FAILURE_POLICIES = ("stop", "route")

MAX_INPUTS = 10
MAX_OUTPUTS = 10
MAX_STEPS = 50
MAX_LABELS = 10
MAX_NAME = 120
MAX_DESCRIPTION = 1000
MAX_PURPOSE = 500
MAX_REASON = 500
MAX_LITERAL = 200
MAX_LIST_LITERAL = 20
MAX_RETRY_ATTEMPTS = 3
MAX_BACKOFF_SECONDS = 300
MAX_TIMEOUT_SECONDS = 900
MAX_DELAY_SECONDS = 604_800

# Hard ceilings. A workflow may ask for less, never more.
LIMIT_CEILINGS: dict[str, int] = {
    "max_duration_seconds": 86_400,
    "max_steps": MAX_STEPS,
    "max_concurrent_runs": 10,
    "max_runs_per_hour": 10_000,
}
LIMIT_FLOORS: dict[str, int] = {key: 1 for key in LIMIT_CEILINGS}

TOP_LEVEL_FIELDS = frozenset({
    "schema_version", "category", "purpose", "trigger", "inputs", "entry", "steps", "outputs", "limits", "metadata",
})
STEP_COMMON_FIELDS = frozenset({"id", "type", "next", "timeout_seconds", "retry", "on_failure"})

# Output contract of each CRM action: the fields a later step may reference. Agent steps accept any field name, because their output
# schema is defined by the agent version and is checked when the workflow is published.
CRM_ACTION_OUTPUTS: dict[str, tuple[str, ...]] = {
    "intake.process": ("submission_id", "status", "match_outcome", "lead_id"),
    "intake.resolve_identity": ("submission_id", "outcome", "candidate_count"),
    "lead.calculate_priority": ("score_id", "score", "band", "method", "confidence", "insufficient_data", "ruleset_version"),
    "qualification.record": ("qualification_id", "requires_review", "created"),
    "matching.evaluate": ("run_id", "created", "ruleset_version"),
}
APPROVAL_OUTPUTS: tuple[str, ...] = ("decision",)

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_STEP_FIELD_REF = re.compile(r"^\$steps\.([a-z][a-z0-9_]{0,39})\.([a-z][a-z0-9_]{0,39})$")
_INPUT_REF = re.compile(r"^\$input\.([a-z][a-z0-9_]{0,39})$")
_LABEL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class WorkflowValidationError(ValueError):
    """The configuration breaks the schema. Each problem names its location and never echoes a stored value."""

    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__("; ".join(item["message"] for item in problems))
        self.problems = problems


class _Problems:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, path: str, message: str) -> None:
        self.items.append({"path": path, "message": message})


def _object(value: object, path: str, allowed: frozenset[str] | set[str], problems: _Problems) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        problems.add(path, "Must be an object.")
        return None
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        problems.add(path, f"Unknown field(s) are not allowed: {', '.join(unknown)}.")
        return None
    return value


def _text(value: object, path: str, limit: int, problems: _Problems, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            problems.add(path, "Is required.")
        return None
    if not isinstance(value, str):
        problems.add(path, "Must be text.")
        return None
    if len(value) > limit:
        problems.add(path, f"Must be {limit} characters or fewer.")
        return None
    return value


def _integer(value: object, path: str, floor: int, ceiling: int, problems: _Problems) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        problems.add(path, "Must be an integer.")
        return None
    if not floor <= value <= ceiling:
        problems.add(path, f"Must be between {floor} and {ceiling}.")
        return None
    return value


def _choice(value: object, path: str, options: tuple[str, ...], problems: _Problems) -> str | None:
    if not isinstance(value, str) or value not in options:
        problems.add(path, f"Must be one of: {', '.join(options)}.")
        return None
    return value


def _identifier(value: object, path: str, problems: _Problems, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        problems.add(path, "Must be lower case letters, digits and underscores, starting with a letter, 40 characters or fewer.")
        return None
    return value


def _literal(value: object, path: str, operator: str, problems: _Problems) -> Any:
    if operator == "exists":
        if value is not None:
            problems.add(path, "Must be omitted for the exists operator.")
        return None
    if operator in ("in", "not_in"):
        if not isinstance(value, list) or not value or len(value) > MAX_LIST_LITERAL:
            problems.add(path, f"Must be a non-empty list of up to {MAX_LIST_LITERAL} values.")
            return None
        if not all(isinstance(item, str) and len(item) <= MAX_LITERAL for item in value):
            problems.add(path, "List values must be short text.")
            return None
        return list(value)
    if operator in ORDERED_OPERATORS:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.add(path, "Must be a number for this operator.")
            return None
        return value
    if isinstance(value, (bool, int, str)):
        if isinstance(value, str) and len(value) > MAX_LITERAL:
            problems.add(path, f"Must be {MAX_LITERAL} characters or fewer.")
            return None
        return value
    problems.add(path, "Must be short text, a whole number or a boolean.")
    return None


def _reference(value: object, path: str, *, input_names: set[str], problems: _Problems) -> str | None:
    """A reference to a declared input or to an output field of a step. Anything else is refused."""
    if not isinstance(value, str):
        problems.add(path, "Must be a reference such as $input.name or $steps.step_id.field.")
        return None
    input_match = _INPUT_REF.fullmatch(value)
    if input_match is not None:
        if input_match.group(1) not in input_names:
            problems.add(path, "Refers to an input that is not declared.")
            return None
        return value
    if _STEP_FIELD_REF.fullmatch(value) is not None:
        return value
    problems.add(path, "Must be a reference such as $input.name or $steps.step_id.field.")
    return None


def _arguments(raw: object, path: str, allowed: tuple[str, ...], required: tuple[str, ...], *, input_names: set[str],
               problems: _Problems) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        problems.add(path, "Must be an object of argument references.")
        return None
    clean: dict[str, str] = {}
    for name, value in raw.items():
        if name not in allowed:
            problems.add(f"{path}.{name}", "This argument is not accepted by this step.")
            continue
        ref = _reference(value, f"{path}.{name}", input_names=input_names, problems=problems)
        if ref is not None:
            clean[name] = ref
    for name in required:
        if name not in clean:
            problems.add(path, f"Missing required argument: {name}.")
    return clean


def _normalise_step(raw: object, index: int, *, input_names: set[str], problems: _Problems) -> dict[str, Any] | None:
    path = f"steps[{index}]"
    if not isinstance(raw, dict):
        problems.add(path, "Must be an object.")
        return None
    step_type = raw.get("type")
    if step_type not in STEP_TYPES:
        problems.add(f"{path}.type", f"Must be one of: {', '.join(STEP_TYPES)}.")
        return None
    extra_fields = {
        "crm_action": {"action", "arguments"},
        "condition": {"condition", "then", "else"},
        "agent": {"agent_id", "arguments"},
        "approval": {"approver_permission", "reason"},
        "delay": {"seconds"},
    }[step_type]
    if step_type == "condition":
        allowed = STEP_COMMON_FIELDS - {"next", "retry", "timeout_seconds"} | extra_fields
    else:
        allowed = STEP_COMMON_FIELDS | extra_fields
    data = _object(raw, path, allowed, problems)
    if data is None:
        return None
    step_id = _identifier(data.get("id"), f"{path}.id", problems)
    clean: dict[str, Any] = {"id": step_id, "type": step_type}

    if step_type != "condition":
        clean["next"] = _identifier(data.get("next"), f"{path}.next", problems, required=False)
        timeout = data.get("timeout_seconds", 60)
        clean["timeout_seconds"] = _integer(timeout, f"{path}.timeout_seconds", 1, MAX_TIMEOUT_SECONDS, problems)
        retry = data.get("retry", {"max_attempts": 1, "backoff_seconds": 1})
        retry_data = _object(retry, f"{path}.retry", {"max_attempts", "backoff_seconds"}, problems)
        if retry_data is not None:
            attempts = _integer(retry_data.get("max_attempts", 1), f"{path}.retry.max_attempts", 1, MAX_RETRY_ATTEMPTS, problems)
            backoff = _integer(retry_data.get("backoff_seconds", 1), f"{path}.retry.backoff_seconds", 1, MAX_BACKOFF_SECONDS,
                               problems)
            if attempts is not None and backoff is not None:
                clean["retry"] = {"max_attempts": attempts, "backoff_seconds": backoff}
        if step_type == "delay" and clean.get("retry", {}).get("max_attempts", 1) != 1:
            problems.add(f"{path}.retry", "A delay step is not retried.")
    else:
        if "retry" in data or "timeout_seconds" in data or "next" in data:
            problems.add(path, "A condition step has no retry, timeout or next field. Use then and else.")

    failure = data.get("on_failure", {"policy": "stop"})
    failure_data = _object(failure, f"{path}.on_failure", {"policy", "route_to"}, problems)
    if failure_data is not None and step_type != "condition":
        policy = _choice(failure_data.get("policy", "stop"), f"{path}.on_failure.policy", FAILURE_POLICIES, problems)
        route_to = _identifier(failure_data.get("route_to"), f"{path}.on_failure.route_to", problems, required=False)
        if policy == "route" and route_to is None:
            problems.add(f"{path}.on_failure", "A route policy needs route_to.")
        if policy == "stop" and route_to is not None:
            problems.add(f"{path}.on_failure", "A stop policy must not name route_to.")
        if policy is not None:
            clean["on_failure"] = {"policy": policy, "route_to": route_to}

    if step_type == "crm_action":
        action = data.get("action")
        spec = CRM_ACTIONS.get(action) if isinstance(action, str) else None
        if spec is None:
            problems.add(f"{path}.action", "Must be an approved CRM action.")
        else:
            args = _arguments(data.get("arguments"), f"{path}.arguments",
                              spec.required_arguments + spec.optional_arguments, spec.required_arguments,
                              input_names=input_names, problems=problems)
            clean["action"] = action
            clean["arguments"] = args
    elif step_type == "condition":
        condition = _object(data.get("condition"), f"{path}.condition", {"left", "operator", "right"}, problems)
        if condition is not None:
            left = _reference(condition.get("left"), f"{path}.condition.left", input_names=input_names, problems=problems)
            operator = _choice(condition.get("operator"), f"{path}.condition.operator", CONDITION_OPERATORS, problems)
            right = _literal(condition.get("right"), f"{path}.condition.right", operator or "eq", problems) \
                if operator else None
            if left is not None and operator is not None:
                clean["condition"] = {"left": left, "operator": operator, "right": right}
        clean["then"] = _identifier(data.get("then"), f"{path}.then", problems)
        clean["else"] = _identifier(data.get("else"), f"{path}.else", problems)
    elif step_type == "agent":
        agent_id = data.get("agent_id")
        try:
            clean["agent_id"] = str(UUID(str(agent_id)))
        except (TypeError, ValueError):
            problems.add(f"{path}.agent_id", "Must be an agent identifier.")
        clean["arguments"] = _agent_inputs(data.get("arguments", {}), f"{path}.arguments", input_names, problems)
    elif step_type == "approval":
        clean["approver_permission"] = _choice(data.get("approver_permission"), f"{path}.approver_permission",
                                               APPROVER_PERMISSIONS, problems)
        clean["reason"] = _text(data.get("reason"), f"{path}.reason", MAX_REASON, problems, required=True)
    elif step_type == "delay":
        clean["seconds"] = _integer(data.get("seconds"), f"{path}.seconds", 1, MAX_DELAY_SECONDS, problems)
    return clean


def _agent_inputs(raw: object, path: str, input_names: set[str], problems: _Problems) -> dict[str, str] | None:
    """Inputs passed to an agent: each is a reference. The names are checked against the agent at publish time."""
    if not isinstance(raw, dict):
        problems.add(path, "Must be an object of input references.")
        return None
    clean: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
            problems.add(path, "An agent input name must be lower case letters, digits and underscores.")
            continue
        ref = _reference(value, f"{path}.{name}", input_names=input_names, problems=problems)
        if ref is not None:
            clean[name] = ref
    return clean


def _graph_problems(steps: list[dict[str, Any]], entry: str | None, problems: _Problems) -> None:
    ids = [step["id"] for step in steps]
    if len(set(ids)) != len(ids):
        problems.add("steps", "Step identifiers must be unique.")
    by_id = {step["id"]: step for step in steps if step.get("id")}
    if not steps:
        return
    if entry is None or entry not in by_id:
        problems.add("entry", "Entry must name one of the steps.")
        return

    def targets(step: dict[str, Any]) -> list[tuple[str, str]]:
        edges: list[tuple[str, str]] = []
        if step["type"] == "condition":
            edges += [("then", step.get("then")), ("else", step.get("else"))]
        else:
            edges.append(("next", step.get("next")))
            failure = step.get("on_failure") or {}
            if failure.get("policy") == "route":
                edges.append(("on_failure.route_to", failure.get("route_to")))
        return [(label, target) for label, target in edges if target is not None]

    for step in steps:
        for label, target in targets(step):
            if target not in by_id:
                problems.add(f"steps.{step['id']}.{label}", "Points to a step that does not exist.")

    # Cycles: a workflow is a directed acyclic graph.
    state: dict[str, int] = {}

    def visit(node: str) -> bool:
        state[node] = 1
        for _label, target in targets(by_id[node]):
            if target not in by_id:
                continue
            if state.get(target) == 1:
                return True
            if state.get(target) is None and visit(target):
                return True
        state[node] = 2
        return False

    if visit(entry):
        problems.add("steps", "The workflow contains a cycle. A workflow must not loop back to an earlier step.")

    reachable: set[str] = set()
    stack = [entry]
    while stack:
        node = stack.pop()
        if node in reachable or node not in by_id:
            continue
        reachable.add(node)
        stack.extend(target for _label, target in targets(by_id[node]))
    for step_id in ids:
        if step_id not in reachable:
            problems.add(f"steps.{step_id}", "This step cannot be reached from the entry step.")


def _ancestors(steps: list[dict[str, Any]]) -> dict[str, set[str]]:
    """For each step, the steps that can run before it on some path."""
    parents: dict[str, set[str]] = {step["id"]: set() for step in steps}
    for step in steps:
        targets = []
        if step["type"] == "condition":
            targets = [step.get("then"), step.get("else")]
        else:
            targets = [step.get("next")]
            failure = step.get("on_failure") or {}
            if failure.get("policy") == "route":
                targets.append(failure.get("route_to"))
        for target in targets:
            if target in parents:
                parents[target].add(step["id"])
    result: dict[str, set[str]] = {}

    def collect(node: str, seen: set[str]) -> set[str]:
        if node in result:
            return result[node]
        found: set[str] = set()
        for parent in parents[node]:
            if parent in seen:
                continue
            found.add(parent)
            found |= collect(parent, seen | {parent})
        result[node] = found
        return found

    for step in steps:
        collect(step["id"], {step["id"]})
    return result


def _output_fields(step: dict[str, Any]) -> tuple[str, ...] | None:
    """The fields a step outputs, or None when any field name is accepted (agent steps)."""
    if step["type"] == "crm_action":
        return CRM_ACTION_OUTPUTS.get(step.get("action") or "", ())
    if step["type"] == "approval":
        return APPROVAL_OUTPUTS
    if step["type"] == "agent":
        return None
    return ()


def _reference_order_problems(steps: list[dict[str, Any]], problems: _Problems) -> None:
    ancestors = _ancestors(steps)
    by_id = {step["id"]: step for step in steps}
    for step in steps:
        refs: list[tuple[str, str]] = []
        if step["type"] == "crm_action":
            refs += [(f"steps.{step['id']}.arguments", value) for value in (step.get("arguments") or {}).values()]
        if step["type"] == "agent":
            refs += [(f"steps.{step['id']}.arguments", value) for value in (step.get("arguments") or {}).values()]
        if step["type"] == "condition" and step.get("condition"):
            refs.append((f"steps.{step['id']}.condition.left", step["condition"]["left"]))
        for path, value in refs:
            match = _STEP_FIELD_REF.fullmatch(value)
            if match is None:
                continue
            referenced = match.group(1)
            if referenced == step["id"] or referenced not in ancestors.get(step["id"], set()):
                problems.add(path, "Refers to a step that does not run before this one on every path to it.")
                continue
            fields = _output_fields(by_id[referenced])
            if fields is not None and match.group(2) not in fields:
                problems.add(path, f"Refers to a field that step '{referenced}' does not output.")


def normalise_workflow_configuration(raw: object) -> dict[str, Any]:
    """Return the canonical configuration, or raise ``WorkflowValidationError`` listing every problem found.

    A draft may have no steps yet. Publishing requires a complete configuration (see ``require_publishable``).
    """
    problems = _Problems()
    data = _object(raw, "configuration", TOP_LEVEL_FIELDS, problems)
    if data is None:
        raise WorkflowValidationError(problems.items)

    if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        problems.add("schema_version", f"Must be {SCHEMA_VERSION}.")
    category = data.get("category")
    if category is not None:
        _choice(category, "category", CATEGORIES, problems)
    purpose = _text(data.get("purpose"), "purpose", MAX_PURPOSE, problems)

    trigger_raw = data.get("trigger", {"type": TRIGGER_MANUAL})
    trigger: dict[str, Any] | None = None
    trigger_data = _object(trigger_raw, "trigger", {"type", "event"}, problems)
    if trigger_data is not None:
        trigger_type = _choice(trigger_data.get("type"), "trigger.type", (TRIGGER_MANUAL, TRIGGER_EVENT), problems)
        if trigger_type == TRIGGER_MANUAL:
            if "event" in trigger_data:
                problems.add("trigger", "A manual trigger has no event.")
            trigger = {"type": TRIGGER_MANUAL}
        elif trigger_type == TRIGGER_EVENT:
            event = _choice(trigger_data.get("event"), "trigger.event", TRIGGER_EVENTS, problems)
            trigger = {"type": TRIGGER_EVENT, "event": event} if event is not None else None

    raw_inputs = data.get("inputs", [])
    inputs: list[dict[str, Any]] = []
    input_names: set[str] = set()
    if not isinstance(raw_inputs, list) or len(raw_inputs) > MAX_INPUTS:
        problems.add("inputs", f"Must be a list of at most {MAX_INPUTS} inputs.")
    else:
        for index, item in enumerate(raw_inputs):
            path = f"inputs[{index}]"
            item_data = _object(item, path, {"name", "type", "required"}, problems)
            if item_data is None:
                continue
            name = _identifier(item_data.get("name"), f"{path}.name", problems)
            if name is not None and name in input_names:
                problems.add(f"{path}.name", "Input names must be unique.")
                continue
            input_type = _choice(item_data.get("type"), f"{path}.type", INPUT_TYPES, problems)
            required = item_data.get("required", True)
            if not isinstance(required, bool):
                problems.add(f"{path}.required", "Must be true or false.")
                continue
            if name is not None and input_type is not None:
                input_names.add(name)
                inputs.append({"name": name, "type": input_type, "required": required})

    raw_steps = data.get("steps", [])
    steps: list[dict[str, Any]] = []
    if not isinstance(raw_steps, list) or len(raw_steps) > MAX_STEPS:
        problems.add("steps", f"Must be a list of at most {MAX_STEPS} steps.")
    else:
        for index, item in enumerate(raw_steps):
            clean = _normalise_step(item, index, input_names=input_names, problems=problems)
            if clean is not None:
                steps.append(clean)
    entry = _identifier(data.get("entry"), "entry", problems, required=False) if "entry" in data else None
    if steps and "entry" not in data:
        problems.add("entry", "Entry must name the first step.")
    if steps and len(steps) == len(raw_steps):
        _graph_problems(steps, entry, problems)
        _reference_order_problems(steps, problems)

    raw_outputs = data.get("outputs", {})
    outputs: dict[str, str] = {}
    if not isinstance(raw_outputs, dict) or len(raw_outputs) > MAX_OUTPUTS:
        problems.add("outputs", f"Must be an object of at most {MAX_OUTPUTS} output references.")
    else:
        for name, value in raw_outputs.items():
            if not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
                problems.add("outputs", "Output names must be lower case letters, digits and underscores.")
                continue
            ref = _reference(value, f"outputs.{name}", input_names=input_names, problems=problems)
            if ref is not None:
                outputs[name] = ref

    limits_data = _object(data.get("limits", {}), "limits", set(LIMIT_CEILINGS), problems)
    limits: dict[str, int] = {}
    for key, value in (limits_data or {}).items():
        checked = _integer(value, f"limits.{key}", LIMIT_FLOORS[key], LIMIT_CEILINGS[key], problems)
        if checked is not None:
            limits[key] = checked
    if "max_steps" in limits and len(steps) > limits["max_steps"]:
        problems.add("limits.max_steps", "The workflow has more steps than this limit allows.")

    metadata_data = _object(data.get("metadata", {}), "metadata", {"labels"}, problems)
    labels: list[str] = []
    if metadata_data is not None:
        raw_labels = metadata_data.get("labels", [])
        if not isinstance(raw_labels, list) or len(raw_labels) > MAX_LABELS:
            problems.add("metadata.labels", f"Must be a list of at most {MAX_LABELS} labels.")
        else:
            for label in raw_labels:
                if isinstance(label, str) and _LABEL.fullmatch(label):
                    labels.append(label)
                else:
                    problems.add("metadata.labels", "Each label must be lower case letters, digits, dashes or underscores.")

    if problems.items:
        raise WorkflowValidationError(problems.items)
    return {
        "schema_version": SCHEMA_VERSION,
        "category": category,
        "purpose": purpose,
        "trigger": trigger,
        "inputs": inputs,
        "entry": entry,
        "steps": steps,
        "outputs": outputs,
        "limits": limits,
        "metadata": {"labels": sorted(set(labels))},
    }


def require_publishable(configuration: Mapping[str, Any], *, name: str | None, description: str | None = None) -> list[dict[str, str]]:
    """Problems that stop a draft from being published. An empty list means it may be published."""
    problems: list[dict[str, str]] = []
    if not name or not name.strip():
        problems.append({"path": "name", "message": "A name is required to publish."})
    if not configuration.get("category"):
        problems.append({"path": "category", "message": "A category is required to publish."})
    if not configuration.get("purpose"):
        problems.append({"path": "purpose", "message": "A purpose is required to publish."})
    if not configuration.get("steps"):
        problems.append({"path": "steps", "message": "The workflow needs at least one step to publish."})
    missing = sorted(set(LIMIT_CEILINGS) - set(configuration.get("limits") or {}))
    if missing:
        problems.append({"path": "limits", "message": "Every limit must be set to publish: " + ", ".join(missing) + "."})
    return problems

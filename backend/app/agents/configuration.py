"""Schema validation for agent configuration and execution inputs (DFR1-019).

A configuration is plain JSON with a fixed shape. Unknown keys are refused at every level, so a field that is not part of the
schema cannot be stored and quietly change behaviour later. Validation is pure: it needs the set of registered tool keys, and it
does not touch the database. Publishing repeats the checks that need the database (see ``service.py``).

An agent's plan is a fixed, ordered list of steps. There is no free-form loop: the number of steps is bounded, and a tool step
names a tool the agent was assigned. The model never chooses a tool.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.agents.crm_action_catalogue import CRM_ACTIONS
from app.ai_gateway.structured import validate_schema

CATEGORIES = ("sales", "operations", "research")
LANGUAGES = ("en", "de", "es", "fr", "nl", "sv", "da", "nb")
INPUT_TYPES = ("uuid", "string", "integer")
STEP_KINDS = ("tool", "knowledge", "model", "approval", "crm_action")
AUTONOMY_LEVELS = ("suggest", "act")
APPROVAL_POLICIES = ("none", "before_result")
TRIGGER_TYPES = ("manual",)
MODEL_TASKS = ("text",)

MAX_TOOLS = 10
MAX_INPUTS = 10
MAX_KNOWLEDGE_DOCUMENTS = 20
MAX_OUTPUT_KEYS = 10
MAX_PURPOSE = 500
MAX_INSTRUCTIONS = 4000
MAX_PROMPT = 2000
MAX_QUERY = 500
MAX_REASON = 500

# Hard ceilings. A configuration may ask for less, never more.
CEILINGS: dict[str, int] = {
    "max_duration_seconds": 300,
    "max_steps": 20,
    "max_tool_calls": 10,
    "max_retries": 2,
    "max_output_characters": 16_384,
    "max_concurrent_executions": 5,
    "max_executions_per_hour": 1_000,
}
LIMIT_FLOORS: dict[str, int] = {
    "max_duration_seconds": 1,
    "max_steps": 1,
    "max_tool_calls": 0,
    "max_retries": 0,
    "max_output_characters": 1,
    "max_concurrent_executions": 1,
    "max_executions_per_hour": 1,
}

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_INPUT_REF = re.compile(r"^\$input\.([a-z][a-z0-9_]{0,39})$")
_PLACEHOLDER = re.compile(r"\$(input|step)\.([a-z0-9_]+)")
_STEP_REF = re.compile(r"^[0-9]{1,2}$")
_STEP_FIELD_REF = re.compile(r"^\$step\.([0-9]{1,2})\.([a-z][a-z0-9_]{0,39})$")


class ConfigurationError(ValueError):
    """The configuration breaks the schema. ``problems`` names each problem without echoing any stored value."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _object(value: object, where: str, allowed: set[str], problems: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        problems.append(f"{where} must be an object.")
        return None
    for key in value:
        if key not in allowed:
            problems.append(f"{where} has an unknown field.")
            return None
    return value


def _text(value: object, where: str, limit: int, problems: list[str], *, required: bool) -> str | None:
    if value is None or value == "":
        if required:
            problems.append(f"{where} is required.")
        return None
    if not isinstance(value, str):
        problems.append(f"{where} must be text.")
        return None
    if len(value) > limit:
        problems.append(f"{where} is longer than {limit} characters.")
        return None
    return value


def _integer(value: object, where: str, floor: int, ceiling: int, problems: list[str]) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        problems.append(f"{where} must be an integer.")
        return None
    if not floor <= value <= ceiling:
        problems.append(f"{where} must be between {floor} and {ceiling}.")
        return None
    return value


def _choice(value: object, where: str, options: tuple[str, ...], problems: list[str]) -> str | None:
    if value not in options:
        problems.append(f"{where} must be one of: {', '.join(options)}.")
        return None
    return value  # type: ignore[return-value]


def _normalise_limits(raw: object, problems: list[str]) -> dict[str, int]:
    limits: dict[str, int] = {}
    data = _object(raw, "limits", set(CEILINGS), problems)
    if data is None:
        return limits
    for key, value in data.items():
        checked = _integer(value, f"limits.{key}", LIMIT_FLOORS[key], CEILINGS[key], problems)
        if checked is not None:
            limits[key] = checked
    return limits


def _normalise_inputs(raw: object, problems: list[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or len(raw) > MAX_INPUTS:
        problems.append(f"inputs must be a list of at most {MAX_INPUTS} entries.")
        return []
    inputs: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(raw):
        where = f"inputs[{index}]"
        data = _object(item, where, {"name", "type", "required"}, problems)
        if data is None:
            continue
        name = data.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            problems.append(f"{where}.name must be lower case letters, digits and underscores.")
            continue
        if name in names:
            problems.append(f"{where}.name is declared more than once.")
            continue
        names.add(name)
        input_type = _choice(data.get("type"), f"{where}.type", INPUT_TYPES, problems)
        required = data.get("required", True)
        if not isinstance(required, bool):
            problems.append(f"{where}.required must be true or false.")
            continue
        if input_type is not None:
            inputs.append({"name": name, "type": input_type, "required": required})
    return inputs


def _normalise_knowledge(raw: object, problems: list[str]) -> list[str]:
    if not isinstance(raw, list) or len(raw) > MAX_KNOWLEDGE_DOCUMENTS:
        problems.append(f"knowledge_document_ids must be a list of at most {MAX_KNOWLEDGE_DOCUMENTS} identifiers.")
        return []
    ids: list[str] = []
    for item in raw:
        try:
            from uuid import UUID

            value = str(UUID(str(item)))
        except (TypeError, ValueError):
            problems.append("knowledge_document_ids must contain only identifiers.")
            continue
        if value in ids:
            problems.append("knowledge_document_ids must not repeat.")
            continue
        ids.append(value)
    return ids


def _placeholders_ok(text: str, *, input_names: set[str], step_index: int, problems: list[str], where: str) -> None:
    for kind, name in _PLACEHOLDER.findall(text):
        if kind == "input" and name not in input_names:
            problems.append(f"{where} refers to an undeclared input.")
        if kind == "step" and not (_STEP_REF.fullmatch(name) and int(name) < step_index):
            problems.append(f"{where} refers to a step that does not come before it.")


def _is_reference(value: str, *, index: int, input_names: set[str]) -> bool:
    """A ``$input.name`` declared by the agent, or a ``$step.N.field`` that comes before this step."""
    match = _INPUT_REF.fullmatch(value)
    if match is not None:
        return match.group(1) in input_names
    step_match = _STEP_FIELD_REF.fullmatch(value)
    return step_match is not None and int(step_match.group(1)) < index


def _normalise_crm_action(item: object, where: str, *, index: int, input_names: set[str],
                          problems: list[str]) -> dict[str, Any] | None:
    """A CRM action step names one approved action and its arguments. Arguments are references, never literal values."""
    data = _object(item, where, {"kind", "action", "arguments"}, problems)
    if data is None:
        return None
    action = data.get("action")
    spec = CRM_ACTIONS.get(action) if isinstance(action, str) else None
    if spec is None:
        problems.append(f"{where}.action is not an approved CRM action.")
        return None
    arguments = data.get("arguments", {})
    if not isinstance(arguments, dict):
        problems.append(f"{where}.arguments must be an object.")
        return None
    allowed = set(spec.required_arguments) | set(spec.optional_arguments)
    clean: dict[str, str] = {}
    for name, value in arguments.items():
        if name not in allowed:
            problems.append(f"{where}.arguments has an argument this action does not take.")
            continue
        if not isinstance(value, str) or not _is_reference(value, index=index, input_names=input_names):
            problems.append(f"{where}.arguments must refer to a declared input or to an earlier step.")
            continue
        clean[name] = value
    if any(name not in clean for name in spec.required_arguments):
        problems.append(f"{where} is missing a required argument.")
        return None
    return {"kind": "crm_action", "action": action, "arguments": clean}


def _normalise_steps(raw: object, *, tools: set[str], input_names: set[str], problems: list[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        problems.append("steps must be a non-empty list.")
        return []
    steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        where = f"steps[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where} must be an object.")
            continue
        kind = item.get("kind")
        if kind not in STEP_KINDS:
            problems.append(f"{where}.kind must be one of: {', '.join(STEP_KINDS)}.")
            continue
        if kind == "tool":
            data = _object(item, where, {"kind", "tool", "arguments"}, problems)
            if data is None:
                continue
            tool = data.get("tool")
            if tool not in tools:
                problems.append(f"{where}.tool is not assigned to this agent.")
                continue
            arguments = data.get("arguments", {})
            if not isinstance(arguments, dict):
                problems.append(f"{where}.arguments must be an object.")
                continue
            clean_arguments: dict[str, Any] = {}
            for name, value in arguments.items():
                if not isinstance(name, str) or not _NAME.fullmatch(name):
                    problems.append(f"{where}.arguments has an invalid name.")
                    continue
                if isinstance(value, str) and value.startswith("$"):
                    match = _INPUT_REF.fullmatch(value)
                    if match is None or match.group(1) not in input_names:
                        problems.append(f"{where}.arguments refers to an undeclared input.")
                        continue
                elif not isinstance(value, (str, int, bool)) or (isinstance(value, str) and len(value) > MAX_QUERY):
                    problems.append(f"{where}.arguments values must be short text, integers or booleans.")
                    continue
                clean_arguments[name] = value
            steps.append({"kind": "tool", "tool": tool, "arguments": clean_arguments})
        elif kind == "knowledge":
            data = _object(item, where, {"kind", "query", "top_k"}, problems)
            if data is None:
                continue
            query = _text(data.get("query"), f"{where}.query", MAX_QUERY, problems, required=True)
            top_k = _integer(data.get("top_k", 5), f"{where}.top_k", 1, 10, problems)
            if query is None or top_k is None:
                continue
            if query.startswith("$"):
                match = _INPUT_REF.fullmatch(query)
                if match is None or match.group(1) not in input_names:
                    problems.append(f"{where}.query refers to an undeclared input.")
                    continue
            steps.append({"kind": "knowledge", "query": query, "top_k": top_k})
        elif kind == "model":
            data = _object(item, where, {"kind", "prompt", "output_schema"}, problems)
            if data is None:
                continue
            prompt = _text(data.get("prompt"), f"{where}.prompt", MAX_PROMPT, problems, required=True)
            schema = data.get("output_schema")
            if not isinstance(schema, dict) or len(schema) > MAX_OUTPUT_KEYS:
                problems.append(f"{where}.output_schema must be an object of at most {MAX_OUTPUT_KEYS} keys.")
                continue
            schema_problem = validate_schema({str(k): str(v) for k, v in schema.items()}) if schema else "empty"
            if schema_problem is not None:
                problems.append(f"{where}.output_schema is not valid.")
                continue
            if prompt is None:
                continue
            _placeholders_ok(prompt, input_names=input_names, step_index=index, problems=problems, where=where)
            steps.append({"kind": "model", "prompt": prompt, "output_schema": dict(schema)})
        elif kind == "crm_action":
            clean = _normalise_crm_action(item, where, index=index, input_names=input_names, problems=problems)
            if clean is not None:
                steps.append(clean)
        else:  # approval
            data = _object(item, where, {"kind", "reason"}, problems)
            if data is None:
                continue
            reason = _text(data.get("reason"), f"{where}.reason", MAX_REASON, problems, required=True)
            if reason is not None:
                steps.append({"kind": "approval", "reason": reason})
    return steps


def normalise_configuration(raw: object, *, registered_tools: frozenset[str]) -> dict[str, Any]:
    """Return the canonical configuration, or raise ``ConfigurationError`` listing every problem found.

    Limits and the approval-related checks are only partly required here, so a draft can be saved while it is incomplete. A
    publish must repeat the check with ``require_publishable``.
    """
    problems: list[str] = []
    data = _object(
        raw,
        "configuration",
        {
            "category", "purpose", "instructions", "language", "model_task", "autonomy_level", "approval_policy",
            "trigger", "tools", "knowledge_document_ids", "inputs", "steps", "limits",
        },
        problems,
    )
    if data is None:
        raise ConfigurationError(problems)

    category = data.get("category")
    if category is not None:
        _choice(category, "category", CATEGORIES, problems)
    purpose = _text(data.get("purpose"), "purpose", MAX_PURPOSE, problems, required=False)
    instructions = _text(data.get("instructions"), "instructions", MAX_INSTRUCTIONS, problems, required=False)
    language = data.get("language", "en")
    _choice(language, "language", LANGUAGES, problems)
    model_task = data.get("model_task", "text")
    _choice(model_task, "model_task", MODEL_TASKS, problems)
    autonomy = data.get("autonomy_level", "suggest")
    _choice(autonomy, "autonomy_level", AUTONOMY_LEVELS, problems)
    approval_policy = data.get("approval_policy", "none")
    _choice(approval_policy, "approval_policy", APPROVAL_POLICIES, problems)

    trigger = _object(data.get("trigger", {"type": "manual"}), "trigger", {"type"}, problems)
    if trigger is not None and trigger.get("type") not in TRIGGER_TYPES:
        problems.append("trigger.type must be manual. Event triggers are not available in this release.")

    tools_raw = data.get("tools", [])
    tools: list[str] = []
    if not isinstance(tools_raw, list) or len(tools_raw) > MAX_TOOLS:
        problems.append(f"tools must be a list of at most {MAX_TOOLS} tool keys.")
    else:
        for tool in tools_raw:
            if not isinstance(tool, str) or tool not in registered_tools:
                problems.append("tools must name tools from the approved registry.")
                continue
            if tool in tools:
                problems.append("tools must not repeat.")
                continue
            tools.append(tool)

    knowledge = _normalise_knowledge(data.get("knowledge_document_ids", []), problems)
    inputs = _normalise_inputs(data.get("inputs", []), problems)
    input_names = {item["name"] for item in inputs}
    steps = _normalise_steps(data.get("steps", []), tools=set(tools), input_names=input_names, problems=problems) \
        if "steps" in data else []
    limits = _normalise_limits(data.get("limits", {}), problems)

    if any(step["kind"] == "knowledge" for step in steps) and not knowledge:
        problems.append("A knowledge step needs at least one knowledge source assigned to the agent.")
    if len(steps) > limits.get("max_steps", CEILINGS["max_steps"]):
        problems.append("The plan has more steps than the step limit allows.")
    tool_steps = sum(1 for step in steps if step["kind"] == "tool")
    if tool_steps > limits.get("max_tool_calls", CEILINGS["max_tool_calls"]):
        problems.append("The plan has more tool steps than the tool-call limit allows.")
    if autonomy == "suggest" and approval_policy == "none" and not any(step["kind"] == "approval" for step in steps):
        problems.append("A suggest-only agent needs an approval step or an approval policy before its result is released.")

    if problems:
        raise ConfigurationError(problems)
    return {
        "category": category,
        "purpose": purpose,
        "instructions": instructions,
        "language": language,
        "model_task": model_task,
        "autonomy_level": autonomy,
        "approval_policy": approval_policy,
        "trigger": {"type": "manual"},
        "tools": tools,
        "knowledge_document_ids": knowledge,
        "inputs": inputs,
        "steps": steps,
        "limits": limits,
    }


def require_publishable(configuration: Mapping[str, Any]) -> list[str]:
    """Problems that stop a draft from being published. An empty list means it may be published."""
    problems: list[str] = []
    if not configuration.get("category"):
        problems.append("A category is required to publish.")
    if not configuration.get("purpose"):
        problems.append("A purpose is required to publish.")
    if not configuration.get("instructions"):
        problems.append("Instructions are required to publish.")
    if not configuration.get("steps"):
        problems.append("The agent needs at least one step to publish.")
    limits = configuration.get("limits") or {}
    missing = sorted(set(CEILINGS) - set(limits))
    if missing:
        problems.append("Every execution limit must be set to publish: " + ", ".join(missing) + ".")
    return problems


def validate_input_values(inputs: list[Mapping[str, Any]], values: object) -> dict[str, Any]:
    """Check an execution's input values against the version's declared inputs. Raises ``ConfigurationError``."""
    if not isinstance(values, dict):
        raise ConfigurationError(["The input must be an object."])
    declared = {item["name"]: item for item in inputs}
    problems: list[str] = []
    for name in values:
        if name not in declared:
            problems.append("The input has an undeclared field.")
    typed: dict[str, Any] = {}
    for name, spec in declared.items():
        if name not in values:
            if spec["required"]:
                problems.append(f"Input {name} is required.")
            continue
        value = values[name]
        if spec["type"] == "uuid":
            try:
                from uuid import UUID

                typed[name] = str(UUID(str(value)))
            except (TypeError, ValueError):
                problems.append(f"Input {name} must be an identifier.")
        elif spec["type"] == "integer":
            if isinstance(value, int) and not isinstance(value, bool):
                typed[name] = value
            else:
                problems.append(f"Input {name} must be an integer.")
        else:
            if isinstance(value, str) and 0 < len(value) <= MAX_QUERY:
                typed[name] = value
            else:
                problems.append(f"Input {name} must be short text.")
    if problems:
        raise ConfigurationError(problems)
    return typed

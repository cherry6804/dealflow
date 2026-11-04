"""Strict argument validation for AI tool calls (DFR1-018).

Arguments are checked against the tool's schema before anything else runs. Unknown keys, missing required keys, the wrong
JSON type (a boolean is never an integer, and a string is never a UUID by accident), out-of-range values and overlong
strings are all refused. Refusals name the parameter, never the value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.ai_tools.definitions import ParameterType, ToolDefinition, ToolParameter


class InvalidArgumentsError(ValueError):
    """The arguments do not match the tool's schema. The message names the parameter, not its value."""


def _check_value(parameter: ToolParameter, value: object) -> Any:
    if parameter.type is ParameterType.STRING:
        if not isinstance(value, str):
            raise InvalidArgumentsError(f"{parameter.name} must be a string.")
        if not value.strip():
            raise InvalidArgumentsError(f"{parameter.name} must not be blank.")
        if len(value) > parameter.max_length:
            raise InvalidArgumentsError(f"{parameter.name} is longer than {parameter.max_length} characters.")
        return value
    if parameter.type is ParameterType.UUID:
        if not isinstance(value, str):
            raise InvalidArgumentsError(f"{parameter.name} must be a UUID string.")
        try:
            return UUID(value)
        except ValueError as exc:
            raise InvalidArgumentsError(f"{parameter.name} must be a UUID string.") from exc
    if parameter.type is ParameterType.BOOLEAN:
        if not isinstance(value, bool):
            raise InvalidArgumentsError(f"{parameter.name} must be true or false.")
        return value
    # INTEGER: a bool is an int in Python, so it is refused explicitly.
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidArgumentsError(f"{parameter.name} must be an integer.")
    if parameter.minimum is not None and value < parameter.minimum:
        raise InvalidArgumentsError(f"{parameter.name} is below its minimum.")
    if parameter.maximum is not None and value > parameter.maximum:
        raise InvalidArgumentsError(f"{parameter.name} is above its maximum.")
    return value


def validate_arguments(definition: ToolDefinition, raw: Mapping[str, object]) -> dict[str, Any]:
    """Return the typed arguments, or raise ``InvalidArgumentsError``."""
    if not isinstance(raw, Mapping):
        raise InvalidArgumentsError("Arguments must be an object.")
    known = {parameter.name: parameter for parameter in definition.parameters}
    unknown = sorted(str(key) for key in raw if key not in known)
    if unknown:
        raise InvalidArgumentsError("Unknown argument " + unknown[0] + ".")
    typed: dict[str, Any] = {}
    for name, parameter in known.items():
        if name not in raw:
            if parameter.required:
                raise InvalidArgumentsError(f"{name} is required.")
            continue
        typed[name] = _check_value(parameter, raw[name])
    return typed

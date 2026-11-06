"""Strict argument validation for AI tool calls (DFR1-018).

Arguments are checked against the tool's schema before anything else runs. Unknown keys, missing required keys, the wrong
JSON type (a boolean is never an integer, and a string is never a UUID by accident), out-of-range values and overlong
strings are all refused. Refusals name the parameter, never the value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.ai_tools.definitions import (
    OutputField,
    OutputType,
    ParameterType,
    ToolDefinition,
    ToolParameter,
)


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


class OutputContractError(ValueError):
    """A handler result does not match its declared output contract. The detail names a field, never a value."""


def validate_output(definition: ToolDefinition, data: object) -> dict[str, Any]:
    """Check a handler result against the tool's exact output contract, and return a new, fully checked copy.

    Every key must be declared, required keys must be present, nullable is the only way a value may be None, and each value
    must match its declared type. Nested objects are checked with their own declared fields, and arrays with their declared
    item type. Nothing is returned until the whole result has passed, so a partly valid result is never exposed.
    """
    return _check_object(definition.output_schema, data, path="result")


def _check_object(fields: tuple[OutputField, ...], value: object, *, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OutputContractError(f"{path} must be an object.")
    declared = {field.name: field for field in fields}
    if any(key not in declared for key in value):
        raise OutputContractError(f"{path} has an undeclared field.")
    checked: dict[str, Any] = {}
    for field in fields:
        if field.name not in value:
            if field.required:
                raise OutputContractError(f"{path}.{field.name} is required.")
            continue
        checked[field.name] = _check_result_value(field, value[field.name], path=f"{path}.{field.name}")
    return checked


def _check_result_value(field: OutputField, value: object, *, path: str) -> Any:
    if value is None:
        if field.nullable:
            return None
        raise OutputContractError(f"{path} may not be null.")
    if field.type is OutputType.OBJECT:
        return _check_object(field.fields, value, path=path)
    if field.type is OutputType.ARRAY:
        if not isinstance(value, list) or field.items is None:
            raise OutputContractError(f"{path} must be an array.")
        return [_check_result_value(field.items, item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    if field.type is OutputType.STRING and isinstance(value, str):
        return value
    if field.type is OutputType.BOOLEAN and isinstance(value, bool):
        return value
    if field.type is OutputType.INTEGER and isinstance(value, int) and not isinstance(value, bool):
        return value
    raise OutputContractError(f"{path} has the wrong type.")

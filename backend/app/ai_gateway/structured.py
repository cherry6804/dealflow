"""Structured-output validation for AI text tasks (DFR1-015).

The caller states the output as a schema of required keys and JSON type names. The provider's text must be a JSON object
that has exactly those keys, each of the stated type. Anything else is refused, so a model's free text never reaches a
caller that expects structure.
"""

from __future__ import annotations

import json

ALLOWED_TYPES: frozenset[str] = frozenset({"string", "number", "integer", "boolean", "array", "object"})


def validate_schema(schema: dict[str, str]) -> str | None:
    """Return a problem description for a malformed schema, or None when it is usable."""
    if not schema:
        return "The output schema must name at least one key."
    for key, type_name in schema.items():
        if not key or not key.strip():
            return "Schema keys must not be blank."
        if type_name not in ALLOWED_TYPES:
            return f"Schema type {type_name!r} is not supported."
    return None


def _matches(value: object, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "array":
        return isinstance(value, list)
    return isinstance(value, dict)


def parse_structured(text: str, schema: dict[str, str]) -> dict[str, object] | None:
    """Return the parsed object when ``text`` matches ``schema`` exactly, otherwise None."""
    try:
        decoded = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    if set(decoded) != set(schema):
        return None
    if not all(_matches(decoded[key], type_name) for key, type_name in schema.items()):
        return None
    return decoded

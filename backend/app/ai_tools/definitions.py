"""Typed tool definitions for AI agents (DFR1-018).

A tool is a named, server-defined operation with a fixed input schema, one catalogued permission, and one AI capability
that governs it. Agents never supply code, SQL, or a handler. They name a registered tool and supply arguments that match its
schema.

This release registers read-only tools only. A write tool needs its own approval (ADR-0029, gate 9) and is refused here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

# Largest JSON result a tool may return, in characters. Keeps one call from returning unbounded data to a model.
MAX_RESULT_CHARACTERS = 16_384
# Statement timeout applied to a tool's database work, in milliseconds.
DEFAULT_TIMEOUT_MS = 2_000
MAX_TIMEOUT_MS = 10_000
MAX_STRING_LENGTH = 200


class ParameterType(StrEnum):
    STRING = "string"
    UUID = "uuid"
    INTEGER = "integer"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: ParameterType
    required: bool = True
    max_length: int = MAX_STRING_LENGTH
    minimum: int | None = None
    maximum: int | None = None


# Deepest nesting an output contract may declare. The result object is level 1, so this allows an object inside an object
# inside an object, and no deeper.
MAX_OUTPUT_DEPTH = 3


class OutputType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


@dataclass(frozen=True)
class OutputField:
    """One declared field of a tool result. An object declares its ``fields``; an array declares its ``items``.

    A field that is not ``required`` may be absent. A field that is ``nullable`` may hold None. Nothing else is accepted.
    """

    name: str
    type: OutputType
    required: bool = True
    nullable: bool = False
    fields: tuple[OutputField, ...] = ()
    items: OutputField | None = None


# A handler receives a validated, typed argument mapping and returns JSON-safe primitives only. It must not return ORM rows.
ToolHandler = Callable[[Session, UUID, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    key: str
    description: str
    capability_key: str
    required_permission: str
    parameters: tuple[ToolParameter, ...]
    handler: ToolHandler
    read_only: bool = True
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    # Contract version. A caller may pin a version; any other version is refused, so a changed contract never runs silently.
    version: int = 1
    # The exact shape of the result. Every key must be declared, required keys must be present, and every value must match
    # its declared type. A result that does not match is refused and never returned.
    output_schema: tuple[OutputField, ...] = ()
    # The record the call acts on, for the audit trail. ``target_parameter`` names the argument that holds its UUID. Only the
    # identifier is recorded, never the record's contents.
    target_type: str | None = None
    target_parameter: str | None = None
    # An unavailable tool stays in the catalogue for review but cannot be invoked through the registry.
    available: bool = True

    def parameter(self, name: str) -> ToolParameter | None:
        return next((item for item in self.parameters if item.name == name), None)

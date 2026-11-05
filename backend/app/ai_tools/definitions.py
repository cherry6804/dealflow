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
    # Top-level keys the handler may return (the "found" flag, then the entity). Every returned key must be declared, and every
    # value must be a JSON primitive or a flat object of JSON primitives. Anything else is refused as an output contract violation.
    output_fields: tuple[str, ...] = ()
    # An unavailable tool stays in the catalogue for review but cannot be invoked through the registry.
    available: bool = True

    def parameter(self, name: str) -> ToolParameter | None:
        return next((item for item in self.parameters if item.name == name), None)

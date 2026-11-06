"""Registry of approved AI tools (DFR1-018).

Registration checks every definition, so a tool that breaks the rules cannot be added: the key must be well formed and
unique, the permission must exist in the catalogue, the capability must be an AI capability in the governance catalogue, the
tool must be read-only, and its timeout and parameters must be within bounds. Nothing can be registered at runtime from
input data.
"""

from __future__ import annotations

import re

from app.ai_tools.definitions import (
    MAX_OUTPUT_DEPTH,
    MAX_TIMEOUT_MS,
    OutputField,
    OutputType,
    ParameterType,
    ToolDefinition,
)
from app.authz.permissions import PERMISSION_DESCRIPTIONS
from app.governance.capabilities import CAPABILITY_BY_KEY, CapabilityCategory

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}\.[a-z][a-z0-9_]{0,39}$")
_PARAMETER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# Channel and voice tools are deferred with the communication hub (see the release plan). Their names and capabilities are
# refused here so that no such tool can be registered by accident while they are out of scope.
_DEFERRED_KEY_PARTS = frozenset({"whatsapp", "messenger", "instagram", "telephony", "voice", "sms", "email", "call", "channel"})
_DEFERRED_CAPABILITY_KEYS = frozenset({"ai.voice"})


class ToolRegistrationError(ValueError):
    """A tool definition breaks a registration rule. Raised at import or registration, never at runtime."""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if not _KEY_PATTERN.fullmatch(definition.key):
            raise ToolRegistrationError("A tool key must look like 'area.action' in lower case.")
        if definition.key in self._tools:
            raise ToolRegistrationError("A tool with this key is already registered.")
        if not definition.read_only:
            raise ToolRegistrationError("Only read-only tools can be registered in this release.")
        if definition.required_permission not in PERMISSION_DESCRIPTIONS:
            raise ToolRegistrationError("The tool's permission is not in the permission catalogue.")
        capability = CAPABILITY_BY_KEY.get(definition.capability_key)
        if capability is None or capability.category is not CapabilityCategory.AI:
            raise ToolRegistrationError("The tool must be governed by an AI capability.")
        if not 1 <= definition.timeout_ms <= MAX_TIMEOUT_MS:
            raise ToolRegistrationError("The tool timeout is out of range.")
        if definition.version < 1:
            raise ToolRegistrationError("A tool version starts at 1.")
        if _DEFERRED_KEY_PARTS & set(definition.key.split(".")) or definition.capability_key in _DEFERRED_CAPABILITY_KEYS:
            raise ToolRegistrationError("Channel and voice tools are deferred and cannot be registered in this release.")
        _check_output_schema(definition.output_schema, depth=1)
        if (definition.target_type is None) != (definition.target_parameter is None):
            raise ToolRegistrationError("A tool names its target type and its target parameter together, or neither.")
        if definition.target_parameter is not None:
            parameter = definition.parameter(definition.target_parameter)
            if parameter is None or parameter.type is not ParameterType.UUID:
                raise ToolRegistrationError("The target parameter must be a UUID argument of the tool.")
        names = [parameter.name for parameter in definition.parameters]
        if len(set(names)) != len(names):
            raise ToolRegistrationError("Parameter names must be unique.")
        for parameter in definition.parameters:
            if not _PARAMETER_PATTERN.fullmatch(parameter.name):
                raise ToolRegistrationError("A parameter name must be lower case letters, digits and underscores.")
            if parameter.type is ParameterType.STRING and not 1 <= parameter.max_length <= 1_000:
                raise ToolRegistrationError("A string parameter needs a length limit between 1 and 1000.")
        self._tools[definition.key] = definition

    def get(self, key: str) -> ToolDefinition | None:
        return self._tools.get(key)

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))


def _check_output_schema(fields: tuple[OutputField, ...], *, depth: int) -> None:
    """A declared output schema is finite, uniquely named and no deeper than the release allows."""
    if not fields:
        raise ToolRegistrationError("An output object must declare at least one field.")
    names = [field.name for field in fields]
    if len(set(names)) != len(names):
        raise ToolRegistrationError("Output field names must be unique within an object.")
    for field in fields:
        _check_output_field(field, depth=depth)


def _check_output_field(field: OutputField, *, depth: int) -> None:
    if depth > MAX_OUTPUT_DEPTH:
        raise ToolRegistrationError("An output contract nests deeper than the release allows.")
    if not _PARAMETER_PATTERN.fullmatch(field.name):
        raise ToolRegistrationError("An output field name must be lower case letters, digits and underscores.")
    if field.type is OutputType.OBJECT:
        _check_output_schema(field.fields, depth=depth + 1)
    elif field.fields:
        raise ToolRegistrationError("Only an object output field can declare nested fields.")
    if field.type is OutputType.ARRAY:
        if field.items is None:
            raise ToolRegistrationError("An array output field must declare its item type.")
        _check_output_field(field.items, depth=depth + 1)
    elif field.items is not None:
        raise ToolRegistrationError("Only an array output field can declare item types.")


def build_default_registry() -> ToolRegistry:
    """The approved tools for this release. Adding a tool is a code change that goes through the same checks."""
    from app.ai_tools.builtin import BUILTIN_TOOLS

    registry = ToolRegistry()
    for definition in BUILTIN_TOOLS:
        registry.register(definition)
    return registry


DEFAULT_REGISTRY: ToolRegistry = build_default_registry()

"""Registry of approved AI tools (DFR1-018).

Registration checks every definition, so a tool that breaks the rules cannot be added: the key must be well formed and
unique, the permission must exist in the catalogue, the capability must be an AI capability in the governance catalogue, the
tool must be read-only, and its timeout and parameters must be within bounds. Nothing can be registered at runtime from
input data.
"""

from __future__ import annotations

import re

from app.ai_tools.definitions import MAX_TIMEOUT_MS, ParameterType, ToolDefinition
from app.authz.permissions import PERMISSION_DESCRIPTIONS
from app.governance.capabilities import CAPABILITY_BY_KEY, CapabilityCategory

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}\.[a-z][a-z0-9_]{0,39}$")
_PARAMETER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


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


def build_default_registry() -> ToolRegistry:
    """The approved tools for this release. Adding a tool is a code change that goes through the same checks."""
    from app.ai_tools.builtin import BUILTIN_TOOLS

    registry = ToolRegistry()
    for definition in BUILTIN_TOOLS:
        registry.register(definition)
    return registry


DEFAULT_REGISTRY: ToolRegistry = build_default_registry()

"""Capability catalogue for AI and automation governance (DFR1-006).

Every optional AI or automation capability is listed here and is disabled by default.
A capability runs only when its master switch and its own switch are both enabled and
the policy engine allows the execution (see ``app.governance.policy``).

The catalogue is code, not data, so a capability cannot be introduced without a review
of its gates. Organization settings are stored separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CapabilityCategory(str, Enum):
    """Broad area a capability belongs to. Drives which gates apply."""

    MASTER = "master"
    AI = "ai"
    AUTOMATION = "automation"
    COMMUNICATION = "communication"


@dataclass(frozen=True)
class CapabilityDefinition:
    """A governed capability and the gates that apply beyond enablement."""

    key: str
    category: CapabilityCategory
    parent_key: str | None
    requires_provider: bool = False
    requires_consent: bool = False
    # SIBVO plan feature that must be enabled in the attested access snapshot.
    entitlement_feature: str | None = None

    @property
    def default_enabled(self) -> bool:
        """Every capability is disabled until an organization enables it."""
        return False


AI_MASTER = "ai.master"
AUTOMATION_MASTER = "automation.master"
AUTOMATION_DEAL_CREATED_RULES = "automation.deal_created_rules"


CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(AI_MASTER, CapabilityCategory.MASTER, None),
    CapabilityDefinition(AUTOMATION_MASTER, CapabilityCategory.MASTER, None),
    CapabilityDefinition(
        "ai.assistant", CapabilityCategory.AI, AI_MASTER, requires_provider=True
    ),
    CapabilityDefinition(
        "ai.agents", CapabilityCategory.AI, AI_MASTER, requires_provider=True
    ),
    CapabilityDefinition(
        "ai.workflow_execution", CapabilityCategory.AI, AI_MASTER, requires_provider=True
    ),
    CapabilityDefinition(
        "ai.predictions", CapabilityCategory.AI, AI_MASTER, requires_provider=True
    ),
    CapabilityDefinition(
        "ai.content_generation", CapabilityCategory.AI, AI_MASTER, requires_provider=True
    ),
    CapabilityDefinition(
        "ai.document_processing", CapabilityCategory.AI, AI_MASTER, requires_provider=True
    ),
    CapabilityDefinition(
        "ai.voice", CapabilityCategory.AI, AI_MASTER, requires_provider=True,
        requires_consent=True,
    ),
    CapabilityDefinition(
        AUTOMATION_DEAL_CREATED_RULES,
        CapabilityCategory.AUTOMATION,
        AUTOMATION_MASTER,
        entitlement_feature="workflow_automation",
    ),
    CapabilityDefinition(
        "channels.whatsapp", CapabilityCategory.COMMUNICATION, None,
        requires_provider=True, requires_consent=True,
    ),
    CapabilityDefinition(
        "channels.email", CapabilityCategory.COMMUNICATION, None,
        requires_provider=True, requires_consent=True,
    ),
    CapabilityDefinition(
        "channels.sms", CapabilityCategory.COMMUNICATION, None,
        requires_provider=True, requires_consent=True,
    ),
    CapabilityDefinition(
        "channels.voice", CapabilityCategory.COMMUNICATION, None,
        requires_provider=True, requires_consent=True,
    ),
)

CAPABILITY_BY_KEY: dict[str, CapabilityDefinition] = {
    definition.key: definition for definition in CAPABILITIES
}


def ancestry(definition: CapabilityDefinition) -> tuple[CapabilityDefinition, ...]:
    """Return the chain from the top-level master down to ``definition`` inclusive."""
    chain: list[CapabilityDefinition] = []
    current: CapabilityDefinition | None = definition
    while current is not None:
        chain.append(current)
        current = (
            CAPABILITY_BY_KEY[current.parent_key] if current.parent_key else None
        )
    return tuple(reversed(chain))

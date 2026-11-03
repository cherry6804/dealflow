"""Trusted attribution for independently written audit records (WS6 WP3 security correction).

An audit row names an organization and an actor. Those values are security evidence, so the writer does not
accept them as plain identifiers. A caller must pass an ``AuditAttribution``, and the writer checks that
attribution against the database before it writes anything:

- A user attribution is valid only when that user holds an active membership in an active organization. The
  request path establishes the same fact in ``get_tenant_context``, which binds the request to its session
  organization and requires an active membership. The writer repeats the check on its own connection, so a
  caller cannot write under an organization or user it does not belong to.
- A system attribution names one of the explicitly allowlisted system actors. It exists for gates and jobs
  that act without a user, and it must still name an active organization.

Anything else is refused with ``AuditAttributionError`` before a row is written. Refusal is a fail-closed
outcome, not an availability problem, so it is reported separately from persistence failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

# System actors that may write audit records without a user. Adding one is a reviewed change.
SYSTEM_ACTORS: frozenset[str] = frozenset({"ai_execution_gate", "automation_rate_limit"})


class AuditAttributionError(PermissionError):
    """The attribution could not be verified, so no audit record was written."""


@dataclass(frozen=True)
class AuditAttribution:
    organization_id: UUID
    actor_user_id: UUID | None = None
    system_actor: str | None = None

    def __post_init__(self) -> None:
        if (self.actor_user_id is None) == (self.system_actor is None):
            raise ValueError("An attribution names exactly one actor: a user or a system actor.")
        if self.system_actor is not None and self.system_actor not in SYSTEM_ACTORS:
            raise ValueError(f"Unknown system audit actor: {self.system_actor!r}.")


def user_attribution(*, organization_id: UUID, actor_user_id: UUID) -> AuditAttribution:
    """Attribution for an authenticated user acting in ``organization_id``. Verified by the writer."""
    return AuditAttribution(organization_id=organization_id, actor_user_id=actor_user_id)


def system_attribution(*, organization_id: UUID, system_actor: str) -> AuditAttribution:
    """Attribution for an allowlisted system actor acting in ``organization_id``. Verified by the writer."""
    return AuditAttribution(organization_id=organization_id, system_actor=system_actor)

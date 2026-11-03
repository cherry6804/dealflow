"""Trusted audit attribution for independently written audit records (WS6 WP3, hardened).

An audit row names an organization and an actor. Those values are security evidence, so they are never taken
from a caller as plain identifiers. An ``AuditAttribution`` can be created in only two ways, and both are
checked:

- ``user_attribution`` derives the user and organization from the principal bound by the authentication layer
  (``app.audit.principal``). The claimed user and organization must equal that principal exactly. A caller
  cannot attribute an operation to another user, including another active user of the same organization, or to
  a user or organization outside the request.
- ``system_attribution`` requires a ``SystemActorCapability``. Each system actor has one capability, created
  once by the module that owns that actor through ``register_system_actor``. A caller cannot mint a capability,
  because its constructor requires a token held by this module, and a capability is accepted only if it is the
  one registered under its name. A name on its own is not enough. If a principal is bound, the system record
  must name that principal's organization.

The writer then verifies the organization and any user against the database on its own connection, so the
guarantee does not depend on the caller having used these factories correctly.

Refusal raises ``AuditAttributionError``. It maps to HTTP 403 and names no identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.audit.principal import current_principal

_ATTRIBUTION_ISSUED = object()
_REGISTRATION_TOKEN = object()

ATTRIBUTION_SOURCE_PRINCIPAL = "principal"  # bound to an authenticated request
ATTRIBUTION_SOURCE_MEMBERSHIP = "membership"  # no request; the writer verifies active membership
ATTRIBUTION_SOURCE_SYSTEM = "system"  # a registered system actor


class AuditAttributionError(PermissionError):
    """The attribution could not be verified, so no audit record was written."""


class SystemActorCapability:
    """Authority to write audit records for one system actor. Created only by ``register_system_actor``."""

    __slots__ = ("name",)

    def __init__(self, name: str, _registration: object) -> None:
        if _registration is not _REGISTRATION_TOKEN:
            raise TypeError("A system actor capability is created only by register_system_actor.")
        self.name = name


_registry: dict[str, SystemActorCapability] = {}


def register_system_actor(name: str) -> SystemActorCapability:
    """Register a system actor and return its capability. Called once, at import, by the owning module."""
    if not name or name in _registry:
        raise ValueError(f"System actor {name!r} is empty or already registered.")
    capability = SystemActorCapability(name, _REGISTRATION_TOKEN)
    _registry[name] = capability
    return capability


@dataclass(frozen=True)
class AuditAttribution:
    organization_id: UUID
    actor_user_id: UUID | None
    system_actor: str | None
    source: str
    _issued: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._issued is not _ATTRIBUTION_ISSUED:
            raise TypeError("An audit attribution is created only by user_attribution or system_attribution.")
        if (self.actor_user_id is None) == (self.system_actor is None):
            raise ValueError("An attribution names exactly one actor: a user or a system actor.")


def user_attribution(*, organization_id: UUID, actor_user_id: UUID) -> AuditAttribution:
    """Attribution for a user.

    Inside an authenticated request, the user and organization must equal the bound principal exactly, so a
    caller cannot attribute an operation to another user, in the same organization or another one. Outside a
    request there is no principal to bind. The attribution is then labelled ``membership``, and the writer
    still verifies the user's active membership in the organization. That residual case is documented in
    docs/architecture/independent-audit-persistence.md, section 3.5.
    """
    principal = current_principal()
    if principal is not None:
        if principal.user_id != actor_user_id or principal.organization_id != organization_id:
            raise AuditAttributionError("The claimed identity does not match the authenticated principal.")
        source = ATTRIBUTION_SOURCE_PRINCIPAL
    else:
        source = ATTRIBUTION_SOURCE_MEMBERSHIP
    return AuditAttribution(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        system_actor=None,
        _issued=_ATTRIBUTION_ISSUED,
        source=source,
    )


def system_attribution(*, organization_id: UUID, capability: SystemActorCapability) -> AuditAttribution:
    """Attribution for a registered system actor, within the bound principal's organization if there is one."""
    if not isinstance(capability, SystemActorCapability) or _registry.get(capability.name) is not capability:
        raise AuditAttributionError("The system actor is not authorized to write audit records.")
    principal = current_principal()
    if principal is not None and principal.organization_id != organization_id:
        raise AuditAttributionError("The system record does not match the authenticated organization.")
    return AuditAttribution(
        organization_id=organization_id,
        actor_user_id=None,
        system_actor=capability.name,
        source=ATTRIBUTION_SOURCE_SYSTEM,
        _issued=_ATTRIBUTION_ISSUED,
    )

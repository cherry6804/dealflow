"""Server-side capability policy evaluation (DFR1-006).

The engine answers one question: may this organization run this capability now?
It fails closed. An unknown capability, a disabled master or capability switch, or a
gate whose infrastructure is not built yet all produce a denial with a stable reason
code. The frontend never decides; every execution entry point calls this engine.

Gates implemented here:
1. Capability is known to the catalogue.
2. Master and capability switches are enabled, checked from the top of the chain.
3. Capabilities that need a provider are denied until a provider connection exists
   (no provider integration is built yet, so these always deny).
4. Capabilities that need consent are denied until a consent model exists (not built).

Gates not implemented in this slice, and therefore not claimed: SIBVO entitlement,
provider health, resource publication and activation, per-actor permission, budgets,
rate limits and human approval. They are listed in the E13 documentation as blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.governance.capabilities import (
    CAPABILITY_BY_KEY,
    CapabilityDefinition,
    ancestry,
)
from app.governance.entitlement import (
    REASON_ENTITLEMENT_DISABLED,
    REASON_ENTITLEMENT_MISSING,
    REASON_ENTITLEMENT_UNVERIFIED,
    REASON_PRODUCT_MEMBERSHIP_INACTIVE,
    REASON_SUBSCRIPTION_NOT_ACTIVE,
    REASON_TRIAL_EXPIRED,
    REASON_WRONG_ORGANIZATION,
    verify_entitlement,
)

REASON_ALLOWED = "allowed"
REASON_UNKNOWN_CAPABILITY = "unknown_capability"
REASON_MASTER_DISABLED = "master_disabled"
REASON_CAPABILITY_DISABLED = "capability_disabled"
REASON_PROVIDER_NOT_CONNECTED = "provider_not_connected"
REASON_CONSENT_NOT_CONFIGURED = "consent_not_configured"

_EXPLANATIONS: dict[str, str] = {
    REASON_ALLOWED: "The capability is enabled for this organization.",
    REASON_UNKNOWN_CAPABILITY: "This capability is not recognised, so it cannot run.",
    REASON_MASTER_DISABLED: "A master switch above this capability is turned off.",
    REASON_CAPABILITY_DISABLED: "This capability is turned off for the organization.",
    REASON_PROVIDER_NOT_CONNECTED: (
        "A verified provider connection is required and none is available."
    ),
    REASON_CONSENT_NOT_CONFIGURED: (
        "Consent and channel policy must be configured before this capability can run."
    ),
    REASON_ENTITLEMENT_UNVERIFIED: (
        "Your subscription could not be verified. Sign in again or try later."
    ),
    REASON_WRONG_ORGANIZATION: "Your session is not authorized for this organization.",
    REASON_PRODUCT_MEMBERSHIP_INACTIVE: "Your access to this product is not active.",
    REASON_TRIAL_EXPIRED: "The trial for this product has ended.",
    REASON_SUBSCRIPTION_NOT_ACTIVE: "The subscription for this product is not active.",
    REASON_ENTITLEMENT_MISSING: "Your plan does not include this feature.",
    REASON_ENTITLEMENT_DISABLED: "This feature is turned off for your plan.",
}


@dataclass(frozen=True)
class PolicyDecision:
    """Structured result of a capability check. Denials carry a stable reason code."""

    capability_key: str
    organization_id: UUID
    allowed: bool
    reason_code: str
    explanation: str
    policy_version: int
    correlation_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "capability_key": self.capability_key,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "explanation": self.explanation,
            "policy_version": self.policy_version,
        }


def _decision(
    definition_key: str,
    organization_id: UUID,
    reason_code: str,
    policy_version: int,
    correlation_id: str | None,
) -> PolicyDecision:
    return PolicyDecision(
        capability_key=definition_key,
        organization_id=organization_id,
        allowed=reason_code == REASON_ALLOWED,
        reason_code=reason_code,
        explanation=_EXPLANATIONS[reason_code],
        policy_version=policy_version,
        correlation_id=correlation_id,
    )


def evaluate_capability(
    db: Session,
    *,
    organization_id: UUID,
    capability_key: str,
    user_context: CurrentUserContext | None = None,
    correlation_id: str | None = None,
) -> PolicyDecision:
    """Return whether ``capability_key`` may execute for ``organization_id`` now.

    Gates run in this order: entitlement (SIBVO snapshot), organization master and child
    switches, provider, consent. The first failing gate decides the reason. A capability
    that needs an entitlement and has no verifiable snapshot is denied.
    """

    definition: CapabilityDefinition | None = CAPABILITY_BY_KEY.get(capability_key)
    if definition is None:
        return _decision(
            capability_key, organization_id, REASON_UNKNOWN_CAPABILITY, 0, correlation_id
        )

    if definition.entitlement_feature is not None:
        verdict = verify_entitlement(
            user_context,
            organization_id=organization_id,
            feature_key=definition.entitlement_feature,
        )
        if not verdict.allowed:
            return _decision(
                definition.key, organization_id, verdict.reason_code, 0, correlation_id
            )

    chain = ancestry(definition)
    rows = {
        row.capability_key: row
        for row in db.scalars(
            select(OrganizationCapabilitySetting).where(
                OrganizationCapabilitySetting.organization_id == organization_id,
                OrganizationCapabilitySetting.capability_key.in_([item.key for item in chain]),
            )
        ).all()
    }

    policy_version = 0
    for item in chain:
        row = rows.get(item.key)
        enabled = row.is_enabled if row is not None else item.default_enabled
        if row is not None:
            policy_version = max(policy_version, row.policy_version)
        if not enabled:
            reason = (
                REASON_MASTER_DISABLED if item is not definition else REASON_CAPABILITY_DISABLED
            )
            return _decision(
                definition.key, organization_id, reason, policy_version, correlation_id
            )

    if definition.requires_provider:
        return _decision(
            definition.key, organization_id, REASON_PROVIDER_NOT_CONNECTED, policy_version,
            correlation_id,
        )

    if definition.requires_consent:
        return _decision(
            definition.key, organization_id, REASON_CONSENT_NOT_CONFIGURED, policy_version,
            correlation_id,
        )

    return _decision(definition.key, organization_id, REASON_ALLOWED, policy_version, correlation_id)

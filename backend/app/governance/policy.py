"""Server-side capability policy evaluation (DFR1-006).

The engine answers one question: may this organization run this capability now?
It fails closed. An unknown capability, a disabled master or capability switch, or a
gate whose infrastructure is not built yet all produce a denial with a stable reason
code. The frontend never decides; every execution entry point calls this engine.

Gates implemented here:
1. Capability is known to the catalogue.
2. Master and capability switches are enabled, checked from the top of the chain.
3. Capabilities that need a provider are denied until a verified provider connection exists
   (ADR-0032). A ready provider is not an execution grant: the capability is then denied with
   ``execution_gates_pending`` until consent, budget, approval and activation gates are built.
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
    CapabilityCategory,
    CapabilityDefinition,
    ancestry,
)
from app.governance.entitlement import (
    ORG_SNAPSHOT_FEATURES,
    REASON_ENTITLEMENT_DISABLED,
    REASON_ENTITLEMENT_MISSING,
    REASON_ENTITLEMENT_UNVERIFIED,
    REASON_PRODUCT_MEMBERSHIP_INACTIVE,
    REASON_SUBSCRIPTION_NOT_ACTIVE,
    REASON_TRIAL_EXPIRED,
    REASON_WRONG_ORGANIZATION,
    verify_entitlement,
)
from app.governance.org_entitlement import organization_entitlement_verdict
from app.providers.readiness import any_provider_ready
from app.providers.registry import providers_for_capability

REASON_ALLOWED = "allowed"
REASON_UNKNOWN_CAPABILITY = "unknown_capability"
REASON_MASTER_DISABLED = "master_disabled"
REASON_CAPABILITY_DISABLED = "capability_disabled"
REASON_PROVIDER_NOT_CONNECTED = "provider_not_connected"
REASON_ENTITLEMENT_NOT_DEFINED = "entitlement_not_defined"
REASON_CONSENT_NOT_CONFIGURED = "consent_not_configured"
REASON_EXECUTION_GATES_PENDING = "execution_gates_pending"

_EXPLANATIONS: dict[str, str] = {
    REASON_ALLOWED: "The capability is enabled for this organization.",
    REASON_UNKNOWN_CAPABILITY: "This capability is not recognised, so it cannot run.",
    REASON_MASTER_DISABLED: "A master switch above this capability is turned off.",
    REASON_CAPABILITY_DISABLED: "This capability is turned off for the organization.",
    REASON_ENTITLEMENT_NOT_DEFINED: "This capability has no confirmed plan feature, so it cannot run.",
    REASON_PROVIDER_NOT_CONNECTED: (
        "A verified provider connection is required and none is available."
    ),
    REASON_EXECUTION_GATES_PENDING: (
        "A provider is connected, but the consent, budget, approval and activation gates "
        "are not yet enforced, so this capability stays disabled."
    ),
    "snapshot_missing": "No current SIBVO entitlement snapshot is available for this organization.",
    "snapshot_expired": "The SIBVO entitlement snapshot has expired and could not be refreshed.",
    "snapshot_unavailable": "SIBVO could not be reached to confirm the entitlement.",
    "snapshot_rejected": "The SIBVO entitlement response could not be verified.",
    "organization_access_denied": "SIBVO reports that this organization has no current access.",
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
    consent_checked: bool = False,
) -> PolicyDecision:
    """Return whether ``capability_key`` may execute for ``organization_id`` now.

    ``consent_checked`` means the caller supplied a contact and the execution gate checks that contact's consent.
    Without it, a capability that requires consent is denied.

    Gates run in this order: entitlement (SIBVO snapshot), organization master and child
    switches, provider, consent. The first failing gate decides the reason. A capability
    that needs an entitlement and has no verifiable snapshot is denied.
    """

    definition: CapabilityDefinition | None = CAPABILITY_BY_KEY.get(capability_key)
    if definition is None:
        return _decision(
            capability_key, organization_id, REASON_UNKNOWN_CAPABILITY, 0, correlation_id
        )

    if (
        definition.entitlement_feature is not None
        and definition.entitlement_feature not in ORG_SNAPSHOT_FEATURES
    ):
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
            select(OrganizationCapabilitySetting)
            .where(
                OrganizationCapabilitySetting.organization_id == organization_id,
                OrganizationCapabilitySetting.capability_key.in_([item.key for item in chain]),
            )
            # Re-read the switches on every check. A switch changed by another committed session must stop
            # in-flight work at the next revalidation, even when this session already holds the old row.
            .execution_options(populate_existing=True)
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

    # An executable capability without a confirmed plan feature can never run. A null or empty key is not a feature,
    # so it cannot skip the entitlement check (E13 invariant, fail closed).
    if definition.category is not CapabilityCategory.MASTER and not definition.entitlement_feature:
        return _decision(
            definition.key, organization_id, REASON_ENTITLEMENT_NOT_DEFINED, policy_version, correlation_id,
        )

    if definition.requires_provider:
        provider_ready = any_provider_ready(
            db,
            organization_id=organization_id,
            provider_keys=providers_for_capability(definition.key),
        )
        if not provider_ready:
            return _decision(
                definition.key, organization_id, REASON_PROVIDER_NOT_CONNECTED, policy_version,
                correlation_id,
            )

    if definition.entitlement_feature in ORG_SNAPSHOT_FEATURES:
        # Organization-level SIBVO snapshot (WS5). Valid for background and synchronous callers alike.
        org_verdict = organization_entitlement_verdict(
            db,
            organization_id=organization_id,
            feature_key=definition.entitlement_feature,
        )
        if not org_verdict.allowed:
            return _decision(
                definition.key, organization_id, org_verdict.reason_code, policy_version,
                correlation_id,
            )

    if definition.requires_provider:
        # Entitlement and readiness are gates, never grants. Consent, budget, approval and activation
        # are not built, so execution stays closed even when every gate above passes.
        return _decision(
            definition.key, organization_id, REASON_EXECUTION_GATES_PENDING, policy_version,
            correlation_id,
        )

    if definition.requires_consent and not consent_checked:
        return _decision(
            definition.key, organization_id, REASON_CONSENT_NOT_CONFIGURED, policy_version,
            correlation_id,
        )

    return _decision(definition.key, organization_id, REASON_ALLOWED, policy_version, correlation_id)

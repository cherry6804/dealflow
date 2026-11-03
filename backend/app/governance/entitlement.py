"""SIBVO entitlement verification for governed capabilities (DFR1-006, decision 3).

Dealsflo does not hold subscription or billing state. The only authority is SIBVO's access
snapshot, which SIBVO issues with the session and Dealsflo revalidates through the E12 client
(introspection, bounded cache, fail-closed on outage). This module reads that snapshot and
decides, with stable reason codes, whether the snapshot allows a feature for this organization.

Fail-closed rules:
- No attested session, or no snapshot (for example SIBVO unavailable or session revoked):
  denied as ``entitlement_unverified``.
- Snapshot bound to another organization: denied as ``wrong_organization``.
- Missing or non-list entitlements, or malformed entries: denied as ``entitlement_unverified``.
- No product role (product membership inactive or suspended): ``product_membership_inactive``.
- Subscription not active or trialing: ``trial_expired`` for expired trials,
  otherwise ``subscription_not_active``.
- Feature absent from the plan: ``entitlement_missing``. Present but not enabled:
  ``entitlement_disabled``.

Responses expose only the reason code and a generic explanation, never the plan contents.
The local entitlement tables are not consulted here. Local fallback exists only for the
legacy feature checks and is refused for governed capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.auth.dependencies import CurrentUserContext

ELIGIBLE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing"})
# Features checked against the organization-level snapshot (WS5). Every other feature is checked
# against the user's session snapshot, as before.
ORG_SNAPSHOT_FEATURES = frozenset({"ai_gateway"})
EXPIRED_SUBSCRIPTION_STATUSES = frozenset({"expired", "trial_expired"})

REASON_ENTITLEMENT_UNVERIFIED = "entitlement_unverified"
REASON_WRONG_ORGANIZATION = "wrong_organization"
REASON_PRODUCT_MEMBERSHIP_INACTIVE = "product_membership_inactive"
REASON_TRIAL_EXPIRED = "trial_expired"
REASON_SUBSCRIPTION_NOT_ACTIVE = "subscription_not_active"
REASON_ENTITLEMENT_MISSING = "entitlement_missing"
REASON_ENTITLEMENT_DISABLED = "entitlement_disabled"
REASON_ENTITLEMENT_ALLOWED = "entitlement_allowed"


@dataclass(frozen=True)
class EntitlementVerdict:
    allowed: bool
    reason_code: str


def verify_entitlement(
    user_context: CurrentUserContext | None,
    *,
    organization_id: UUID,
    feature_key: str,
) -> EntitlementVerdict:
    """Return whether SIBVO's snapshot allows ``feature_key`` for ``organization_id``."""
    if user_context is None or not user_context.sibvo_attested:
        return EntitlementVerdict(False, REASON_ENTITLEMENT_UNVERIFIED)

    if (
        user_context.session_organization_id != organization_id
        or user_context.sibvo_organization_id != organization_id
    ):
        return EntitlementVerdict(False, REASON_WRONG_ORGANIZATION)

    access = user_context.sibvo_access
    return evaluate_feature_access(access, feature_key=feature_key, require_product_role=True)


def evaluate_feature_access(
    access: object,
    *,
    feature_key: str,
    require_product_role: bool,
) -> EntitlementVerdict:
    """The single rule set for a SIBVO access snapshot, from a user session or an organization.

    Session snapshots require a product role. Organization snapshots (WS5) involve no user and carry
    no role, so they pass ``require_product_role=False``. Every other rule is the same for both.
    """
    if not isinstance(access, dict):
        return EntitlementVerdict(False, REASON_ENTITLEMENT_UNVERIFIED)

    entitlements = access.get("entitlements")
    if not isinstance(entitlements, list):
        return EntitlementVerdict(False, REASON_ENTITLEMENT_UNVERIFIED)

    if require_product_role and not access.get("product_role"):
        return EntitlementVerdict(False, REASON_PRODUCT_MEMBERSHIP_INACTIVE)

    status = access.get("subscription_status")
    if status in EXPIRED_SUBSCRIPTION_STATUSES:
        return EntitlementVerdict(False, REASON_TRIAL_EXPIRED)
    if status not in ELIGIBLE_SUBSCRIPTION_STATUSES:
        return EntitlementVerdict(False, REASON_SUBSCRIPTION_NOT_ACTIVE)

    for item in entitlements:
        if not isinstance(item, dict):
            return EntitlementVerdict(False, REASON_ENTITLEMENT_UNVERIFIED)
        if item.get("feature_key") == feature_key:
            if item.get("enabled") is True:
                return EntitlementVerdict(True, REASON_ENTITLEMENT_ALLOWED)
            return EntitlementVerdict(False, REASON_ENTITLEMENT_DISABLED)

    return EntitlementVerdict(False, REASON_ENTITLEMENT_MISSING)

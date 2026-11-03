"""Test helpers for governance switches.

Deal-created automation is disabled by default (DFR1-006). Tests that exercise that
automation must enable it explicitly, as an organization administrator would.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext
from app.governance.capabilities import AUTOMATION_DEAL_CREATED_RULES, AUTOMATION_MASTER
from app.governance.service import set_capability_enabled


def enable_deal_created_automation(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
) -> None:
    """Turn on the automation master switch and the deal-created rules switch."""
    for capability_key in (AUTOMATION_MASTER, AUTOMATION_DEAL_CREATED_RULES):
        set_capability_enabled(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            capability_key=capability_key,
            is_enabled=True,
        )


DEFAULT_ENTITLEMENTS = (
    {"feature_key": "workflow_automation", "enabled": True, "limit_value": 10, "limit_unit": "runs"},
)


def attested_user_context(
    user,
    *,
    organization_id: UUID,
    subscription_status: str | None = "active",
    product_role: str | None = "owner",
    entitlements: object = DEFAULT_ENTITLEMENTS,
    sibvo_attested: bool = True,
    session_organization_id: UUID | None = None,
    sibvo_organization_id: UUID | None = None,
) -> CurrentUserContext:
    """Build the context a request gets from a SIBVO-attested session.

    The access snapshot mirrors what SIBVO returns for an active product membership. Tests
    change one argument at a time to build the negative cases.
    """
    access = {
        "organization_id": str(organization_id),
        "product_key": "dealsflo",
        "subscription_status": subscription_status,
        "product_role": product_role,
        "entitlements": list(entitlements) if isinstance(entitlements, (list, tuple)) else entitlements,
    }
    return CurrentUserContext(
        user=user,
        session_organization_id=session_organization_id or organization_id,
        sibvo_attested=sibvo_attested,
        sibvo_access=access if sibvo_attested else None,
        sibvo_subject=None,
        sibvo_session_id=None,
        sibvo_organization_id=sibvo_organization_id or organization_id,
    )


def allow_organization_entitlements(monkeypatch) -> None:
    """Stub the signed SIBVO snapshot check in the policy for gate tests.

    Snapshot signing, refresh and revalidation are covered by ``tests/test_org_entitlement_snapshot.py``.
    These tests exercise the consent, channel and approval gates, so the feature check is allowed here.
    """
    from app.governance.entitlement import EntitlementVerdict

    def verdict(db, *, organization_id, feature_key, now=None):
        return EntitlementVerdict(True, "allowed")

    monkeypatch.setattr("app.governance.policy.organization_entitlement_verdict", verdict)


def allow_actor_execution_permission(monkeypatch, permission_key: str) -> None:
    """Make the actor check require ``permission_key`` for channel and AI capabilities that name no permission.

    Develop's gate uses ``ai.execute`` by default, a key no role holds yet, so channel sends fail closed for every
    actor. The product decision for the send permission is open. These tests pass a key the test user holds, so the
    consent, channel and approval gates are the ones being exercised.
    """
    from app.governance import execution_gate

    monkeypatch.setattr(execution_gate, "DEFAULT_AI_PERMISSION", permission_key)


def allow_provider_readiness(monkeypatch) -> None:
    """Treat a provider as ready for the policy gate. Provider readiness and verification have their own tests."""
    from app.providers.readiness import ConnectionReadiness, ReadinessCode

    monkeypatch.setattr(
        "app.governance.policy.best_provider_readiness",
        lambda db, *, organization_id, provider_keys: ConnectionReadiness(True, ReadinessCode.READY, None),
    )

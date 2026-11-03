"""DFR1-053: a subscription downgrade reaches Dealsflo's execution decisions through the signed snapshot.

SIBVO owns plan activation and its seat-capacity check (contract section 4.1). Dealsflo's part is how a downgraded
snapshot replaces the grant held from the earlier snapshot. These tests use the same snapshot path and fixed clock as
``test_org_entitlement_snapshot.py`` and ``test_entitlement_lifecycle.py``.

Covered: a valid downgrade, a downgrade that is not visible before the snapshot expires, a downgrade that removes the
entitlement item, idempotent decisions after a downgrade, a downgrade for another organization, and SIBVO being
unreachable when the downgrade is due.
"""

from __future__ import annotations

# ruff: noqa: F811  (fixtures are imported from the snapshot tests and used as arguments)
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.db.models.organization_entitlement_snapshot import (
    OrganizationEntitlementSnapshot,
)
from app.db.session import SessionLocal
from app.governance.entitlement import (
    REASON_ENTITLEMENT_DISABLED,
    REASON_ENTITLEMENT_MISSING,
)
from app.integrations.org_entitlement_snapshot import compute_signature
from app.integrations.sibvo_client import SibvoUnavailable
from tests.test_org_entitlement_snapshot import (  # noqa: F401  (fixtures and helpers)
    FEATURE,
    KEY,
    KEY_ID,
    T0,
    at,
    configured,
    decide,
    organization_id,
    sibvo,
)


def _snapshot_at(
    organization_id: UUID,
    *,
    enabled: bool = True,
    issued_offset: float = 0.0,
    lifetime: float = 30.0,
    entitlements: list | None = None,
) -> dict:
    """A signed snapshot issued at ``T0 + issued_offset``, for the fixed test clock."""
    snapshot = {
        "version": 1,
        "snapshot_id": str(uuid4()),
        "attested": True,
        "organization_id": str(organization_id),
        "product_key": "dealsflo",
        "subscription_status": "active",
        "issued_at": (T0 + timedelta(seconds=issued_offset)).isoformat(),
        "expires_at": (T0 + timedelta(seconds=issued_offset + lifetime)).isoformat(),
        "entitlements": entitlements
        if entitlements is not None
        else [{"feature_key": FEATURE, "enabled": enabled}],
    }
    return {
        "active": True,
        "snapshot": snapshot,
        "signature": {"alg": "HMAC-SHA256", "kid": KEY_ID, "value": compute_signature(snapshot, KEY)},
    }


def _stored_body(organization_id: UUID):
    with SessionLocal() as db:
        row = db.scalar(
            select(OrganizationEntitlementSnapshot).where(
                OrganizationEntitlementSnapshot.organization_id == organization_id
            )
        )
        return None if row is None else row.snapshot_body


def test_a_downgrade_is_denied_once_the_next_snapshot_is_due(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: _snapshot_at(org, enabled=True)
    assert decide(organization_id, now=at(0)).allowed is True

    # The plan is downgraded at SIBVO. The new snapshot is issued at t=31 s, after the first one expired at t=30 s.
    sibvo.answer = lambda org: _snapshot_at(org, enabled=False, issued_offset=31)
    verdict = decide(organization_id, now=at(31))

    assert verdict.allowed is False
    assert verdict.reason_code == REASON_ENTITLEMENT_DISABLED
    assert len(sibvo.calls) == 2


def test_a_downgrade_is_not_visible_before_the_held_snapshot_expires(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: _snapshot_at(org, enabled=True)
    assert decide(organization_id, now=at(0)).allowed is True

    sibvo.answer = lambda org: _snapshot_at(org, enabled=False, issued_offset=10)
    still_granted = decide(organization_id, now=at(29))

    assert still_granted.allowed is True
    assert len(sibvo.calls) == 1


def test_a_downgrade_that_removes_the_entitlement_item_is_denied_as_missing(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: _snapshot_at(org, enabled=True)
    assert decide(organization_id, now=at(0)).allowed is True

    sibvo.answer = lambda org: _snapshot_at(org, issued_offset=31, entitlements=[])
    verdict = decide(organization_id, now=at(31))

    assert verdict.allowed is False
    assert verdict.reason_code == REASON_ENTITLEMENT_MISSING


def test_decisions_after_a_downgrade_make_no_further_sibvo_calls(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: _snapshot_at(org, enabled=True)
    assert decide(organization_id, now=at(0)).allowed is True

    sibvo.answer = lambda org: _snapshot_at(org, enabled=False, issued_offset=31)
    for seconds in (31, 32, 45, 60):
        verdict = decide(organization_id, now=at(seconds))
        assert verdict.allowed is False
        assert verdict.reason_code == REASON_ENTITLEMENT_DISABLED

    # One refresh at t=31 s, and the downgraded snapshot serves every later decision until it expires at t=61 s.
    assert len(sibvo.calls) == 2


def test_a_downgrade_for_another_organization_is_rejected_and_does_not_replace_this_one(
    organization_id, sibvo
) -> None:
    other_organization = uuid4()
    sibvo.answer = lambda org: _snapshot_at(org, enabled=True)
    assert decide(organization_id, now=at(0)).allowed is True
    stored_before = _stored_body(organization_id)

    sibvo.answer = lambda org: _snapshot_at(other_organization, enabled=False, issued_offset=31)
    verdict = decide(organization_id, now=at(31))

    assert verdict.allowed is False
    assert _stored_body(organization_id) == stored_before


def test_a_due_downgrade_with_sibvo_unreachable_does_not_extend_the_old_grant(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: _snapshot_at(org, enabled=True)
    assert decide(organization_id, now=at(0)).allowed is True

    sibvo.answer = SibvoUnavailable("SIBVO is unreachable.")
    verdict = decide(organization_id, now=at(31))

    assert verdict.allowed is False

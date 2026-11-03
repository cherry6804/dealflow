"""WP-A (A and B, Dealsflo side): revocation and trial expiry reach execution decisions within the bounded interval.

Existing coverage that these tests build on:
- test_org_entitlement_snapshot.py: valid, invalid, incorrectly signed, stale and unavailable snapshots; expiry
  boundaries; backoff; revocation after expiry.
- test_tenant_dependencies.py: revoked and active SIBVO session revalidation.
- test_billing_entitlements.py: trialing access is allowed.
- test_team_member_removal.py: seat release on removal.

The tests here add the missing piece: a revocation at SIBVO is not visible before the next revalidation, and is
visible exactly at it. The snapshot path is the one that governs AI execution. Automation entitlement is
revalidated per session (see the WP-A report).
"""

from __future__ import annotations

# ruff: noqa: F811  (fixtures are imported from the snapshot tests and used as arguments)
from app.governance.entitlement import REASON_TRIAL_EXPIRED
from app.governance.org_entitlement import REASON_ORGANIZATION_ACCESS_DENIED
from app.integrations.sibvo_client import SibvoUnavailable
from tests.test_org_entitlement_snapshot import (  # noqa: F401  (fixtures and helpers)
    at,
    configured,
    decide,
    organization_id,
    sibvo,
    signed,
    signed_at,
)


def test_a_revocation_at_sibvo_is_not_visible_before_the_next_revalidation(
    configured, organization_id, sibvo
) -> None:
    sibvo.answer = lambda org: signed_at(org, at(0))
    assert decide(organization_id, now=at(0)).allowed is True

    # SIBVO revokes the organization at t=5 s. Dealsflo has no reason to ask again until the snapshot is due.
    sibvo.answer = lambda org: {"active": False}
    still_cached = decide(organization_id, now=at(10))

    assert still_cached.allowed is True
    assert len(sibvo.calls) == 1

    revoked = decide(organization_id, now=at(30))

    assert revoked.allowed is False
    assert revoked.reason_code == REASON_ORGANIZATION_ACCESS_DENIED
    assert len(sibvo.calls) == 2


def test_the_revalidation_boundary_is_exact_at_thirty_seconds(configured, organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed_at(org, at(0))
    assert decide(organization_id, now=at(0)).allowed is True

    assert decide(organization_id, now=at(29.999)).allowed is True
    assert len(sibvo.calls) == 1

    # At 30 s the stored snapshot has expired. SIBVO is asked, and its fresh answer is issued at 30 s.
    sibvo.answer = lambda org: signed_at(org, at(30))
    assert decide(organization_id, now=at(30)).allowed is True
    assert len(sibvo.calls) == 2


def test_a_snapshot_for_an_expired_trial_is_denied_with_the_trial_reason(
    configured, organization_id, sibvo
) -> None:
    # SIBVO reports the trial as expired in the signed body. Dealsflo must not grant access on it.
    sibvo.answer = lambda org: signed(org, enabled=True, status="expired")

    verdict = decide(organization_id)

    assert verdict.allowed is False
    assert verdict.reason_code == REASON_TRIAL_EXPIRED


def test_a_snapshot_for_a_trial_that_is_still_running_is_granted(
    configured, organization_id, sibvo
) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True, status="trialing")

    verdict = decide(organization_id)

    assert verdict.allowed is True


def test_the_cached_grant_is_bounded_by_the_snapshot_expiry_even_without_a_revocation(
    configured, organization_id, sibvo
) -> None:
    sibvo.answer = lambda org: signed_at(org, at(0))
    assert decide(organization_id, now=at(0)).allowed is True

    # SIBVO becomes unreachable, so the cache is the only source. It stops authorizing at the expiry instant.
    sibvo.answer = SibvoUnavailable("SIBVO could not be reached.")
    assert decide(organization_id, now=at(29.999)).allowed is True
    assert decide(organization_id, now=at(30)).allowed is False

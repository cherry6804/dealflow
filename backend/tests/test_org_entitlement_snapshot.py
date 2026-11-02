"""SIBVO organization-level AI entitlement: verification, cache, expiry, outage and revocation (WS5).

The SIBVO responses in this file are unit-test fixtures built with the contract's canonical signing
rule. They prove how Dealsflo reacts to each case. They are not evidence of live connectivity, which
is recorded separately by the cross-repository contract run.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models.organization_entitlement_snapshot import (
    OrganizationEntitlementSnapshot,
)
from app.db.session import SessionLocal
from app.governance import org_entitlement
from app.governance.entitlement import (
    REASON_ENTITLEMENT_ALLOWED,
    REASON_ENTITLEMENT_DISABLED,
    REASON_ENTITLEMENT_MISSING,
    REASON_SUBSCRIPTION_NOT_ACTIVE,
)
from app.governance.org_entitlement import (
    REASON_ORGANIZATION_ACCESS_DENIED,
    REASON_SNAPSHOT_EXPIRED,
    REASON_SNAPSHOT_REJECTED,
    REASON_SNAPSHOT_UNAVAILABLE,
    organization_entitlement_verdict,
)
from app.integrations.org_entitlement_snapshot import (
    SnapshotRejected,
    compute_signature,
    verify_snapshot,
)
from app.integrations.sibvo_client import SibvoUnavailable
from tests.test_team_api import create_owner_manager

KEY = "k" * 40
KEY_ID = "v1"
FEATURE = "ai_gateway"
GOLDEN_SNAPSHOT = {
    "version": 1,
    "snapshot_id": "00000000-0000-4000-8000-000000000001",
    "attested": True,
    "organization_id": "00000000-0000-4000-8000-0000000000aa",
    "product_key": "dealsflo",
    "subscription_status": "active",
    "issued_at": "2026-11-02T10:00:00+00:00",
    "expires_at": "2026-11-02T10:00:30+00:00",
    "entitlements": [{"feature_key": "ai_gateway", "enabled": True}],
}
GOLDEN_SIGNATURE = "s_SysADUWO9e-I5cJq9zu6zkfegmWc2mt8-oN8Nqwo8"


class FakeSibvo:
    """Records calls and returns scripted answers. Stands in for SIBVO only inside these unit tests."""

    def __init__(self) -> None:
        self.calls: list[UUID] = []
        self.answer = None
        self.lock = threading.Lock()

    def __call__(self, settings, organization_id: UUID):
        with self.lock:
            self.calls.append(organization_id)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer(organization_id) if callable(self.answer) else self.answer


def signed(organization_id: UUID, *, enabled: bool = True, status: str = "active",
           issued_offset: float = 0, lifetime: float = 30, key: str = KEY,
           attested: bool = True, product: str = "dealsflo", mutate=None) -> dict:
    now = datetime.now(UTC)
    snapshot = {
        "version": 1,
        "snapshot_id": str(uuid4()),
        "attested": attested,
        "organization_id": str(organization_id),
        "product_key": product,
        "subscription_status": status,
        "issued_at": (now + timedelta(seconds=issued_offset)).isoformat(),
        "expires_at": (now + timedelta(seconds=issued_offset + lifetime)).isoformat(),
        "entitlements": [{"feature_key": FEATURE, "enabled": enabled}],
    }
    if mutate is not None:
        mutate(snapshot)
    return {
        "active": True,
        "snapshot": snapshot,
        "signature": {"alg": "HMAC-SHA256", "kid": KEY_ID, "value": compute_signature(snapshot, key)},
    }


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    settings = get_settings().model_copy(update={
        "sso_dealsflo_product_key": "dealsflo",
        "sibvo_org_snapshot_signing_key": SecretStr(KEY),
        "sibvo_org_snapshot_key_id": KEY_ID,
    })
    monkeypatch.setattr(org_entitlement, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def sibvo(monkeypatch) -> FakeSibvo:
    fake = FakeSibvo()
    monkeypatch.setattr(org_entitlement, "fetch_organization_entitlements", fake)
    return fake


@pytest.fixture
def organization_id():
    with SessionLocal() as db:
        _, organization = create_owner_manager(permissions=("governance.usage.read",))
        org_id = organization.id
    yield org_id
    with SessionLocal() as db:
        db.execute(delete(OrganizationEntitlementSnapshot).where(
            OrganizationEntitlementSnapshot.organization_id == org_id))
        db.commit()


def decide(organization_id: UUID, *, now: datetime | None = None) -> object:
    with SessionLocal() as db:
        verdict = organization_entitlement_verdict(db, organization_id=organization_id, feature_key=FEATURE, now=now)
        db.commit()
        return verdict


# Contract compatibility -------------------------------------------------------------------------


def test_canonical_signature_matches_the_golden_vector_shared_with_sibvo() -> None:
    assert compute_signature(GOLDEN_SNAPSHOT, KEY) == GOLDEN_SIGNATURE


def test_a_key_change_breaks_every_signature() -> None:
    assert compute_signature(GOLDEN_SNAPSHOT, "x" * 40) != GOLDEN_SIGNATURE


# Verification of one response ----------------------------------------------------------------


def test_valid_snapshot_verifies_and_grants_the_entitlement() -> None:
    org = uuid4()
    verified = verify_snapshot(
        signed(org), signing_key=KEY, key_id=KEY_ID, organization_id=org, product_key="dealsflo",
        now=datetime.now(UTC),
    )
    assert verified.subscription_status == "active"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"key": "y" * 40}, "signature_invalid"),
        ({"attested": False}, "not_attested"),
        ({"product": "other"}, "wrong_product"),
        ({"issued_offset": 3600}, "not_yet_valid"),
        ({"issued_offset": -120, "lifetime": 30}, "expired"),
        ({"lifetime": 300}, "lifetime_invalid"),
    ],
    ids=["bad signature", "not attested", "wrong product", "future issue", "expired", "lifetime too long"],
)
def test_invalid_snapshots_are_rejected(kwargs, reason) -> None:
    org = uuid4()
    body = signed(org, **kwargs)
    with pytest.raises(SnapshotRejected) as rejected:
        verify_snapshot(body, signing_key=KEY, key_id=KEY_ID, organization_id=org,
                        product_key="dealsflo", now=datetime.now(UTC))
    assert rejected.value.reason == reason


def test_a_snapshot_for_another_organization_is_rejected() -> None:
    org_a, org_b = uuid4(), uuid4()
    with pytest.raises(SnapshotRejected) as rejected:
        verify_snapshot(signed(org_a), signing_key=KEY, key_id=KEY_ID, organization_id=org_b,
                        product_key="dealsflo", now=datetime.now(UTC))
    assert rejected.value.reason == "wrong_organization"


def test_a_tampered_snapshot_is_rejected() -> None:
    org = uuid4()
    body = signed(org, enabled=False)
    body["snapshot"]["entitlements"][0]["enabled"] = True
    with pytest.raises(SnapshotRejected) as rejected:
        verify_snapshot(body, signing_key=KEY, key_id=KEY_ID, organization_id=org,
                        product_key="dealsflo", now=datetime.now(UTC))
    assert rejected.value.reason == "signature_invalid"


@pytest.mark.parametrize("body", [None, "text", {"active": True}, {"active": True, "snapshot": {}, "signature": {}}])
def test_malformed_bodies_are_rejected(body) -> None:
    with pytest.raises(SnapshotRejected):
        verify_snapshot(body, signing_key=KEY, key_id=KEY_ID, organization_id=uuid4(),
                        product_key="dealsflo", now=datetime.now(UTC))


def test_missing_signing_key_refuses_to_verify() -> None:
    org = uuid4()
    with pytest.raises(SnapshotRejected) as rejected:
        verify_snapshot(signed(org), signing_key=None, key_id=KEY_ID, organization_id=org,
                        product_key="dealsflo", now=datetime.now(UTC))
    assert rejected.value.reason == "signing_key_unavailable"


# Decisions: grant, denial, expiry, outage, revocation -----------------------------------------


def test_enabled_entitlement_grants_through_the_shared_rules(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True)

    verdict = decide(organization_id)

    assert verdict.allowed is True
    assert verdict.reason_code == REASON_ENTITLEMENT_ALLOWED
    assert sibvo.calls == [organization_id]


def test_subscription_without_the_entitlement_is_denied(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=False)
    verdict = decide(organization_id)
    assert verdict.allowed is False
    assert verdict.reason_code == REASON_ENTITLEMENT_DISABLED


def test_missing_entitlement_item_is_denied(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, mutate=lambda s: s.update(entitlements=[]))
    verdict = decide(organization_id)
    assert verdict.allowed is False
    assert verdict.reason_code == REASON_ENTITLEMENT_MISSING


def test_inactive_subscription_is_denied_by_the_shared_rules(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, status="past_due")
    verdict = decide(organization_id)
    assert verdict.allowed is False
    assert verdict.reason_code == REASON_SUBSCRIPTION_NOT_ACTIVE


def test_fresh_snapshot_is_served_from_the_cache_without_calling_sibvo(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True)
    decide(organization_id)
    decide(organization_id)
    assert len(sibvo.calls) == 1


def test_an_expired_snapshot_is_never_used_and_outage_denies(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True)
    decide(organization_id)
    later = datetime.now(UTC) + timedelta(seconds=31)
    sibvo.answer = SibvoUnavailable("SIBVO could not be reached.")

    verdict = decide(organization_id, now=later)

    assert verdict.allowed is False
    assert verdict.reason_code == REASON_SNAPSHOT_UNAVAILABLE


def test_refresh_after_expiry_restores_access_when_sibvo_answers(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True)
    decide(organization_id)
    later = datetime.now(UTC) + timedelta(seconds=31)
    # SIBVO issues at the refresh moment, so the fresh snapshot is valid at the decision time.
    sibvo.answer = lambda org: signed(org, enabled=True, issued_offset=31)

    assert decide(organization_id, now=later).allowed is True
    assert len(sibvo.calls) == 2


def test_revocation_is_enforced_at_the_next_revalidation_after_expiry(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True)
    assert decide(organization_id).allowed is True

    sibvo.answer = lambda org: {"active": False}
    later = datetime.now(UTC) + timedelta(seconds=31)
    verdict = decide(organization_id, now=later)

    assert verdict.allowed is False
    assert verdict.reason_code == REASON_ORGANIZATION_ACCESS_DENIED


def test_sibvo_denial_removes_a_grant_held_from_an_earlier_snapshot(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True)
    assert decide(organization_id).allowed is True

    sibvo.answer = lambda org: {"active": False}
    # Force a refresh on the same instant by moving the clock past expiry, then check the stored row.
    verdict = decide(organization_id, now=datetime.now(UTC) + timedelta(seconds=31))
    assert verdict.allowed is False
    with SessionLocal() as db:
        row = db.scalar(select(OrganizationEntitlementSnapshot).where(
            OrganizationEntitlementSnapshot.organization_id == organization_id))
        assert row.snapshot_body is None


def test_a_rejected_response_never_replaces_the_stored_snapshot(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True)
    decide(organization_id)
    with SessionLocal() as db:
        before = db.scalar(select(OrganizationEntitlementSnapshot.snapshot_body).where(
            OrganizationEntitlementSnapshot.organization_id == organization_id))

    sibvo.answer = lambda org: signed(org, enabled=True, key="z" * 40)
    verdict = decide(organization_id, now=datetime.now(UTC) + timedelta(seconds=31))

    assert verdict.allowed is False
    assert verdict.reason_code == REASON_SNAPSHOT_REJECTED
    with SessionLocal() as db:
        after = db.scalar(select(OrganizationEntitlementSnapshot.snapshot_body).where(
            OrganizationEntitlementSnapshot.organization_id == organization_id))
    assert after == before


def test_backoff_limits_retries_and_never_extends_authorization(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True)
    decide(organization_id)
    sibvo.answer = SibvoUnavailable("SIBVO could not be reached.")
    first = datetime.now(UTC) + timedelta(seconds=31)
    decide(organization_id, now=first)  # one failed refresh opens a backoff window
    calls_after_failure = len(sibvo.calls)

    during_backoff = decide(organization_id, now=first + timedelta(seconds=2))
    assert during_backoff.allowed is False
    assert during_backoff.reason_code == REASON_SNAPSHOT_EXPIRED
    assert len(sibvo.calls) == calls_after_failure  # no call during the backoff window

    much_later = first + timedelta(seconds=400)
    sibvo.answer = lambda org: signed(org, enabled=True, issued_offset=(much_later - datetime.now(UTC)).total_seconds())
    assert decide(organization_id, now=much_later).allowed is True


def test_backoff_is_capped_at_three_hundred_seconds(organization_id, sibvo) -> None:
    sibvo.answer = SibvoUnavailable("SIBVO could not be reached.")
    moment = datetime.now(UTC)
    for _ in range(12):
        decide(organization_id, now=moment)
        moment = moment + timedelta(seconds=301)  # always past the window, so each call retries

    with SessionLocal() as db:
        row = db.scalar(select(OrganizationEntitlementSnapshot).where(
            OrganizationEntitlementSnapshot.organization_id == organization_id))
        assert row.failure_count == 12
        assert row.next_refresh_attempt_at - (moment - timedelta(seconds=301)) <= timedelta(seconds=300)


def test_concurrent_decisions_produce_one_sibvo_call(organization_id, sibvo) -> None:
    sibvo.answer = lambda org: signed(org, enabled=True)
    results: list[bool] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(decide(organization_id).allowed)
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == []
    assert results == [True, True, True, True]
    assert len(sibvo.calls) == 1


def test_snapshots_never_cross_organizations(sibvo) -> None:
    org_a, org_b = uuid4(), uuid4()
    with SessionLocal() as db:
        _, a = create_owner_manager(permissions=("governance.usage.read",))
        _, b = create_owner_manager(permissions=("governance.usage.read",))
        org_a, org_b = a.id, b.id
    try:
        sibvo.answer = lambda org: signed(org, enabled=True)
        assert decide(org_a).allowed is True
        sibvo.answer = lambda org: {"active": False}
        assert decide(org_b).allowed is False
        assert sibvo.calls == [org_a, org_b]
    finally:
        with SessionLocal() as db:
            db.execute(delete(OrganizationEntitlementSnapshot).where(
                OrganizationEntitlementSnapshot.organization_id.in_([org_a, org_b])))
            db.commit()


def test_missing_snapshot_with_sibvo_unreachable_is_denied(organization_id, sibvo) -> None:
    sibvo.answer = SibvoUnavailable("SIBVO could not be reached.")
    verdict = decide(organization_id)
    assert verdict.allowed is False
    assert verdict.reason_code == REASON_SNAPSHOT_UNAVAILABLE

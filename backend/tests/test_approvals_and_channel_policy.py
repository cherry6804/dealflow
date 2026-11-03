"""DFR1-006: approval lifecycle, channel policy, contact do-not-disturb and their gate integration.

Each test creates its own organization, so nothing is shared between tests. Times are fixed so window rules
are deterministic. 2026-11-02 is a Monday. 04:00 UTC on that day is 09:30 in Asia/Kolkata (UTC+05:30).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, select

from app.db.models.approval_request import ApprovalRequest
from app.db.models.audit_event import AuditEvent
from app.db.models.channel_policy import ChannelPolicy, ContactDoNotDisturb
from app.db.models.contact import Contact
from app.db.models.contact_consent import ContactConsentRecord
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance import execution_gate
from app.governance.approvals import (
    ApprovalError,
    ApprovalInvalidError,
    check_approval_for_execution,
    consume_approval,
    decide_approval,
    payload_hash,
    request_approval,
)
from app.governance.capabilities import (
    CAPABILITY_BY_KEY,
)
from app.governance.channel_policy import (
    REASON_CHANNEL_DISABLED,
    REASON_CHANNEL_NOT_CONFIGURED,
    REASON_CONTACT_DO_NOT_DISTURB,
    REASON_OUTSIDE_MESSAGING_WINDOW,
    REASON_QUIET_HOURS,
    ChannelPolicyError,
    ChannelPolicyInput,
    evaluate_channel_policy,
    set_channel_policy,
    set_contact_do_not_disturb,
    validate_policy,
)
from app.governance.consent import ConsentSubject, record_consent
from app.governance.execution_gate import ExecutionRequest, evaluate_execution
from app.governance.service import set_capability_enabled
from tests.governance_helpers import (
    allow_actor_execution_permission,
    allow_organization_entitlements,
    allow_provider_readiness,
    attested_user_context,
)
from tests.test_activities_api import create_membership, create_user, grant_permission
from tests.test_contacts_api import create_contact
from tests.test_deals_api import create_authorized_user

APPROVAL_KEY = "channels.email"
APPROVAL_RESOURCE = "deal"
MONDAY_09_30_IST = datetime(2026, 11, 2, 4, 0, tzinfo=UTC)
MONDAY_08_30_IST = datetime(2026, 11, 2, 3, 0, tzinfo=UTC)
SUNDAY_09_30_IST = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
MONDAY_21_30_IST = datetime(2026, 11, 2, 16, 0, tzinfo=UTC)
MONDAY_07_30_IST = datetime(2026, 11, 2, 2, 0, tzinfo=UTC)
MONDAY_23_00_IST = datetime(2026, 11, 2, 17, 30, tzinfo=UTC)
MONDAY_12_00_IST = datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
ALL_DAYS = 127


@pytest.fixture
def org(monkeypatch) -> Iterator[dict[str, UUID]]:
    """An organization with a requester (may request), an approver (may decide) and a manager (may configure)."""
    with SessionLocal() as db:
        requester, organization = create_authorized_user(db, permission_keys=("governance.approvals.request",))
        approver = create_user(db)
        membership = create_membership(db, user=approver, organization=organization)
        grant_permission(db, membership=membership, permission_key="governance.approvals.decide")
        db.commit()
        ids = {"organization_id": organization.id, "requester_id": requester.id, "approver_id": approver.id}
    original = CAPABILITY_BY_KEY[APPROVAL_KEY]
    monkeypatch.setitem(CAPABILITY_BY_KEY, APPROVAL_KEY, replace(original, requires_approval=True))
    yield ids
    _cleanup(ids["organization_id"])


def _cleanup(organization_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(ApprovalRequest).where(ApprovalRequest.organization_id == organization_id))
        db.execute(delete(ChannelPolicy).where(ChannelPolicy.organization_id == organization_id))
        db.execute(delete(ContactDoNotDisturb).where(ContactDoNotDisturb.organization_id == organization_id))
        db.execute(delete(ContactConsentRecord).where(ContactConsentRecord.organization_id == organization_id))
        db.execute(delete(Contact).where(Contact.organization_id == organization_id))
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.commit()


PAYLOAD = {"action": "CREATE_FOLLOW_UP", "deal_id": "d-1", "title": "Call"}


def _request(ids: dict[str, UUID], *, payload: dict | None = None, ttl: timedelta = timedelta(hours=1), now: datetime | None = None) -> UUID:
    with SessionLocal() as db:
        row = request_approval(
            db,
            organization_id=ids["organization_id"],
            requester_user_id=ids["requester_id"],
            capability_key=APPROVAL_KEY,
            resource_type=APPROVAL_RESOURCE,
            resource_id="d-1",
            payload=payload if payload is not None else PAYLOAD,
            ttl=ttl,
            now=now,
        )
        db.commit()
        return row.id


def _decide(ids: dict[str, UUID], approval_id: UUID, *, by: str, approve: bool = True, now: datetime | None = None) -> None:
    with SessionLocal() as db:
        decide_approval(
            db,
            organization_id=ids["organization_id"],
            approver_user_id=ids[by],
            approval_id=approval_id,
            approve=approve,
            now=now,
        )
        db.commit()


def _status(approval_id: UUID) -> tuple[str, datetime | None]:
    with SessionLocal() as db:
        row = db.get(ApprovalRequest, approval_id)
        assert row is not None
        return row.status, row.consumed_at


def _use(ids: dict[str, UUID], approval_id: UUID, payload: dict | None = None, *, now: datetime | None = None) -> None:
    """Check then consume in one transaction, as the gate does."""
    with SessionLocal() as db:
        check_approval_for_execution(
            db,
            organization_id=ids["organization_id"],
            approval_id=approval_id,
            capability_key=APPROVAL_KEY,
            resource_type=APPROVAL_RESOURCE,
            resource_id="d-1",
            payload=payload if payload is not None else PAYLOAD,
            now=now,
        )
        consume_approval(db, organization_id=ids["organization_id"], approval_id=approval_id, actor_user_id=None, now=now)
        db.commit()


def _refusal(callable_) -> str:
    with pytest.raises(ApprovalError) as info:
        callable_()
    return info.value.reason_code


def _check_refusal(ids: dict[str, UUID], approval_id: UUID, payload: dict) -> str:
    """Run the execution check on its own session and return the refusal reason."""
    with SessionLocal() as db:
        return _refusal(
            lambda: check_approval_for_execution(
                db,
                organization_id=ids["organization_id"],
                approval_id=approval_id,
                capability_key=APPROVAL_KEY,
                resource_type=APPROVAL_RESOURCE,
                resource_id="d-1",
                payload=payload,
            )
        )


# --- Approval lifecycle --------------------------------------------------------------------------------


def test_a_request_is_pending_bound_to_its_payload_hash_and_audited(org) -> None:
    approval_id = _request(org)
    with SessionLocal() as db:
        row = db.get(ApprovalRequest, approval_id)
        assert row is not None
        assert row.status == "pending"
        assert row.payload_hash == payload_hash(PAYLOAD)
        assert "CREATE_FOLLOW_UP" not in row.payload_hash
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.organization_id == org["organization_id"],
                AuditEvent.action == "approval.requested",
            )
        )
        assert audit is not None
        assert "CREATE_FOLLOW_UP" not in (audit.event_metadata or "")


def test_the_hash_is_canonical_and_changes_with_any_value_change() -> None:
    assert payload_hash({"a": 1, "b": {"x": [1, 2]}}) == payload_hash({"b": {"x": [1, 2]}, "a": 1})
    assert payload_hash({"a": 1}) != payload_hash({"a": 2})
    assert payload_hash({"a": 1}) != payload_hash({"a": "1"})


@pytest.mark.parametrize(
    "bad_payload",
    [{"value": float("nan")}, {"value": object()}, {"value": "x" * (70 * 1024)}],
)
def test_unserializable_or_oversized_payloads_are_refused(bad_payload) -> None:
    with pytest.raises(ApprovalInvalidError):
        payload_hash(bad_payload)


def test_only_capabilities_that_require_approval_can_request_one(org) -> None:
    with SessionLocal() as db, pytest.raises(ApprovalInvalidError):
        request_approval(
            db,
            organization_id=org["organization_id"],
            requester_user_id=org["requester_id"],
            capability_key="ai.assistant",
            resource_type=APPROVAL_RESOURCE,
            resource_id="d-1",
            payload=PAYLOAD,
            ttl=timedelta(hours=1),
        )


@pytest.mark.parametrize("ttl", [timedelta(seconds=30), timedelta(days=8)])
def test_expiry_must_be_between_one_minute_and_seven_days(org, ttl) -> None:
    with SessionLocal() as db, pytest.raises(ApprovalInvalidError):
        request_approval(
            db,
            organization_id=org["organization_id"],
            requester_user_id=org["requester_id"],
            capability_key=APPROVAL_KEY,
            resource_type=APPROVAL_RESOURCE,
            resource_id="d-1",
            payload=PAYLOAD,
            ttl=ttl,
        )


def test_another_member_can_approve_and_the_requester_cannot_approve_their_own(org) -> None:
    approval_id = _request(org)
    with SessionLocal() as db:
        with pytest.raises(ApprovalError) as info:
            decide_approval(
                db,
                organization_id=org["organization_id"],
                approver_user_id=org["requester_id"],
                approval_id=approval_id,
                approve=True,
            )
        assert info.value.reason_code == "approval_self_decision_refused"
        db.rollback()
    assert _status(approval_id)[0] == "pending"

    _decide(org, approval_id, by="approver_id")
    assert _status(approval_id)[0] == "approved"


def test_a_decided_request_cannot_be_decided_again(org) -> None:
    approval_id = _request(org)
    _decide(org, approval_id, by="approver_id", approve=False)
    with SessionLocal() as db:
        assert _refusal(
            lambda: decide_approval(
                db,
                organization_id=org["organization_id"],
                approver_user_id=org["approver_id"],
                approval_id=approval_id,
                approve=True,
            )
        ) == "approval_not_pending"


def test_a_pending_request_that_expires_before_a_decision_is_refused_and_recorded(org) -> None:
    created = datetime.now(UTC)
    approval_id = _request(org, ttl=timedelta(minutes=5), now=created)
    later = created + timedelta(minutes=6)
    with SessionLocal() as db:
        assert _refusal(
            lambda: decide_approval(
                db,
                organization_id=org["organization_id"],
                approver_user_id=org["approver_id"],
                approval_id=approval_id,
                approve=True,
                now=later,
            )
        ) == "approval_expired"
        db.commit()
    assert _status(approval_id)[0] == "expired"


def test_an_approval_is_single_use_and_replay_is_refused(org) -> None:
    approval_id = _request(org)
    _decide(org, approval_id, by="approver_id")
    _use(org, approval_id)
    assert _status(approval_id)[1] is not None
    with SessionLocal() as db:
        assert _refusal(
            lambda: check_approval_for_execution(
                db,
                organization_id=org["organization_id"],
                approval_id=approval_id,
                capability_key=APPROVAL_KEY,
                resource_type=APPROVAL_RESOURCE,
                resource_id="d-1",
                payload=PAYLOAD,
            )
        ) == "approval_already_used"


def test_a_changed_payload_cannot_use_an_approval(org) -> None:
    approval_id = _request(org)
    _decide(org, approval_id, by="approver_id")
    changed = {**PAYLOAD, "title": "Something else"}
    with SessionLocal() as db:
        assert _refusal(
            lambda: check_approval_for_execution(
                db,
                organization_id=org["organization_id"],
                approval_id=approval_id,
                capability_key=APPROVAL_KEY,
                resource_type=APPROVAL_RESOURCE,
                resource_id="d-1",
                payload=changed,
            )
        ) == "approval_mismatch"
        assert _refusal(
            lambda: check_approval_for_execution(
                db,
                organization_id=org["organization_id"],
                approval_id=approval_id,
                capability_key=APPROVAL_KEY,
                resource_type=APPROVAL_RESOURCE,
                resource_id="other-deal",
                payload=PAYLOAD,
            )
        ) == "approval_mismatch"


def test_a_rejected_or_pending_approval_cannot_be_used(org) -> None:
    rejected = _request(org)
    _decide(org, rejected, by="approver_id", approve=False)
    pending = _request(org, payload={"n": 2})
    for approval_id, payload in ((rejected, PAYLOAD), (pending, {"n": 2})):
        assert _check_refusal(org, approval_id, payload) == "approval_not_approved"


def test_an_approved_request_expires_and_cannot_be_used_after_its_window(org) -> None:
    created = datetime.now(UTC)
    approval_id = _request(org, ttl=timedelta(minutes=5), now=created)
    _decide(org, approval_id, by="approver_id", now=created + timedelta(minutes=1))
    with SessionLocal() as db:
        assert _refusal(
            lambda: check_approval_for_execution(
                db,
                organization_id=org["organization_id"],
                approval_id=approval_id,
                capability_key=APPROVAL_KEY,
                resource_type=APPROVAL_RESOURCE,
                resource_id="d-1",
                payload=PAYLOAD,
                now=created + timedelta(minutes=6),
            )
        ) == "approval_expired"


def test_an_approval_is_invisible_to_another_organization(org) -> None:
    approval_id = _request(org)
    _decide(org, approval_id, by="approver_id")
    with SessionLocal() as db:
        _, other_org = create_authorized_user(db, permission_keys=())
        other_id = other_org.id
        db.commit()
    try:
        with SessionLocal() as db:
            assert _refusal(
                lambda: check_approval_for_execution(
                    db,
                    organization_id=other_id,
                    approval_id=approval_id,
                    capability_key=APPROVAL_KEY,
                    resource_type=APPROVAL_RESOURCE,
                    resource_id="d-1",
                    payload=PAYLOAD,
                )
            ) == "approval_not_found"
        assert _status(approval_id)[1] is None
    finally:
        _cleanup(other_id)


def test_the_api_requires_the_decide_permission_to_approve(org) -> None:
    from fastapi.testclient import TestClient

    from app.api.governance_controls import router as controls_router
    from tests.test_governance_api import _app_for

    approval_id = _request(org)
    with SessionLocal() as db:
        requester = db.get(User, org["requester_id"])
        assert requester is not None
        db.expunge(requester)
    app = _app_for(requester)
    app.include_router(controls_router)
    with TestClient(app) as client:
        client.headers.update({"X-Organization-ID": str(org["organization_id"])})
        response = client.post(f"/api/v1/governance/approvals/{approval_id}/decision", json={"approve": True})
    assert response.status_code == 403
    assert _status(approval_id)[0] == "pending"


# --- Channel policy configuration ---------------------------------------------------------------------


def _policy(**overrides) -> ChannelPolicyInput:
    values = {
        "channel": "email",
        "is_enabled": True,
        "timezone": "Asia/Kolkata",
        "messaging_days": 0b0011111,
        "messaging_start": time(9, 0),
        "messaging_end": time(18, 0),
        "quiet_start": None,
        "quiet_end": None,
    }
    values.update(overrides)
    return ChannelPolicyInput(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"channel": "fax"},
        {"timezone": "Mars/Olympus"},
        {"messaging_days": 128},
        {"messaging_start": None},
        {"messaging_start": time(9, 0), "messaging_end": time(9, 0)},
        {"messaging_days": 0},
        {"quiet_start": time(21, 0), "quiet_end": None},
        {"quiet_start": time(7, 0), "quiet_end": time(7, 0)},
    ],
)
def test_ambiguous_or_incomplete_channel_policies_are_refused(overrides) -> None:
    with pytest.raises(ChannelPolicyError):
        validate_policy(_policy(**overrides))


def test_a_disabled_channel_may_be_saved_without_a_window() -> None:
    validate_policy(_policy(is_enabled=False, messaging_days=0, messaging_start=None, messaging_end=None))


# --- Channel policy evaluation -----------------------------------------------------------------------


@pytest.fixture
def manager(org) -> Iterator[dict[str, UUID]]:
    with SessionLocal() as db:
        manager_user, manager_org = create_authorized_user(db, permission_keys=())
        ids = {"organization_id": manager_org.id, "user_id": manager_user.id}
        db.commit()
    yield ids
    _cleanup(ids["organization_id"])


def _configure(ids: dict[str, UUID], **overrides) -> None:
    with SessionLocal() as db:
        set_channel_policy(db, organization_id=ids["organization_id"], actor_user_id=ids["user_id"], policy=_policy(**overrides))
        db.commit()


def _contact(ids: dict[str, UUID]) -> UUID:
    with SessionLocal() as db:
        organization = db.get(Organization, ids["organization_id"])
        assert organization is not None
        contact = create_contact(db, organization=organization, first_name="Asha", email="asha@example.test")
        return contact.id


def _evaluate(ids: dict[str, UUID], contact_id: UUID, at: datetime) -> str | None:
    with SessionLocal() as db:
        return evaluate_channel_policy(
            db, organization_id=ids["organization_id"], channel="email", contact_id=contact_id, now=at
        )


def test_a_channel_with_no_policy_is_never_usable(manager) -> None:
    contact_id = _contact(manager)
    assert _evaluate(manager, contact_id, MONDAY_09_30_IST) == REASON_CHANNEL_NOT_CONFIGURED


def test_a_disabled_channel_is_denied_even_inside_its_window(manager) -> None:
    _configure(manager, is_enabled=False, messaging_days=0, messaging_start=None, messaging_end=None)
    assert _evaluate(manager, _contact(manager), MONDAY_09_30_IST) == REASON_CHANNEL_DISABLED


def test_the_messaging_window_is_local_and_weekday_aware(manager) -> None:
    _configure(manager)
    contact_id = _contact(manager)
    assert _evaluate(manager, contact_id, MONDAY_09_30_IST) is None
    assert _evaluate(manager, contact_id, MONDAY_08_30_IST) == REASON_OUTSIDE_MESSAGING_WINDOW
    assert _evaluate(manager, contact_id, SUNDAY_09_30_IST) == REASON_OUTSIDE_MESSAGING_WINDOW


def test_quiet_hours_that_cross_midnight_block_sending(manager) -> None:
    _configure(manager, messaging_days=ALL_DAYS, messaging_start=time(0, 0), messaging_end=time(23, 59), quiet_start=time(21, 0), quiet_end=time(7, 0))
    contact_id = _contact(manager)
    assert _evaluate(manager, contact_id, MONDAY_21_30_IST) == REASON_QUIET_HOURS
    assert _evaluate(manager, contact_id, MONDAY_07_30_IST) is None
    assert _evaluate(manager, contact_id, MONDAY_09_30_IST) is None


def test_a_window_that_crosses_midnight_is_open_late_and_closed_midday(manager) -> None:
    _configure(manager, messaging_days=ALL_DAYS, messaging_start=time(22, 0), messaging_end=time(2, 0))
    contact_id = _contact(manager)
    assert _evaluate(manager, contact_id, MONDAY_23_00_IST) is None
    assert _evaluate(manager, contact_id, MONDAY_12_00_IST) == REASON_OUTSIDE_MESSAGING_WINDOW


def test_do_not_disturb_blocks_every_send_to_that_contact_and_can_be_lifted(manager) -> None:
    _configure(manager, messaging_days=ALL_DAYS, messaging_start=time(0, 0), messaging_end=time(23, 59))
    contact_id = _contact(manager)
    with SessionLocal() as db:
        set_contact_do_not_disturb(db, organization_id=manager["organization_id"], actor_user_id=manager["user_id"], contact_id=contact_id, enabled=True)
        db.commit()
    assert _evaluate(manager, contact_id, MONDAY_09_30_IST) == REASON_CONTACT_DO_NOT_DISTURB
    with SessionLocal() as db:
        set_contact_do_not_disturb(db, organization_id=manager["organization_id"], actor_user_id=manager["user_id"], contact_id=contact_id, enabled=False)
        db.commit()
    assert _evaluate(manager, contact_id, MONDAY_09_30_IST) is None


def test_do_not_disturb_cannot_be_set_on_another_organizations_contact(manager, org) -> None:
    with SessionLocal() as db:
        from app.db.models.organization import Organization

        other = db.get(Organization, org["organization_id"])
        assert other is not None
        foreign_contact = create_contact(db, organization=other, first_name="Other", email="other@example.test")
        foreign_id = foreign_contact.id
    with SessionLocal() as db, pytest.raises(ChannelPolicyError):
        set_contact_do_not_disturb(
            db,
            organization_id=manager["organization_id"],
            actor_user_id=manager["user_id"],
            contact_id=foreign_id,
            enabled=True,
        )


# --- Gate integration -----------------------------------------------------------------------------------
#
# These run through the shared execution gate. Each test stubs only the gates it is not about: the signed SIBVO
# entitlement snapshot, the actor permission key and the rate rule for channel sends. Those gates have their own
# tests. Consent, channel policy, approval and budget behaviour is what these tests exercise.


def _gate_ready(ids: dict[str, UUID], monkeypatch) -> UUID:
    """Make a channel send reach the approval gate: entitled, permitted, rate-allowed, open window, consent granted."""
    allow_organization_entitlements(monkeypatch)
    allow_provider_readiness(monkeypatch)
    allow_actor_execution_permission(monkeypatch, "governance.approvals.request")
    original = CAPABILITY_BY_KEY[APPROVAL_KEY]
    monkeypatch.setitem(CAPABILITY_BY_KEY, APPROVAL_KEY, replace(original, entitlement_feature="channels_email"))
    monkeypatch.setitem(
        execution_gate.RATE_EXECUTION_TYPE,
        APPROVAL_KEY,
        execution_gate.RATE_EXECUTION_TYPE["automation.deal_created_rules"],
    )
    with SessionLocal() as db:
        organization = db.get(Organization, ids["organization_id"])
        assert organization is not None
        contact = create_contact(db, organization=organization, first_name="Asha", email="asha@example.test")
        contact_id = contact.id
        set_channel_policy(
            db,
            organization_id=ids["organization_id"],
            actor_user_id=ids["requester_id"],
            policy=ChannelPolicyInput(
                channel="email",
                is_enabled=True,
                timezone="UTC",
                messaging_days=ALL_DAYS,
                messaging_start=time(0, 0),
                messaging_end=time(23, 59),
                quiet_start=None,
                quiet_end=None,
            ),
        )
        record_consent(
            db,
            organization_id=ids["organization_id"],
            contact_id=contact_id,
            channel="email",
            purpose="customer_service",
            status="granted",
            source="test",
            actor_user_id=ids["requester_id"],
        )
        db.commit()
    return contact_id


def _gate(
    ids: dict[str, UUID],
    *,
    contact_id: UUID,
    approval_id: UUID | None,
    payload: dict | None,
) -> str:
    """Run one channel send through the gate and return the decision's reason code."""
    with SessionLocal() as db:
        user = db.get(User, ids["requester_id"])
        assert user is not None
        decision = evaluate_execution(
            db,
            ExecutionRequest(
                organization_id=ids["organization_id"],
                capability_key=APPROVAL_KEY,
                user_context=attested_user_context(
                    user, organization_id=ids["organization_id"], entitlements=CHANNEL_ENTITLEMENTS
                ),
                resource_type=APPROVAL_RESOURCE,
                resource_id="d-1",
                approval_id=approval_id,
                approval_payload_hash=payload_hash(payload) if payload is not None else None,
                consent=ConsentSubject(contact_id=contact_id, channel="email", purpose="customer_service"),
            ),
        )
        db.commit()
        return decision.reason_code


CHANNEL_ENTITLEMENTS = (
    {"feature_key": "channels_email", "enabled": True, "limit_value": 1000, "limit_unit": "messages"},
)


def test_the_gate_denies_an_approval_action_without_an_approval_and_allows_the_approved_one_once(org, monkeypatch) -> None:
    contact_id = _gate_ready(org, monkeypatch)
    _enable_channel_switch(org)
    assert _gate(org, contact_id=contact_id, approval_id=None, payload=None) == "approval_required"
    approval_id = _request(org)
    _decide(org, approval_id, by="approver_id")
    assert _gate(org, contact_id=contact_id, approval_id=approval_id, payload=PAYLOAD) == "allowed"
    assert _status(approval_id)[1] is not None
    assert _gate(org, contact_id=contact_id, approval_id=approval_id, payload=PAYLOAD) == "approval_already_used"


def test_a_refused_execution_does_not_consume_the_approval(org, monkeypatch) -> None:
    contact_id = _gate_ready(org, monkeypatch)
    _enable_channel_switch(org)
    approval_id = _request(org)
    _decide(org, approval_id, by="approver_id")
    assert _gate(org, contact_id=contact_id, approval_id=approval_id, payload={"title": "changed"}) == "approval_mismatch"
    assert _status(approval_id)[1] is None
    assert _gate(org, contact_id=contact_id, approval_id=approval_id, payload=PAYLOAD) == "allowed"


def test_do_not_disturb_is_checked_before_the_approval_is_considered(manager, org, monkeypatch) -> None:
    """A do-not-disturb contact is refused by the channel gate, which runs before the approval gate."""
    contact_id = _gate_ready(org, monkeypatch)
    _enable_channel_switch(org)
    with SessionLocal() as db:
        set_contact_do_not_disturb(db, organization_id=org["organization_id"], actor_user_id=org["requester_id"], contact_id=contact_id, enabled=True)
        db.commit()
    assert _gate(org, contact_id=contact_id, approval_id=None, payload=None) == "contact_do_not_disturb"
    with SessionLocal() as db:
        set_contact_do_not_disturb(db, organization_id=org["organization_id"], actor_user_id=org["requester_id"], contact_id=contact_id, enabled=False)
        db.commit()
    # Lifted: the channel gate passes, and the approval gate is the next refusal.
    assert _gate(org, contact_id=contact_id, approval_id=None, payload=None) == "approval_required"


def _enable_channel_switch(ids: dict[str, UUID]) -> None:
    """Turn on the channel capability's own switch, which the policy checks before the gates below."""
    with SessionLocal() as db:
        set_capability_enabled(
            db,
            organization_id=ids["organization_id"],
            actor_user_id=ids["requester_id"],
            capability_key=APPROVAL_KEY,
            is_enabled=True,
        )
        db.commit()



def test_two_racing_executions_cannot_both_use_one_approval(org) -> None:
    """The second execution waits on the row lock taken by the first, then sees the approval as used."""
    import threading

    approval_id = _request(org)
    _decide(org, approval_id, by="approver_id")
    first = SessionLocal()
    second_result: list[str] = []
    try:
        check_approval_for_execution(
            first,
            organization_id=org["organization_id"],
            approval_id=approval_id,
            capability_key=APPROVAL_KEY,
            resource_type=APPROVAL_RESOURCE,
            resource_id="d-1",
            payload=PAYLOAD,
        )

        def race() -> None:
            with SessionLocal() as second:
                try:
                    check_approval_for_execution(
                        second,
                        organization_id=org["organization_id"],
                        approval_id=approval_id,
                        capability_key=APPROVAL_KEY,
                        resource_type=APPROVAL_RESOURCE,
                        resource_id="d-1",
                        payload=PAYLOAD,
                    )
                    consume_approval(second, organization_id=org["organization_id"], approval_id=approval_id, actor_user_id=None)
                    second.commit()
                    second_result.append("allowed")
                except ApprovalError as error:
                    second.rollback()
                    second_result.append(error.reason_code)

        worker = threading.Thread(target=race)
        worker.start()
        consume_approval(first, organization_id=org["organization_id"], approval_id=approval_id, actor_user_id=None)
        first.commit()
        worker.join(timeout=30)
        assert not worker.is_alive()
    finally:
        first.close()
    assert second_result == ["approval_already_used"]
    assert _status(approval_id)[1] is not None

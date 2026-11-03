"""Contact consent: lifecycle, tenant isolation, API authorization and gate enforcement (DFR1-006).

Each test creates its own organizations, so nothing is shared between tests. The gate tests use a
test-only capability definition that declares a plan feature, because no production channel capability has a
confirmed plan feature yet (decision pending with SIBVO, DFR1-005). Production channel capabilities stay denied.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api import governance as governance_api  # noqa: F401  (route module under test)
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.contact_consent import ContactConsentRecord
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance import execution_gate
from app.governance.capabilities import CAPABILITY_BY_KEY
from app.governance.consent import (
    CONSENT_POLICY_VERSION,
    ConsentSubject,
    ContactNotFoundError,
    InvalidConsentError,
    consent_history,
    current_consent,
    record_consent,
)
from app.governance.execution_gate import ExecutionRequest, authorize_execution
from app.governance.service import set_capability_enabled
from tests.governance_helpers import attested_user_context
from tests.test_governance_api import _app_for
from tests.test_team_api import create_manager

BASE = "/api/v1/governance"
CHANNEL_CAPABILITY = "channels.email"
TEST_FEATURE = "channels_email"


@pytest.fixture
def tenant() -> Iterator[tuple[UUID, UUID]]:
    user, organization = create_manager(
        permissions=("governance.consent.manage", "governance.consent.read")
    )
    yield organization.id, user.id
    _cleanup(organization.id)


@pytest.fixture
def other_tenant() -> Iterator[tuple[UUID, UUID]]:
    user, organization = create_manager(permissions=("governance.consent.manage",))
    yield organization.id, user.id
    _cleanup(organization.id)


def _cleanup(organization_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(ContactConsentRecord).where(ContactConsentRecord.organization_id == organization_id))
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.execute(
            delete(OrganizationCapabilitySetting).where(
                OrganizationCapabilitySetting.organization_id == organization_id
            )
        )
        from app.db.models.channel_policy import ChannelPolicy

        db.execute(delete(ChannelPolicy).where(ChannelPolicy.organization_id == organization_id))
        db.execute(delete(Contact).where(Contact.organization_id == organization_id))
        db.commit()


def _contact(organization_id: UUID, email: str = "buyer@example.test") -> UUID:
    with SessionLocal() as db:
        contact = Contact(
            organization_id=organization_id,
            first_name="Asha",
            email=email,
            is_active=True,
        )
        db.add(contact)
        db.commit()
        return contact.id


def _record(organization_id, actor_id, contact_id, **overrides) -> ContactConsentRecord:
    values = {
        "channel": "email",
        "purpose": "marketing",
        "status": "granted",
        "source": "manual_entry",
    }
    values.update(overrides)
    with SessionLocal() as db:
        row = record_consent(
            db,
            organization_id=organization_id,
            contact_id=contact_id,
            actor_user_id=actor_id,
            **values,
        )
        db.commit()
        return row


def _state(organization_id, contact_id, *, channel="email", purpose="marketing", now=None) -> str:
    with SessionLocal() as db:
        return current_consent(
            db,
            organization_id=organization_id,
            contact_id=contact_id,
            channel=channel,
            purpose=purpose,
            now=now,
        ).effective


# --- Lifecycle, versioning and audit --------------------------------------------------------


def test_a_grant_then_a_revocation_is_append_only_versioned_and_audited(tenant) -> None:
    organization_id, actor_id = tenant
    contact_id = _contact(organization_id)

    _record(organization_id, actor_id, contact_id, status="granted", evidence_note="Form submitted")
    assert _state(organization_id, contact_id) == "granted"
    _record(organization_id, actor_id, contact_id, status="revoked")
    assert _state(organization_id, contact_id) == "revoked"

    with SessionLocal() as db:
        history = consent_history(db, organization_id=organization_id, contact_id=contact_id)
        audits = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == "consent.recorded",
            )
        ).all()
    assert [row.status for row in history] == ["granted", "revoked"]
    assert all(row.policy_version == CONSENT_POLICY_VERSION for row in history)
    assert len(audits) == 2
    revoke_audit = json.loads(
        next(audit for audit in audits if json.loads(audit.event_metadata)["status"] == "revoked").event_metadata
    )
    assert revoke_audit["previous_effective"] == "granted"


def test_a_grant_expires_at_its_time_and_is_evaluated_at_check_time(tenant) -> None:
    organization_id, actor_id = tenant
    contact_id = _contact(organization_id)
    expires = datetime.now(UTC) + timedelta(hours=1)
    _record(organization_id, actor_id, contact_id, status="granted", expires_at=expires)

    assert _state(organization_id, contact_id) == "granted"
    assert _state(organization_id, contact_id, now=expires + timedelta(seconds=1)) == "expired"


def test_no_record_means_no_consent(tenant) -> None:
    organization_id, _actor_id = tenant
    contact_id = _contact(organization_id)

    assert _state(organization_id, contact_id) == "none"


@pytest.mark.parametrize(
    "overrides",
    [
        {"channel": "fax"},
        {"purpose": "resale"},
        {"status": "maybe"},
        {"source": "Bad Source"},
        {"status": "granted", "expires_at": datetime.now(UTC) - timedelta(days=1)},
        {"status": "revoked", "expires_at": datetime.now(UTC) + timedelta(days=1)},
    ],
)
def test_invalid_consent_requests_are_refused(tenant, overrides) -> None:
    organization_id, actor_id = tenant
    contact_id = _contact(organization_id)

    with pytest.raises(InvalidConsentError):
        _record(organization_id, actor_id, contact_id, **overrides)


# --- Tenant isolation -------------------------------------------------------------------------


def test_a_contact_of_another_organization_cannot_receive_a_consent_record(tenant, other_tenant) -> None:
    organization_id, actor_id = tenant
    other_contact = _contact(other_tenant[0], email="other@example.test")

    with pytest.raises(ContactNotFoundError):
        _record(organization_id, actor_id, other_contact)
    assert _state(other_tenant[0], other_contact) == "none"


def test_consent_history_and_state_never_cross_organizations(tenant, other_tenant) -> None:
    organization_id, actor_id = tenant
    contact_id = _contact(organization_id)
    _record(organization_id, actor_id, contact_id, status="granted")

    # The same contact ID read through another organization shows nothing.
    assert _state(other_tenant[0], contact_id) == "none"
    with SessionLocal() as db:
        assert consent_history(db, organization_id=other_tenant[0], contact_id=contact_id) == []


# --- API authorization ----------------------------------------------------------------------------


def _actor_for(user_id: UUID) -> User:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        db.expunge(user)
        return user


def test_an_authorized_user_records_and_reads_consent_through_the_api(tenant) -> None:
    organization_id, actor_id = tenant
    contact_id = _contact(organization_id)

    with TestClient(_app_for(_actor_for(actor_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        created = client.post(
            f"{BASE}/consents",
            json={
                "contact_id": str(contact_id),
                "channel": "email",
                "purpose": "marketing",
                "status": "granted",
                "source": "manual_entry",
                "evidence_note": "Signed form",
                "confirm": True,
            },
        )
        read = client.get(f"{BASE}/consents", params={"contact_id": str(contact_id)})

    assert created.status_code == 201
    assert created.json()["policy_version"] == CONSENT_POLICY_VERSION
    assert read.status_code == 200
    body = read.json()
    assert body["history"][0]["status"] == "granted"
    marketing_email = next(
        item for item in body["current"] if item["channel"] == "email" and item["purpose"] == "marketing"
    )
    assert marketing_email["effective"] == "granted"


def test_a_read_only_user_cannot_record_consent(tenant) -> None:
    organization_id, _owner = tenant
    contact_id = _contact(organization_id)
    reader, reader_org = create_manager(permissions=("governance.consent.read",))
    try:
        with TestClient(_app_for(_actor_for(reader.id))) as client:
            client.headers.update({"X-Organization-ID": str(reader_org.id)})
            response = client.post(
                f"{BASE}/consents",
                json={
                    "contact_id": str(contact_id),
                    "channel": "email",
                    "purpose": "marketing",
                    "status": "granted",
                    "source": "manual_entry",
                    "confirm": True,
                },
            )
        assert response.status_code == 403
    finally:
        _cleanup(reader_org.id)


def test_the_api_does_not_reveal_another_organizations_contact(tenant, other_tenant) -> None:
    organization_id, actor_id = tenant
    foreign_contact = _contact(other_tenant[0], email="foreign@example.test")

    with TestClient(_app_for(_actor_for(actor_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        read = client.get(f"{BASE}/consents", params={"contact_id": str(foreign_contact)})
        write = client.post(
            f"{BASE}/consents",
            json={
                "contact_id": str(foreign_contact),
                "channel": "email",
                "purpose": "marketing",
                "status": "granted",
                "source": "manual_entry",
                "confirm": True,
            },
        )

    assert read.status_code == 404
    assert write.status_code == 404


# --- Gate enforcement -----------------------------------------------------------------------------


@pytest.fixture
def channel_capability(monkeypatch) -> None:
    """A test-only channel capability with a plan feature and no provider requirement."""
    original = CAPABILITY_BY_KEY[CHANNEL_CAPABILITY]
    monkeypatch.setitem(
        CAPABILITY_BY_KEY,
        CHANNEL_CAPABILITY,
        replace(original, entitlement_feature=TEST_FEATURE, requires_provider=False),
    )


def _enable_channel(organization_id, actor_id) -> None:
    """Enable the capability and an always-open email policy, so these tests isolate the consent check."""
    from datetime import time as clock

    from app.governance.channel_policy import ChannelPolicyInput, set_channel_policy

    with SessionLocal() as db:
        set_capability_enabled(
            db,
            organization_id=organization_id,
            actor_user_id=actor_id,
            capability_key=CHANNEL_CAPABILITY,
            is_enabled=True,
        )
        set_channel_policy(
            db,
            organization_id=organization_id,
            actor_user_id=actor_id,
            policy=ChannelPolicyInput(
                channel="email",
                is_enabled=True,
                timezone="UTC",
                messaging_days=127,
                messaging_start=clock(0, 0),
                messaging_end=clock(23, 59),
                quiet_start=None,
                quiet_end=None,
            ),
        )
        db.commit()


def _authorize(organization_id, actor_id, contact_id, *, channel="email", purpose="marketing", subject=True):
    with SessionLocal() as db:
        user = db.get(User, actor_id)
        assert user is not None
        context = attested_user_context(
            user,
            organization_id=organization_id,
            entitlements=[{"feature_key": TEST_FEATURE, "enabled": True}],
        )
        decision = authorize_execution(
            db,
            ExecutionRequest(
                organization_id=organization_id,
                capability_key=CHANNEL_CAPABILITY,
                actor=context,
                resource_type="contact",
                resource_id=str(contact_id),
                resource_organization_id=organization_id,
                resource_active=True,
                required_permission=None,
                consent=ConsentSubject(contact_id=contact_id, channel=channel, purpose=purpose) if subject else None,
            ),
        )
        db.commit()
        return decision


def test_a_consent_requiring_capability_without_a_contact_is_refused(tenant, channel_capability) -> None:
    organization_id, actor_id = tenant
    _enable_channel(organization_id, actor_id)

    decision = _authorize(organization_id, actor_id, _contact(organization_id), subject=False)

    assert decision.allowed is False
    assert decision.reason_code == "consent_not_configured"


def test_a_contact_without_consent_is_refused_and_granted_consent_allows(tenant, channel_capability) -> None:
    organization_id, actor_id = tenant
    _enable_channel(organization_id, actor_id)
    contact_id = _contact(organization_id)

    missing = _authorize(organization_id, actor_id, contact_id)
    assert missing.allowed is False
    assert missing.reason_code == "consent_missing"

    _record(organization_id, actor_id, contact_id, status="granted", channel="email", purpose="marketing")
    allowed = _authorize(organization_id, actor_id, contact_id)
    assert allowed.allowed is True
    assert allowed.reason_code == "allowed"


def test_a_revocation_stops_the_very_next_execution(tenant, channel_capability) -> None:
    organization_id, actor_id = tenant
    _enable_channel(organization_id, actor_id)
    contact_id = _contact(organization_id)
    _record(organization_id, actor_id, contact_id, status="granted", channel="email", purpose="marketing")
    assert _authorize(organization_id, actor_id, contact_id).allowed is True

    _record(organization_id, actor_id, contact_id, status="revoked", channel="email", purpose="marketing")

    stopped = _authorize(organization_id, actor_id, contact_id)
    assert stopped.allowed is False
    assert stopped.reason_code == "consent_revoked"


def test_an_expired_grant_is_refused_at_execution_time(tenant, channel_capability) -> None:
    organization_id, actor_id = tenant
    _enable_channel(organization_id, actor_id)
    contact_id = _contact(organization_id)
    expires = datetime.now(UTC) + timedelta(seconds=1)
    _record(
        organization_id,
        actor_id,
        contact_id,
        status="granted",
        channel="email",
        purpose="marketing",
        expires_at=expires,
    )
    assert _authorize(organization_id, actor_id, contact_id).allowed is True

    time.sleep(1.2)

    expired = _authorize(organization_id, actor_id, contact_id)
    assert expired.allowed is False
    assert expired.reason_code == "consent_expired"


def test_consent_for_another_channel_or_purpose_does_not_allow_this_execution(tenant, channel_capability) -> None:
    organization_id, actor_id = tenant
    _enable_channel(organization_id, actor_id)
    contact_id = _contact(organization_id)
    _record(organization_id, actor_id, contact_id, status="granted", channel="sms", purpose="marketing")
    _record(organization_id, actor_id, contact_id, status="granted", channel="email", purpose="customer_service")

    other_channel = _authorize(organization_id, actor_id, contact_id, channel="sms", purpose="marketing")
    assert other_channel.reason_code == "consent_channel_mismatch"
    other_purpose = _authorize(organization_id, actor_id, contact_id, channel="email", purpose="marketing")
    assert other_purpose.reason_code == "consent_missing"


def test_the_gate_decision_is_audited_with_the_consent_reason(tenant, channel_capability) -> None:
    organization_id, actor_id = tenant
    _enable_channel(organization_id, actor_id)
    contact_id = _contact(organization_id)

    _authorize(organization_id, actor_id, contact_id)

    with SessionLocal() as db:
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == "capability.execution",
            )
        )
    assert audit is not None
    assert audit.decision == "denied"
    assert json.loads(audit.event_metadata)["reason_code"] == "consent_missing"
    # The contact's identity is not written to the audit trail.
    assert "buyer@example.test" not in audit.event_metadata
    assert str(contact_id) not in (audit.event_metadata or "")


def test_every_consent_reason_has_a_user_facing_explanation() -> None:
    for code in ("consent_missing", "consent_revoked", "consent_expired", "consent_channel_mismatch"):
        assert code in execution_gate._EXPLANATIONS

"""Retention, legal holds, deletion eligibility and export/deletion request lifecycle (DFR1-050)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.models.audit_event import AuditEvent
from app.db.models.organization import Organization
from app.db.models.privacy_records import LegalHold, PrivacyDataRequest, RetentionPolicy
from app.db.session import SessionLocal
from app.governance.privacy import (
    REASON_CATEGORY_UNKNOWN,
    REASON_LEGAL_HOLD,
    REASON_NO_PRODUCER,
    REASON_NOT_CUSTOMER_DELETABLE,
    STATUS_AWAITING_ARTIFACT,
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_ELIGIBILITY_RECORDED,
    STATUS_EXPIRED,
    STATUS_READY,
    InvalidRequestStateError,
    UnknownCategoryError,
    cancel_request,
    create_privacy_request,
    evaluate_deletion,
    expire_export_if_due,
    mark_export_ready,
    place_legal_hold,
    release_legal_hold,
    set_retention_policy,
)
from tests.test_governance_api import _app_for
from tests.test_team_api import create_manager


@pytest.fixture
def tenant() -> Iterator[tuple[UUID, UUID]]:
    user, organization = create_manager(permissions=())
    yield organization.id, user.id
    with SessionLocal() as db:
        db.execute(delete(PrivacyDataRequest).where(PrivacyDataRequest.organization_id == organization.id))
        db.execute(delete(LegalHold).where(LegalHold.organization_id == organization.id))
        db.execute(delete(RetentionPolicy).where(RetentionPolicy.organization_id == organization.id))
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization.id))
        db.commit()


def _in_session(fn, *args, **kwargs):
    with SessionLocal() as db:
        db.expire_on_commit = False
        result = fn(db, *args, **kwargs)
        db.commit()
        return result


def test_retention_is_versioned_and_audited(tenant) -> None:
    organization_id, actor_id = tenant

    first = _in_session(set_retention_policy, organization_id=organization_id, actor_user_id=actor_id,
                        category_key="crm.leads", retention_days=365)
    second = _in_session(set_retention_policy, organization_id=organization_id, actor_user_id=actor_id,
                         category_key="crm.leads", retention_days=730)

    assert (first.version, second.version) == (1, 2)
    with SessionLocal() as db:
        actions = db.scalars(
            select(AuditEvent.action).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.event_type == "privacy",
            )
        ).all()
    assert actions.count("privacy.retention.changed") == 2


def test_retention_rejects_nonsense_values(tenant) -> None:
    organization_id, actor_id = tenant
    with pytest.raises(ValueError):
        _in_session(set_retention_policy, organization_id=organization_id, actor_user_id=actor_id,
                    category_key="crm.leads", retention_days=0)
    with pytest.raises(UnknownCategoryError):
        _in_session(set_retention_policy, organization_id=organization_id, actor_user_id=actor_id,
                    category_key="not.a.category", retention_days=30)


def test_legal_hold_blocks_deletion_until_released(tenant) -> None:
    organization_id, actor_id = tenant
    assert _in_session(evaluate_deletion, organization_id=organization_id, category_key="crm.leads").eligible

    hold = _in_session(place_legal_hold, organization_id=organization_id, actor_user_id=actor_id,
                       category_key="crm.leads", reason="Litigation hold 2026-41")
    blocked = _in_session(evaluate_deletion, organization_id=organization_id, category_key="crm.leads")
    assert blocked.eligible is False
    assert REASON_LEGAL_HOLD in blocked.reasons

    _in_session(release_legal_hold, organization_id=organization_id, actor_user_id=actor_id, hold_id=hold.id)
    released = _in_session(evaluate_deletion, organization_id=organization_id, category_key="crm.leads")
    assert released.eligible is True


def test_legal_hold_in_one_organization_does_not_block_another(tenant) -> None:
    organization_id, actor_id = tenant
    _in_session(place_legal_hold, organization_id=organization_id, actor_user_id=actor_id,
                category_key="crm.leads", reason="Hold")
    _, other = create_manager(permissions=())

    decision = _in_session(evaluate_deletion, organization_id=other.id, category_key="crm.leads")

    assert decision.eligible is True


@pytest.mark.parametrize("category_key", ["audit.events", "billing.records", "ai.usage", "security.credentials"])
def test_mandatory_record_and_secret_categories_are_never_customer_deletable(tenant, category_key) -> None:
    organization_id, _ = tenant

    decision = _in_session(evaluate_deletion, organization_id=organization_id, category_key=category_key)

    assert decision.eligible is False
    assert REASON_NOT_CUSTOMER_DELETABLE in decision.reasons


def test_categories_without_a_producer_are_not_reported_as_deletable(tenant) -> None:
    organization_id, _ = tenant

    decision = _in_session(evaluate_deletion, organization_id=organization_id,
                           category_key="voice.transcripts")

    assert decision.eligible is False
    assert REASON_NO_PRODUCER in decision.reasons


def test_unknown_category_is_refused(tenant) -> None:
    organization_id, _ = tenant

    decision = _in_session(evaluate_deletion, organization_id=organization_id, category_key="made.up")

    assert decision.eligible is False
    assert decision.reasons == (REASON_CATEGORY_UNKNOWN,)


def test_deletion_request_records_per_category_decisions_without_deleting(tenant) -> None:
    organization_id, actor_id = tenant

    request = _in_session(
        create_privacy_request,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_type=PrivacyDataRequest.TYPE_DELETION,
        category_keys=["crm.leads", "audit.events"],
    )

    assert request.status == STATUS_ELIGIBILITY_RECORDED
    import json

    decisions = json.loads(request.decisions)
    assert decisions["crm.leads"]["eligible"] is True
    assert decisions["audit.events"]["eligible"] is False
    assert REASON_NOT_CUSTOMER_DELETABLE in decisions["audit.events"]["reasons"]


def test_deletion_request_with_only_blocked_categories_is_blocked(tenant) -> None:
    organization_id, actor_id = tenant

    request = _in_session(
        create_privacy_request,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_type=PrivacyDataRequest.TYPE_DELETION,
        category_keys=["billing.records"],
    )

    assert request.status == STATUS_BLOCKED


def test_export_request_waits_for_an_artifact_and_never_claims_ready(tenant) -> None:
    organization_id, actor_id = tenant

    request = _in_session(
        create_privacy_request,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_type=PrivacyDataRequest.TYPE_EXPORT,
        category_keys=["crm.contacts"],
    )

    assert request.status == STATUS_AWAITING_ARTIFACT
    assert request.artifact_reference is None


def test_export_becomes_ready_only_with_an_artifact_and_then_expires(tenant) -> None:
    organization_id, actor_id = tenant
    request = _in_session(
        create_privacy_request,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_type=PrivacyDataRequest.TYPE_EXPORT,
        category_keys=["crm.contacts"],
    )
    expires = datetime.now(UTC) + timedelta(hours=1)

    ready = _in_session(
        mark_export_ready,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_id=request.id,
        artifact_reference="exports/demo/abc.zip",
        expires_at=expires,
    )
    assert ready.status == STATUS_READY

    with SessionLocal() as db:
        stored = db.get(PrivacyDataRequest, request.id)
        later = expire_export_if_due(db, request=stored, now=expires + timedelta(seconds=1))
        db.commit()
        assert later.status == STATUS_EXPIRED
        assert later.artifact_reference is None


def test_only_export_requests_can_receive_artifacts(tenant) -> None:
    organization_id, actor_id = tenant
    request = _in_session(
        create_privacy_request,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_type=PrivacyDataRequest.TYPE_DELETION,
        category_keys=["crm.leads"],
    )

    with pytest.raises(InvalidRequestStateError):
        _in_session(
            mark_export_ready,
            organization_id=organization_id,
            actor_user_id=actor_id,
            request_id=request.id,
            artifact_reference="x",
            expires_at=datetime.now(UTC),
        )


def test_cancelled_requests_cannot_be_cancelled_again_and_are_audited(tenant) -> None:
    organization_id, actor_id = tenant
    request = _in_session(
        create_privacy_request,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_type=PrivacyDataRequest.TYPE_EXPORT,
        category_keys=["crm.contacts"],
    )

    cancelled = _in_session(cancel_request, organization_id=organization_id, actor_user_id=actor_id,
                            request_id=request.id)
    assert cancelled.status == STATUS_CANCELLED
    with pytest.raises(InvalidRequestStateError):
        _in_session(cancel_request, organization_id=organization_id, actor_user_id=actor_id,
                    request_id=request.id)


def test_requests_of_another_organization_cannot_be_read_or_changed(tenant) -> None:
    organization_id, actor_id = tenant
    request = _in_session(
        create_privacy_request,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_type=PrivacyDataRequest.TYPE_EXPORT,
        category_keys=["crm.contacts"],
    )
    _, other = create_manager(permissions=())

    with pytest.raises(InvalidRequestStateError):
        _in_session(cancel_request, organization_id=other.id, actor_user_id=other.id, request_id=request.id)


def test_retention_endpoint_requires_the_privacy_manage_permission(tenant) -> None:
    reader, reader_org = create_manager(permissions=("governance.privacy.read",))
    try:
        with TestClient(_app_for(reader)) as client:
            client.headers.update({"X-Organization-ID": str(reader_org.id)})
            denied = client.put(
                "/api/v1/governance/privacy/retention/crm.leads",
                json={"retention_days": 90, "confirm": True},
            )
            listing = client.get("/api/v1/governance/privacy/retention")
    finally:
        with SessionLocal() as db:
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == reader_org.id))
            db.commit()

    assert denied.status_code == 403
    assert listing.status_code == 200
    assert all(item["retention_days"] is None for item in listing.json())


def test_privacy_request_endpoint_rejects_unknown_categories() -> None:
    user, org = create_manager(permissions=("governance.privacy.manage",))
    try:
        with TestClient(_app_for(user)) as client:
            client.headers.update({"X-Organization-ID": str(org.id)})
            response = client.post(
                "/api/v1/governance/privacy/requests",
                json={"request_type": "deletion", "categories": ["made.up"], "confirm": True},
            )
    finally:
        with SessionLocal() as db:
            db.execute(delete(PrivacyDataRequest).where(PrivacyDataRequest.organization_id == org.id))
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == org.id))
            db.commit()

    assert response.status_code == 404


def test_legal_holds_are_listed_for_the_organization_only(tenant) -> None:
    organization_id, actor_id = tenant
    _in_session(place_legal_hold, organization_id=organization_id, actor_user_id=actor_id,
                category_key="crm.leads", reason="Hold for listing")
    reader, own_org = create_manager(permissions=("governance.privacy.read",))
    try:
        with TestClient(_app_for(reader)) as client:
            # The reader belongs to own_org, so it sees only its own holds (none).
            client.headers.update({"X-Organization-ID": str(own_org.id)})
            own = client.get("/api/v1/governance/privacy/legal-holds")
            # The reader is not a member of the other organization, so it is refused.
            client.headers.update({"X-Organization-ID": str(organization_id)})
            foreign = client.get("/api/v1/governance/privacy/legal-holds")
    finally:
        with SessionLocal() as db:
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == own_org.id))
            db.commit()

    assert own.status_code == 200
    assert own.json() == []
    assert foreign.status_code == 403


def test_a_deletion_request_removes_no_data_and_an_export_creates_no_artifact(tenant) -> None:
    from app.db.models.lead import Lead
    from tests.test_deals_api import create_lead

    organization_id, actor_id = tenant
    with SessionLocal() as db:
        lead = create_lead(db, organization=db.get(Organization, organization_id))
        lead_id = lead.id
        db.commit()

    deletion = _in_session(
        create_privacy_request,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_type=PrivacyDataRequest.TYPE_DELETION,
        category_keys=["crm.leads"],
    )
    export = _in_session(
        create_privacy_request,
        organization_id=organization_id,
        actor_user_id=actor_id,
        request_type=PrivacyDataRequest.TYPE_EXPORT,
        category_keys=["crm.leads"],
    )

    assert deletion.status == STATUS_ELIGIBILITY_RECORDED
    assert export.status == STATUS_AWAITING_ARTIFACT
    assert export.artifact_reference is None
    with SessionLocal() as db:
        assert db.get(Lead, lead_id) is not None, "a deletion request must not delete the lead"

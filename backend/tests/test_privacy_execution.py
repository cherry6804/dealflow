"""Background execution of privacy export and deletion requests (DFR1-050).

These tests cover what a request record does not: generating real export artifacts (including
stored documents), executing deletions and anonymization, re-checking holds at execution time,
retention enforcement, expiry, cancellation, scheduled maintenance, retry safety, and tenant
isolation. Stored objects go to a temporary directory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.api import governance as governance_api
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.deal import Deal
from app.db.models.deal_commission import DealCommission
from app.db.models.document import Document
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.organization import Organization
from app.db.models.outbox_event import OutboxEvent
from app.db.models.payment_milestone import PaymentMilestone
from app.db.models.privacy_records import LegalHold, PrivacyDataRequest, RetentionPolicy
from app.db.models.property import Property
from app.db.models.role import Role
from app.db.models.team_invitation import TeamInvitation
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance import privacy_execution, privacy_maintenance
from app.governance.privacy import (
    STATUS_AWAITING_ARTIFACT,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_ELIGIBILITY_RECORDED,
    STATUS_PARTIALLY_COMPLETED,
    STATUS_READY,
    STATUS_READY_PARTIAL,
    create_privacy_request,
    place_legal_hold,
    set_retention_policy,
)
from app.governance.privacy_execution import (
    EXPORT_KEY_PREFIX,
    PRIVACY_PROCESS_EVENT_TYPE,
    REDACTED_NAME,
    enqueue_processing,
    process_privacy_request,
)
from app.governance.privacy_maintenance import run_export_expiry, run_retention
from app.storage import LocalObjectStorage, StorageError
from tests.test_governance_api import _app_for
from tests.test_team_api import create_manager

BASE = "/api/v1/governance"


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalObjectStorage:
    store = LocalObjectStorage(tmp_path / "objects")
    monkeypatch.setattr(privacy_execution, "get_object_storage", lambda: store)
    # The download endpoint resolves storage through its own import, so patch that name too.
    monkeypatch.setattr(governance_api, "get_object_storage", lambda: store)
    return store


@pytest.fixture
def tenant() -> Iterator[tuple[UUID, UUID]]:
    user, organization = create_manager(
        permissions=("governance.privacy.manage", "governance.privacy.read")
    )
    yield organization.id, user.id
    _cleanup(organization.id)


def _cleanup(organization_id: UUID) -> None:
    # CRM rows reference contacts, so they are removed first, in dependency order.
    with SessionLocal() as db:
        for model in (
            # Documents reference leads and properties with RESTRICT, so they go first.
            Document,
            PaymentMilestone,
            DealCommission,
            Deal,
            CustomerRequirement,
            Lead,
            CustomerProfile,
            Property,
            AiUsageEvent,
            Contact,
            PrivacyDataRequest,
            LegalHold,
            RetentionPolicy,
            OutboxEvent,
            AuditEvent,
            TeamInvitation,
        ):
            db.execute(delete(model).where(model.organization_id == organization_id))
        db.commit()


def _contact(organization_id: UUID, *, email: str = "buyer@example.test") -> UUID:
    with SessionLocal() as db:
        contact = Contact(
            organization_id=organization_id,
            first_name="Asha",
            last_name="Rao",
            email=email,
            phone="+911234567890",
            is_active=True,
        )
        db.add(contact)
        db.commit()
        return contact.id


def _document(
    organization_id: UUID, user_id: UUID, storage: LocalObjectStorage
) -> tuple[UUID, str]:
    document_id = uuid4()
    key = f"{organization_id}/{document_id.hex}/id.pdf"
    content = b"%PDF-1.4 private"
    storage.put(key, BytesIO(content))
    with SessionLocal() as db:
        db.add(
            Document(
                id=document_id,
                organization_id=organization_id,
                original_filename="id.pdf",
                display_name="ID",
                category=Document.CATEGORY_IDENTITY_KYC,
                document_type="Identity",
                content_type="application/pdf",
                file_extension=".pdf",
                file_size_bytes=len(content),
                checksum_sha256=hashlib.sha256(content).hexdigest(),
                storage_backend="local",
                storage_key=key,
                access_classification=Document.CLASSIFICATION_RESTRICTED,
                status=Document.STATUS_AVAILABLE,
                uploaded_by_user_id=user_id,
                created_by_user_id=user_id,
            )
        )
        db.commit()
    return document_id, key


def _request(
    organization_id: UUID, user_id: UUID, request_type: str, categories: list[str]
) -> UUID:
    with SessionLocal() as db:
        row = create_privacy_request(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            request_type=request_type,
            category_keys=categories,
        )
        db.commit()
        return row.id


def _run(request_id: UUID, organization_id: UUID) -> None:
    """Run the outbox handler once, the way the worker does, in a savepoint-free session."""
    event = SimpleNamespace(
        payload={"request_id": str(request_id)}, organization_id=organization_id
    )
    with SessionLocal() as db:
        process_privacy_request(db, event)
        db.commit()


def _row(request_id: UUID) -> PrivacyDataRequest:
    with SessionLocal() as db:
        row = db.scalar(
            select(PrivacyDataRequest).where(PrivacyDataRequest.id == request_id)
        )
        assert row is not None
        db.expunge(row)
        return row


def _archive_members(storage, key: str) -> dict[str, bytes]:
    with (
        storage.open_read(key) as handle,
        zipfile.ZipFile(BytesIO(handle.read())) as archive,
    ):
        return {name: archive.read(name) for name in archive.namelist()}


def _archive_document(storage, key: str) -> dict:
    return json.loads(_archive_members(storage, key)["export.json"])


def test_export_is_generated_with_an_honest_coverage_record(tenant, storage) -> None:
    organization_id, user_id = tenant
    contact_id = _contact(organization_id)
    request_id = _request(
        organization_id, user_id, "export", ["crm.contacts", "messaging.conversations"]
    )

    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_READY_PARTIAL
    assert (
        row.artifact_reference
        == f"{EXPORT_KEY_PREFIX}/{organization_id}/{request_id}.zip"
    )
    document = _archive_document(storage, row.artifact_reference)
    assert document["coverage"]["exported"] == ["crm.contacts"]
    assert document["coverage"]["not_exported"] == [
        {"category_key": "messaging.conversations", "reason": "no_producer_yet"}
    ]
    assert document["categories"]["crm.contacts"][0]["id"] == str(contact_id)
    assert document["categories"]["crm.contacts"][0]["email"] == "buyer@example.test"


def test_a_complete_export_is_marked_ready_and_a_repeat_run_changes_nothing(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    _contact(organization_id)
    request_id = _request(organization_id, user_id, "export", ["crm.contacts"])

    _run(request_id, organization_id)
    first = _row(request_id)
    _run(request_id, organization_id)
    second = _row(request_id)

    assert first.status == STATUS_READY
    assert second.artifact_reference == first.artifact_reference
    assert second.attempt_count == first.attempt_count == 1


def test_an_export_with_no_producer_creates_no_artifact(tenant, storage) -> None:
    organization_id, user_id = tenant
    request_id = _request(
        organization_id, user_id, "export", ["messaging.conversations"]
    )

    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_BLOCKED
    assert row.artifact_reference is None


def test_deletion_anonymizes_contacts_and_removes_documents_and_their_objects(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    contact_id = _contact(organization_id)
    document_id, key = _document(organization_id, user_id, storage)
    request_id = _request(
        organization_id, user_id, "deletion", ["crm.contacts", "documents.files"]
    )
    assert _row(request_id).status == STATUS_ELIGIBILITY_RECORDED

    _run(request_id, organization_id)

    row = _row(request_id)
    # Contacts are anonymized, not fully deleted, so the request cannot be complete.
    assert row.status == STATUS_PARTIALLY_COMPLETED
    execution = json.loads(row.execution)
    assert execution["documents.files"] == {"outcome": "deleted", "count": 1, "verified": True}
    assert execution["crm.contacts"]["outcome"] == "anonymized_partial"
    assert "crm.leads" in execution["crm.contacts"]["not_changed"]
    assert not storage.exists(key)
    with SessionLocal() as db:
        assert db.get(Document, document_id) is None
        contact = db.get(Contact, contact_id)
        assert contact is not None
        assert contact.first_name == REDACTED_NAME
        assert contact.email is None
        assert contact.phone is None
        assert contact.is_active is False


def test_a_deletion_limited_to_documents_completes(tenant, storage) -> None:
    organization_id, user_id = tenant
    _document(organization_id, user_id, storage)
    request_id = _request(organization_id, user_id, "deletion", ["documents.files"])

    _run(request_id, organization_id)

    assert _row(request_id).status == STATUS_COMPLETED


def test_a_repeat_deletion_run_is_a_no_op(tenant, storage) -> None:
    organization_id, user_id = tenant
    _document(organization_id, user_id, storage)
    request_id = _request(organization_id, user_id, "deletion", ["documents.files"])

    _run(request_id, organization_id)
    first = _row(request_id)
    _run(request_id, organization_id)
    second = _row(request_id)

    assert second.attempt_count == first.attempt_count == 1
    assert second.processed_at == first.processed_at


def test_a_legal_hold_placed_after_the_request_blocks_execution(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    document_id, key = _document(organization_id, user_id, storage)
    request_id = _request(organization_id, user_id, "deletion", ["documents.files"])
    with SessionLocal() as db:
        place_legal_hold(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            category_key="documents.files",
            reason="Dispute under review",
        )
        db.commit()

    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_BLOCKED
    assert json.loads(row.execution)["documents.files"]["outcome"] == "skipped"
    assert storage.exists(key)
    with SessionLocal() as db:
        assert db.get(Document, document_id) is not None


def test_a_storage_failure_rolls_back_the_deletion_so_a_retry_can_finish_it(
    tenant, storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization_id, user_id = tenant
    document_id, _key = _document(organization_id, user_id, storage)
    request_id = _request(organization_id, user_id, "deletion", ["documents.files"])

    def unavailable(key: str) -> None:
        raise StorageError("unavailable")

    monkeypatch.setattr(storage, "delete", unavailable)
    with pytest.raises(StorageError):
        _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_ELIGIBILITY_RECORDED
    with SessionLocal() as db:
        assert db.get(Document, document_id) is not None


def test_processing_is_queued_once_per_request_through_the_outbox(tenant) -> None:
    organization_id, user_id = tenant
    request_id = _request(organization_id, user_id, "export", ["crm.contacts"])
    with SessionLocal() as db:
        row = db.get(PrivacyDataRequest, request_id)
        enqueue_processing(db, row)
        enqueue_processing(db, row)
        db.commit()

    with SessionLocal() as db:
        events = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.event_type == PRIVACY_PROCESS_EVENT_TYPE,
            )
        ).all()
    assert len(events) == 1
    assert events[0].aggregate_id == str(request_id)


def _download_setup(tenant, storage) -> UUID:
    organization_id, user_id = tenant
    _contact(organization_id)
    request_id = _request(organization_id, user_id, "export", ["crm.contacts"])
    _run(request_id, organization_id)
    return request_id


def test_export_download_returns_the_artifact_with_safe_headers_and_is_audited(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    request_id = _download_setup(tenant, storage)

    with TestClient(_app_for(_actor_for(user_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        response = client.get(f"{BASE}/privacy/requests/{request_id}/export")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert json.loads(archive.read("export.json"))["categories"]["crm.contacts"]
    with SessionLocal() as db:
        audited = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "privacy.export.downloaded")
        ).all()
        assert any(event.resource_id == str(request_id) for event in audited)


def _actor_for(user_id: UUID):
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        db.expunge(user)
        return user


def test_a_download_before_the_artifact_exists_is_refused(tenant, storage) -> None:
    organization_id, user_id = tenant
    request_id = _request(organization_id, user_id, "export", ["crm.contacts"])

    with TestClient(_app_for(_actor_for(user_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        response = client.get(f"{BASE}/privacy/requests/{request_id}/export")

    assert response.status_code == 409
    assert _row(request_id).status == STATUS_AWAITING_ARTIFACT


def test_an_expired_export_is_refused_and_its_object_is_removed(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    request_id = _download_setup(tenant, storage)
    key = _row(request_id).artifact_reference
    assert key is not None and storage.exists(key)
    with SessionLocal() as db:
        row = db.get(PrivacyDataRequest, request_id)
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    with TestClient(_app_for(_actor_for(user_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        response = client.get(f"{BASE}/privacy/requests/{request_id}/export")

    assert response.status_code == 410
    assert not storage.exists(key)
    assert _row(request_id).status == "expired"


def test_another_organization_cannot_download_an_export(tenant, storage) -> None:
    request_id = _download_setup(tenant, storage)
    other_user, other_organization = create_manager(
        permissions=("governance.privacy.manage",)
    )
    try:
        with TestClient(_app_for(other_user)) as client:
            client.headers.update({"X-Organization-ID": str(other_organization.id)})
            response = client.get(f"{BASE}/privacy/requests/{request_id}/export")
        assert response.status_code == 404
    finally:
        _cleanup(other_organization.id)


def _age(model, record_id: UUID, days: int) -> None:
    """Backdate a row's created_at so retention has something to find."""
    with SessionLocal() as db:
        db.execute(
            update(model)
            .where(model.id == record_id)
            .values(created_at=datetime.now(UTC) - timedelta(days=days))
        )
        db.commit()


def _set_policy(
    organization_id: UUID, user_id: UUID, category_key: str, days: int | None
) -> None:
    with SessionLocal() as db:
        set_retention_policy(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            category_key=category_key,
            retention_days=days,
        )
        db.commit()


def _enforce(organization_id: UUID, storage) -> dict:
    with SessionLocal() as db:
        report = privacy_execution.enforce_retention(
            db,
            organization_id=organization_id,
            storage=storage,
            now=datetime.now(UTC),
        )
        db.commit()
    return report


def _invitation(
    organization_id: UUID,
    user_id: UUID,
    *,
    email: str,
    status: str = "pending",
    token_hash: str | None = None,
) -> UUID:
    with SessionLocal() as db:
        role_id = db.scalar(select(Role.id).limit(1))
        assert role_id is not None
        invitation = TeamInvitation(
            organization_id=organization_id,
            email=email,
            role_id=role_id,
            token_hash=token_hash or f"hash-{uuid4().hex}",
            status=status,
            invited_by_user_id=user_id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        db.add(invitation)
        db.commit()
        return invitation.id


@pytest.fixture
def second_tenant():
    user, organization = create_manager(permissions=())
    yield organization.id, user.id
    _cleanup(organization.id)
    with SessionLocal() as db:
        db.execute(
            delete(TeamInvitation).where(
                TeamInvitation.organization_id == organization.id
            )
        )
        db.commit()


# --- Document export -------------------------------------------------------------------------


def test_documents_are_exported_with_their_stored_files(tenant, storage) -> None:
    organization_id, user_id = tenant
    document_id, _key = _document(organization_id, user_id, storage)
    request_id = _request(organization_id, user_id, "export", ["documents.files"])

    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == "ready"
    members = _archive_members(storage, row.artifact_reference)
    member = f"files/{document_id}.pdf"
    assert members[member] == b"%PDF-1.4 private"
    manifest = json.loads(members["export.json"])
    assert manifest["categories"]["documents.files"][0]["archive_path"] == member


def test_a_missing_stored_object_excludes_the_whole_documents_category(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    _contact(organization_id)
    _document_id, key = _document(organization_id, user_id, storage)
    storage.delete(key)
    request_id = _request(
        organization_id, user_id, "export", ["crm.contacts", "documents.files"]
    )

    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == "ready_partial"
    document = _archive_document(storage, row.artifact_reference)
    assert document["coverage"]["exported"] == ["crm.contacts"]
    assert document["coverage"]["not_exported"] == [
        {"category_key": "documents.files", "reason": "stored_object_missing"}
    ]
    assert "documents.files" not in document["categories"]


def test_a_checksum_mismatch_excludes_the_documents_category(tenant, storage) -> None:
    organization_id, user_id = tenant
    _contact(organization_id)
    _document_id, key = _document(organization_id, user_id, storage)
    storage.delete(key)
    storage.put(key, BytesIO(b"tampered content"))
    request_id = _request(
        organization_id, user_id, "export", ["crm.contacts", "documents.files"]
    )

    _run(request_id, organization_id)

    document = _archive_document(storage, _row(request_id).artifact_reference)
    assert document["coverage"]["not_exported"] == [
        {"category_key": "documents.files", "reason": "stored_object_checksum_mismatch"}
    ]


def test_documents_over_the_export_size_limit_are_not_exported(
    tenant, storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization_id, user_id = tenant
    _contact(organization_id)
    _document(organization_id, user_id, storage)
    monkeypatch.setattr(
        privacy_execution,
        "get_settings",
        lambda: SimpleNamespace(privacy_export_max_bytes=4, privacy_export_ttl_days=7),
    )
    request_id = _request(
        organization_id, user_id, "export", ["crm.contacts", "documents.files"]
    )

    _run(request_id, organization_id)

    document = _archive_document(storage, _row(request_id).artifact_reference)
    assert document["coverage"]["not_exported"] == [
        {"category_key": "documents.files", "reason": "export_size_limit_exceeded"}
    ]


# --- Platform email outbox is not organization data -----------------------------------------


def test_the_platform_email_outbox_is_neither_exported_nor_deleted_per_organization(
    tenant,
) -> None:
    organization_id, user_id = tenant
    with SessionLocal() as db:
        export = create_privacy_request(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            request_type="export",
            category_keys=["messaging.email_outbox"],
        )
        deletion = create_privacy_request(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            request_type="deletion",
            category_keys=["messaging.email_outbox"],
        )
        db.commit()
        deletion_decision = json.loads(deletion.decisions)["messaging.email_outbox"]
        assert deletion.status == "blocked"
        assert deletion_decision == {
            "eligible": False,
            "reasons": ["not_organization_owned"],
        }
        export_id = export.id

    _run(export_id, organization_id)

    row = _row(export_id)
    assert row.status == "blocked"
    assert json.loads(row.execution)["not_exported"] == [
        {"category_key": "messaging.email_outbox", "reason": "not_organization_owned"}
    ]


# --- Leads and follow-ups ------------------------------------------------------------------


def test_leads_and_follow_ups_are_exported_for_their_organization_only(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    contact_id = _contact(organization_id)
    with SessionLocal() as db:
        lead = Lead(
            organization_id=organization_id,
            contact_id=contact_id,
            status="new",
            interest="Two-bedroom flat",
            is_active=True,
        )
        db.add(lead)
        db.flush()
        db.add(
            FollowUp(
                organization_id=organization_id,
                lead_id=lead.id,
                owner_user_id=user_id,
                follow_up_type="CALL",
                title="Call back on Friday",
                description="Asked about parking",
                due_at=datetime.now(UTC) + timedelta(days=2),
                status="PENDING",
            )
        )
        db.commit()
    request_id = _request(
        organization_id, user_id, "export", ["crm.leads", "crm.follow_ups"]
    )

    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_READY
    document = _archive_document(storage, row.artifact_reference)
    assert [item["interest"] for item in document["categories"]["crm.leads"]] == [
        "Two-bedroom flat"
    ]
    assert [item["title"] for item in document["categories"]["crm.follow_ups"]] == [
        "Call back on Friday"
    ]


def test_contacts_that_live_records_depend_on_are_deferred_not_anonymized(tenant, storage) -> None:
    from tests.test_deals_api import create_lead

    organization_id, user_id = tenant
    free_contact_id = _contact(organization_id, email="free@example.test")
    with SessionLocal() as db:
        organization = db.get(Organization, organization_id)
        assert organization is not None
        lead = create_lead(db, organization=organization)
        dependent_contact_id = lead.contact_id
        db.commit()
    request_id = _request(organization_id, user_id, "deletion", ["crm.contacts"])

    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_PARTIALLY_COMPLETED
    execution = json.loads(row.execution)["crm.contacts"]
    assert execution["outcome"] == "anonymized_partial"
    assert execution["deferred_dependent"] == 1
    assert "reasons" not in execution
    with SessionLocal() as db:
        free = db.get(Contact, free_contact_id)
        dependent = db.get(Contact, dependent_contact_id)
        assert free is not None and dependent is not None
        assert free.first_name == REDACTED_NAME
        assert dependent.first_name != REDACTED_NAME
        assert dependent.is_active is True


def _profile_for(organization_id: UUID, contact_id: UUID) -> UUID:
    with SessionLocal() as db:
        profile = CustomerProfile(
            organization_id=organization_id,
            contact_id=contact_id,
            is_active=True,
            customer_notes="Prefers weekend visits",
        )
        db.add(profile)
        db.commit()
        return profile.id


def test_contacts_referenced_by_a_customer_profile_are_deferred(tenant, storage) -> None:
    organization_id, user_id = tenant
    dependent_id = _contact(organization_id, email="profile@example.test")
    independent_id = _contact(organization_id, email="free2@example.test")
    _profile_for(organization_id, dependent_id)
    request_id = _request(organization_id, user_id, "deletion", ["crm.contacts"])

    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_PARTIALLY_COMPLETED
    assert json.loads(row.execution)["crm.contacts"]["deferred_dependent"] == 1
    with SessionLocal() as db:
        dependent = db.get(Contact, dependent_id)
        independent = db.get(Contact, independent_id)
        assert dependent is not None and independent is not None
        assert dependent.email == "profile@example.test"
        assert dependent.is_active is True
        assert independent.first_name == REDACTED_NAME


def test_dependencies_are_checked_when_the_deletion_runs_not_when_requested(tenant, storage) -> None:
    organization_id, user_id = tenant
    contact_id = _contact(organization_id, email="late-link@example.test")
    request_id = _request(organization_id, user_id, "deletion", ["crm.contacts"])
    # A dependency created after the request was recorded must still be respected.
    _profile_for(organization_id, contact_id)

    _run(request_id, organization_id)

    assert json.loads(_row(request_id).execution)["crm.contacts"]["deferred_dependent"] == 1
    with SessionLocal() as db:
        contact = db.get(Contact, contact_id)
        assert contact is not None and contact.email == "late-link@example.test"


def test_a_retry_after_a_failure_re_evaluates_dependencies(tenant, storage, monkeypatch) -> None:
    organization_id, user_id = tenant
    contact_id = _contact(organization_id, email="retry@example.test")
    profile_id = _profile_for(organization_id, contact_id)
    request_id = _request(organization_id, user_id, "deletion", ["crm.contacts"])

    original = privacy_execution._anonymize_contacts
    calls = {"count": 0}

    def fail_once(db, organization_id):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated failure during deletion")
        return original(db, organization_id)

    monkeypatch.setattr(privacy_execution, "_anonymize_contacts", fail_once)
    with pytest.raises(RuntimeError):
        _run(request_id, organization_id)
    assert _row(request_id).status == STATUS_ELIGIBILITY_RECORDED

    # The dependency is removed between attempts. The retry must see the change, not a cached result.
    with SessionLocal() as db:
        db.execute(delete(CustomerProfile).where(CustomerProfile.id == profile_id))
        db.commit()
    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_PARTIALLY_COMPLETED
    execution = json.loads(row.execution)["crm.contacts"]
    assert execution["outcome"] == "anonymized_partial"
    assert "deferred_dependent" not in execution
    with SessionLocal() as db:
        contact = db.get(Contact, contact_id)
        assert contact is not None and contact.first_name == REDACTED_NAME


def test_every_artifact_lists_organization_data_that_is_not_covered(tenant, storage) -> None:
    organization_id, user_id = tenant
    _contact(organization_id)
    request_id = _request(organization_id, user_id, "export", ["crm.contacts"])

    _run(request_id, organization_id)

    coverage = _archive_document(storage, _row(request_id).artifact_reference)["coverage"]
    not_covered = {item["table"]: item for item in coverage["not_covered"]}
    # Decision D3: billing and audit records are listed, not silently omitted.
    assert "billing_reconciliation_records" in not_covered
    assert "audit_events" in not_covered
    # Decision D5: platform email is outside organization export.
    assert "email_outbox_messages" in not_covered
    # Decision D6: SIBVO-owned membership and subscriptions are referred to SIBVO.
    assert not_covered["subscriptions"]["classification"] == "SIBVO-owned (decision D6)"
    assert all(item["reason"] for item in coverage["not_covered"])


def test_crm_sub_records_are_exported_under_their_parent_category(tenant, storage) -> None:
    from app.db.models.activity import Activity
    from app.db.models.customer_requirement import CustomerRequirement
    from app.db.models.customer_requirement_location import CustomerRequirementLocation
    from app.db.models.organization import Organization
    from tests.test_deals_api import create_lead

    organization_id, user_id = tenant
    with SessionLocal() as db:
        organization = db.get(Organization, organization_id)
        user = db.get(User, user_id)
        assert organization is not None and user is not None
        lead = create_lead(db, organization=organization)
        requirement = CustomerRequirement(
            organization_id=organization_id,
            status="ACTIVE",
            is_active=True,
            lead_id=lead.id,
        )
        db.add(requirement)
        db.flush()
        db.add(
            CustomerRequirementLocation(
                organization_id=organization_id,
                customer_requirement_id=requirement.id,
                city="Bengaluru",
                locality="Whitefield",
                is_active=True,
            )
        )
        db.add(
            Activity(
                organization_id=organization_id,
                lead_id=lead.id,
                actor_id=user.id,
                activity_type="NOTE",
                title="Called about the flat",
                description="Wants a south-facing unit",
                details={"internal": "not exported"},
                occurred_at=datetime.now(UTC),
            )
        )
        db.commit()

    request_id = _request(organization_id, user_id, "export", ["crm.requirements", "crm.follow_ups"])
    _run(request_id, organization_id)

    document = _archive_document(storage, _row(request_id).artifact_reference)
    locations = document["categories"]["crm.requirements/requirement_locations"]
    assert [item["city"] for item in locations] == ["Bengaluru"]
    activities = document["categories"]["crm.follow_ups/activities"]
    assert activities[0]["title"] == "Called about the flat"
    # Actor identifiers and unreviewed JSON details are never exported.
    serialized = json.dumps(document)
    assert "not exported" not in serialized
    assert str(user_id) not in serialized


def test_a_property_that_owns_a_contact_defers_that_contact(tenant, storage) -> None:
    from app.db.models.organization import Organization
    from tests.test_deals_api import create_property

    organization_id, user_id = tenant
    contact_id = _contact(organization_id, email="owner@example.test")
    with SessionLocal() as db:
        organization = db.get(Organization, organization_id)
        assert organization is not None
        property_record = create_property(db, organization=organization)
        property_record.owner_contact_id = contact_id
        db.commit()
    request_id = _request(organization_id, user_id, "deletion", ["crm.contacts"])

    _run(request_id, organization_id)

    assert json.loads(_row(request_id).execution)["crm.contacts"]["deferred_dependent"] == 1
    with SessionLocal() as db:
        contact = db.get(Contact, contact_id)
        assert contact is not None and contact.email == "owner@example.test"


def test_a_failed_post_deletion_check_rolls_back_and_never_completes(tenant, storage, monkeypatch) -> None:
    organization_id, user_id = tenant
    document_id, key = _document(organization_id, user_id, storage)
    request_id = _request(organization_id, user_id, "deletion", ["documents.files"])
    # The stored object is not actually removed, so the post-deletion check must fail.
    monkeypatch.setattr(storage, "delete", lambda _key: None)

    with pytest.raises(privacy_execution.PrivacyExecutionError):
        _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_ELIGIBILITY_RECORDED
    with SessionLocal() as db:
        assert db.get(Document, document_id) is not None
    assert storage.exists(key)


def test_a_legal_hold_blocks_deletion_but_not_export(tenant, storage) -> None:
    organization_id, user_id = tenant
    _document(organization_id, user_id, storage)
    with SessionLocal() as db:
        place_legal_hold(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            category_key="documents.files",
            reason="Litigation hold",
        )
        db.commit()
    export_id = _request(organization_id, user_id, "export", ["documents.files"])

    _run(export_id, organization_id)

    assert _row(export_id).status == STATUS_READY
    with SessionLocal() as db:
        from app.governance.privacy import evaluate_deletion

        decision = evaluate_deletion(db, organization_id=organization_id, category_key="documents.files")
    assert decision.eligible is False
    assert "legal_hold_active" in decision.reasons


def test_a_read_only_administrator_cannot_request_or_download_exports(tenant, storage) -> None:
    organization_id, user_id = tenant
    export_id = _request(organization_id, user_id, "export", ["crm.contacts"])
    _run(export_id, organization_id)
    read_only_user, read_only_org = create_manager(permissions=("governance.privacy.read",))
    try:
        with TestClient(_app_for(_actor_for(read_only_user.id))) as client:
            client.headers.update({"X-Organization-ID": str(read_only_org.id)})
            request = client.post(
                f"{BASE}/privacy/requests",
                json={"request_type": "export", "categories": ["crm.contacts"], "confirm": True},
            )
            download = client.get(f"{BASE}/privacy/requests/{export_id}/export")
        assert request.status_code == 403
        assert download.status_code in {403, 404}
    finally:
        _cleanup(read_only_org.id)


# --- Customer profiles, requirements, deals and AI usage --------------------------------------


def test_crm_deals_profiles_requirements_and_usage_are_exported_for_their_organization_only(
    tenant, storage
) -> None:
    from datetime import UTC as _UTC
    from decimal import Decimal

    from app.db.models.ai_usage_event import AiUsageEvent
    from app.db.models.customer_requirement import CustomerRequirement
    from app.db.models.deal_commission import DealCommission
    from app.db.models.organization import Organization
    from app.db.models.payment_milestone import PaymentMilestone
    from tests.test_automation_execution_service import create_test_deal
    from tests.test_deals_api import create_lead

    organization_id, user_id = tenant
    other_user, other_organization = create_manager(permissions=())
    try:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            organization = db.get(Organization, organization_id)
            assert user is not None and organization is not None
            lead = create_lead(db, organization=organization)
            deal = create_test_deal(db, user=user, organization=organization, lead_id=lead.id)
            db.add(
                PaymentMilestone(
                    organization_id=organization_id,
                    deal_id=deal.id,
                    name="Booking",
                    amount=Decimal("100000.00"),
                    currency="INR",
                    due_at=datetime.now(_UTC),
                    status="PENDING",
                )
            )
            db.add(
                DealCommission(
                    organization_id=organization_id,
                    deal_id=deal.id,
                    commission_type="FIXED",
                    fixed_amount=Decimal("5000.00"),
                    currency="INR",
                    status="AGREED",
                    terms="Agreed on site",
                )
            )
            db.add(
                CustomerRequirement(
                    organization_id=organization_id,
                    status="ACTIVE",
                    is_active=True,
                    lead_id=lead.id,
                    customer_profile_id=deal.customer_profile_id,
                )
            )
            db.add(
                AiUsageEvent(
                    organization_id=organization_id,
                    idempotency_key="export-usage-1",
                    unit="tokens_output",
                    reserved_quantity=5,
                    quantity=5,
                    status="recorded",
                    occurred_at=datetime.now(_UTC),
                    capability_key="ai.assistant",
                )
            )
            db.commit()
            deal_id = str(deal.id)
            profile_id = str(deal.customer_profile_id)

        # Another organization's deal must never appear in this organization's export.
        with SessionLocal() as db:
            other_org = db.get(Organization, other_organization.id)
            other_owner = db.get(User, other_user.id)
            other_lead = create_lead(db, organization=other_org)
            other_deal = create_test_deal(
                db, user=other_owner, organization=other_org, lead_id=other_lead.id
            )
            db.commit()
            other_deal_id = str(other_deal.id)

        request_id = _request(
            organization_id,
            user_id,
            "export",
            ["crm.deals", "crm.customer_profiles", "crm.requirements", "ai.usage"],
        )
        _run(request_id, organization_id)

        row = _row(request_id)
        assert row.status == STATUS_READY
        document = _archive_document(storage, row.artifact_reference)
        assert document["coverage"]["not_exported"] == []
        deals = document["categories"]["crm.deals"]
        assert [item["id"] for item in deals] == [deal_id]
        assert deals[0]["payment_milestones"][0]["name"] == "Booking"
        assert deals[0]["commissions"][0]["terms"] == "Agreed on site"
        assert profile_id in [item["id"] for item in document["categories"]["crm.customer_profiles"]]
        assert len(document["categories"]["crm.requirements"]) == 1
        usage = document["categories"]["ai.usage"]
        assert [item["capability_key"] for item in usage] == ["ai.assistant"]
        assert other_deal_id not in json.dumps(document)
    finally:
        _cleanup(other_organization.id)


# --- Team invitations ----------------------------------------------------------------------


def test_invitation_exports_omit_the_token_hash(tenant, storage) -> None:
    organization_id, user_id = tenant
    secret_hash = f"secret-token-hash-{uuid4().hex}"
    _invitation(
        organization_id,
        user_id,
        email="invitee@example.test",
        token_hash=secret_hash,
    )
    request_id = _request(organization_id, user_id, "export", ["team.invitations"])

    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == "ready"
    text = _archive_members(storage, row.artifact_reference)["export.json"].decode()
    assert "invitee@example.test" in text
    assert secret_hash not in text


def test_deleting_invitations_anonymizes_the_address_and_revokes_pending_ones(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    pending_id = _invitation(organization_id, user_id, email="pending@example.test")
    accepted_id = _invitation(
        organization_id, user_id, email="done@example.test", status="accepted"
    )
    request_id = _request(organization_id, user_id, "deletion", ["team.invitations"])

    _run(request_id, organization_id)

    assert _row(request_id).status == "completed"
    with SessionLocal() as db:
        pending = db.get(TeamInvitation, pending_id)
        accepted = db.get(TeamInvitation, accepted_id)
        assert pending is not None and accepted is not None
        assert pending.email == f"redacted-{pending_id}@redacted.invalid"
        assert pending.status == "revoked"
        assert pending.revoked_at is not None
        assert accepted.email == f"redacted-{accepted_id}@redacted.invalid"
        assert accepted.status == "accepted"


# --- Retention enforcement -----------------------------------------------------------------


def test_retention_removes_only_documents_older_than_the_period(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    old_id, old_key = _document(organization_id, user_id, storage)
    new_id, new_key = _document(organization_id, user_id, storage)
    _age(Document, old_id, days=5)
    _set_policy(organization_id, user_id, "documents.files", days=2)

    report = _enforce(organization_id, storage)

    assert report["documents.files"]["outcome"] == "deleted"
    assert report["documents.files"]["count"] == 1
    assert report["documents.files"]["retention_days"] == 2
    assert not storage.exists(old_key)
    assert storage.exists(new_key)
    with SessionLocal() as db:
        assert db.get(Document, old_id) is None
        assert db.get(Document, new_id) is not None
        audited = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == "privacy.retention.enforced",
            )
        ).all()
        assert len(audited) == 1


def test_a_legal_hold_stops_retention_and_is_audited(tenant, storage) -> None:
    organization_id, user_id = tenant
    document_id, key = _document(organization_id, user_id, storage)
    _age(Document, document_id, days=10)
    _set_policy(organization_id, user_id, "documents.files", days=1)
    with SessionLocal() as db:
        place_legal_hold(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            category_key="documents.files",
            reason="Litigation hold",
        )
        db.commit()

    report = _enforce(organization_id, storage)

    assert report["documents.files"]["outcome"] == "skipped"
    assert report["documents.files"]["reasons"] == ["legal_hold_active"]
    assert storage.exists(key)
    with SessionLocal() as db:
        assert db.get(Document, document_id) is not None
        assert (
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "privacy.retention.skipped"
                )
            ).first()
            is not None
        )


def test_contacts_with_a_period_are_reported_as_not_enforced_and_left_alone(
    tenant, storage
) -> None:
    organization_id, user_id = tenant
    contact_id = _contact(organization_id)
    _age(Contact, contact_id, days=400)
    _set_policy(organization_id, user_id, "crm.contacts", days=30)

    report = _enforce(organization_id, storage)

    assert report["crm.contacts"] == {
        "outcome": "not_enforced",
        "reasons": ["retention_enforcement_not_built"],
    }
    with SessionLocal() as db:
        contact = db.get(Contact, contact_id)
        assert contact is not None and contact.first_name == "Asha"


def test_retention_for_invitations_anonymizes_old_ones(tenant, storage) -> None:
    organization_id, user_id = tenant
    invitation_id = _invitation(organization_id, user_id, email="old@example.test")
    with SessionLocal() as db:
        db.execute(
            update(TeamInvitation)
            .where(TeamInvitation.id == invitation_id)
            .values(created_at=datetime.now(UTC) - timedelta(days=60))
        )
        db.commit()
    _set_policy(organization_id, user_id, "team.invitations", days=30)

    report = _enforce(organization_id, storage)

    assert report["team.invitations"]["outcome"] == "anonymized"
    with SessionLocal() as db:
        invitation = db.get(TeamInvitation, invitation_id)
        assert invitation is not None
        assert invitation.email == f"redacted-{invitation_id}@redacted.invalid"
        assert invitation.status == "revoked"


def test_retention_is_idempotent_and_never_touches_another_organization(
    tenant, second_tenant, storage
) -> None:
    organization_id, user_id = tenant
    other_organization_id, other_user_id = second_tenant
    own_id, own_key = _document(organization_id, user_id, storage)
    other_id, other_key = _document(other_organization_id, other_user_id, storage)
    _age(Document, own_id, days=9)
    _age(Document, other_id, days=9)
    _set_policy(organization_id, user_id, "documents.files", days=1)

    first = _enforce(organization_id, storage)
    second = _enforce(organization_id, storage)

    assert first["documents.files"]["count"] == 1
    assert second["documents.files"]["count"] == 0
    assert not storage.exists(own_key)
    assert storage.exists(other_key)
    with SessionLocal() as db:
        assert db.get(Document, other_id) is not None


def test_a_category_without_a_period_is_not_touched(tenant, storage) -> None:
    organization_id, user_id = tenant
    document_id, key = _document(organization_id, user_id, storage)
    _age(Document, document_id, days=400)
    _set_policy(organization_id, user_id, "documents.files", days=None)

    report = _enforce(organization_id, storage)

    assert report["documents.files"] == {"outcome": "no_period"}
    assert storage.exists(key)


# --- Expiry, cancellation and scheduled maintenance -------------------------------------------


def _ready_export(tenant, storage) -> UUID:
    organization_id, user_id = tenant
    _contact(organization_id)
    request_id = _request(organization_id, user_id, "export", ["crm.contacts"])
    _run(request_id, organization_id)
    return request_id


def test_the_expiry_job_expires_due_exports_and_removes_their_objects(
    tenant, storage
) -> None:
    _organization_id, _user_id = tenant
    request_id = _ready_export(tenant, storage)
    key = _row(request_id).artifact_reference
    with SessionLocal() as db:
        request = db.get(PrivacyDataRequest, request_id)
        request.expires_at = datetime.now(UTC) - timedelta(minutes=5)
        db.commit()

    report = run_export_expiry(SessionLocal, now=datetime.now(UTC), storage=storage)

    assert report["expired"] >= 1
    assert not storage.exists(key)
    row = _row(request_id)
    assert row.status == "expired"
    assert row.artifact_reference is None


def test_the_expiry_job_leaves_unexpired_exports_alone(tenant, storage) -> None:
    request_id = _ready_export(tenant, storage)
    key = _row(request_id).artifact_reference

    run_export_expiry(SessionLocal, now=datetime.now(UTC), storage=storage)

    assert storage.exists(key)
    assert _row(request_id).status == "ready"


def test_cancelling_a_ready_export_removes_its_object(
    tenant, storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization_id, user_id = tenant
    request_id = _ready_export(tenant, storage)
    key = _row(request_id).artifact_reference
    assert key is not None and storage.exists(key)

    with TestClient(_app_for(_actor_for(user_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        response = client.post(f"{BASE}/privacy/requests/{request_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert not storage.exists(key)


def test_one_failing_organization_does_not_stop_retention_for_the_others(
    tenant, second_tenant, storage, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    organization_id, user_id = tenant
    other_organization_id, other_user_id = second_tenant
    _own_id, own_key = _document(organization_id, user_id, storage)
    other_id, other_key = _document(other_organization_id, other_user_id, storage)
    for record_id in (_own_id, other_id):
        _age(Document, record_id, days=9)
    _set_policy(organization_id, user_id, "documents.files", days=1)
    _set_policy(other_organization_id, other_user_id, "documents.files", days=1)

    original = privacy_maintenance.enforce_retention

    def failing_for_one_tenant(db, *, organization_id: UUID, storage, now):
        if organization_id == tenant_org:
            raise RuntimeError("simulated outage for this organization only")
        return original(db, organization_id=organization_id, storage=storage, now=now)

    tenant_org = organization_id
    monkeypatch.setattr(
        privacy_maintenance, "enforce_retention", failing_for_one_tenant
    )
    caplog.set_level(logging.ERROR)

    report = run_retention(SessionLocal, now=datetime.now(UTC), storage=storage)

    assert report["failed"] == 1
    assert storage.exists(own_key)
    assert not storage.exists(other_key)
    assert "buyer@example.test" not in caplog.text
    failures = [
        record
        for record in caplog.records
        if record.getMessage() == "privacy_maintenance_failed"
    ]
    assert failures and failures[0].error_type == "RuntimeError"


def test_retention_jobs_never_expose_personal_data_in_logs(
    tenant, storage, caplog
) -> None:
    organization_id, user_id = tenant
    _contact(organization_id, email="private.person@example.test")
    _set_policy(organization_id, user_id, "crm.contacts", days=30)
    caplog.set_level(logging.DEBUG)

    run_retention(SessionLocal, now=datetime.now(UTC), storage=storage)

    assert "private.person@example.test" not in caplog.text

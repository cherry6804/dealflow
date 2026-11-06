"""DFR1-050 completion: export coverage, CRM free-text deletion, explicit execution, import attachments,
redaction of outbox and log output, and the retention audit trail.

The suite runs against the isolated test database only. Stored objects and uploads go to temporary
directories, so nothing is written under the repository.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models.activity import Activity
from app.db.models.audit_event import AuditEvent
from app.db.models.channel_policy import ContactDoNotDisturb
from app.db.models.contact import Contact
from app.db.models.contact_consent import ContactConsentRecord
from app.db.models.customer_profile import CustomerProfile
from app.db.models.deal import Deal
from app.db.models.deal_commission import DealCommission
from app.db.models.deal_negotiation import DealNegotiation, DealNegotiationHistory
from app.db.models.deal_stage_history import DealStageHistory
from app.db.models.document import Document
from app.db.models.follow_up import FollowUp
from app.db.models.import_batch import ImportBatch
from app.db.models.lead import Lead
from app.db.models.organization import Organization
from app.db.models.outbox_event import OutboxEvent
from app.db.models.payment_milestone import PaymentMilestone
from app.db.models.privacy_records import LegalHold, PrivacyDataRequest, RetentionPolicy
from app.db.models.property import Property
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance import privacy_execution, privacy_maintenance
from app.governance.privacy import (
    STATUS_BLOCKED,
    STATUS_ELIGIBILITY_RECORDED,
    STATUS_PARTIALLY_COMPLETED,
    STATUS_READY,
    InvalidRequestStateError,
    create_privacy_request,
    place_legal_hold,
    set_retention_policy,
)
from app.governance.privacy_execution import (
    REDACTED_NAME,
    enforce_retention,
    process_privacy_request,
    request_deletion_execution,
)
from app.outbox.service import _describe_error
from app.storage import LocalObjectStorage, StorageError
from tests.test_deals_api import create_customer_profile, create_lead, create_property
from tests.test_governance_api import _app_for
from tests.test_team_api import create_owner_manager

BASE = "/api/v1/governance"


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalObjectStorage:
    store = LocalObjectStorage(tmp_path / "objects")
    monkeypatch.setattr(privacy_execution, "get_object_storage", lambda: store)
    return store


@pytest.fixture
def upload_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the import upload root at a temporary directory, for both the privacy code and the import storage."""
    from app.imports import storage as imports_storage

    root = tmp_path / "uploads"
    root.mkdir()
    real = get_settings()

    class _UploadSettings:
        upload_storage_dir = root

        def __getattr__(self, name: str):
            return getattr(real, name)

    monkeypatch.setattr(privacy_execution, "get_settings", lambda: _UploadSettings())
    monkeypatch.setattr(imports_storage, "get_settings", lambda: _UploadSettings())
    return root


@pytest.fixture
def tenant() -> Iterator[tuple[UUID, UUID]]:
    user, organization = create_owner_manager(
        permissions=("governance.privacy.manage", "governance.privacy.read")
    )
    yield organization.id, user.id
    _cleanup(organization.id)


def _cleanup(organization_id: UUID) -> None:
    from app.db.models.notification import Notification
    from app.db.models.notification_preference import NotificationPreference
    from app.db.models.referral import Referral
    from app.db.models.site_visit import SiteVisit
    from app.db.models.team_member_removal import TeamMemberRemoval

    # Dependent rows first. Contacts are referenced by leads, profiles and properties, and import batches by contacts.
    with SessionLocal() as db:
        for model in (
            Document,
            PaymentMilestone,
            DealCommission,
            DealStageHistory,
            DealNegotiationHistory,
            DealNegotiation,
            Deal,
            FollowUp,
            SiteVisit,
            Referral,
            Notification,
            NotificationPreference,
            TeamMemberRemoval,
            Activity,
            Lead,
            CustomerProfile,
            Property,
            ContactConsentRecord,
            ContactDoNotDisturb,
            Contact,
            ImportBatch,
            PrivacyDataRequest,
            LegalHold,
            RetentionPolicy,
            OutboxEvent,
            AuditEvent,
        ):
            db.execute(delete(model).where(model.organization_id == organization_id))
        db.commit()


def _request(organization_id: UUID, user_id: UUID, request_type: str, categories: list[str]) -> UUID:
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
    """Run the outbox handler once, the way the worker does."""
    event = SimpleNamespace(payload={"request_id": str(request_id)}, organization_id=organization_id)
    with SessionLocal() as db:
        process_privacy_request(db, event)
        db.commit()


def _execute(request_id: UUID, organization_id: UUID, user_id: UUID) -> None:
    with SessionLocal() as db:
        request_deletion_execution(
            db, organization_id=organization_id, actor_user_id=user_id, request_id=request_id
        )
        db.commit()


def _row(request_id: UUID) -> PrivacyDataRequest:
    with SessionLocal() as db:
        row = db.scalar(select(PrivacyDataRequest).where(PrivacyDataRequest.id == request_id))
        assert row is not None
        db.expunge(row)
        return row


def _execution(request_id: UUID) -> dict:
    return json.loads(_row(request_id).execution)


def _archive_members(storage, key: str) -> dict[str, bytes]:
    import zipfile

    with storage.open_read(key) as handle, zipfile.ZipFile(BytesIO(handle.read())) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _archive_document(storage, key: str) -> dict:
    return json.loads(_archive_members(storage, key)["export.json"])


def _actor(user_id: UUID) -> User:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        db.expunge(user)
        return user


def _crm_fixture(organization_id: UUID, user_id: UUID) -> dict[str, UUID]:
    """One lead, profile, deal with a commission, follow-up and activity, all carrying free text."""
    with SessionLocal() as db:
        organization = db.get(Organization, organization_id)
        assert organization is not None
        lead = create_lead(db, organization=organization)
        lead.next_action = "Call back about the budget on Tuesday"
        profile = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        deal = Deal(
            organization_id=organization_id,
            customer_profile_id=profile.id,
            property_id=property_record.id,
            lead_id=lead.id,
            owner_user_id=user_id,
            stage=Deal.STAGE_NEW,
            expected_value=7500000,
            currency="INR",
            notes="Buyer wants a corner unit near the park",
        )
        db.add(deal)
        db.flush()
        commission = DealCommission(
            organization_id=organization_id,
            deal_id=deal.id,
            commission_type=DealCommission.TYPE_FIXED,
            fixed_amount=50000,
            currency="INR",
            status=DealCommission.STATUS_AGREED,
            terms="Agreed two percent on completion",
        )
        db.add(commission)
        follow_up = FollowUp(
            organization_id=organization_id,
            lead_id=lead.id,
            owner_user_id=user_id,
            follow_up_type=FollowUp.TYPE_CALL,
            title="Call the buyer",
            description="Discuss the parking allocation",
            due_at=datetime.now(UTC) + timedelta(days=1),
            status=FollowUp.STATUS_PENDING,
        )
        db.add(follow_up)
        activity = Activity(
            organization_id=organization_id,
            lead_id=lead.id,
            actor_id=user_id,
            activity_type="NOTE",
            title="Called about the flat",
            description="Wants a south-facing unit",
            details={"note": "private detail"},
            occurred_at=datetime.now(UTC),
        )
        db.add(activity)
        db.commit()
        return {
            "lead": lead.id,
            "profile": profile.id,
            "deal": deal.id,
            "commission": commission.id,
            "follow_up": follow_up.id,
            "activity": activity.id,
        }


# ---------------------------------------------------------------------------------------------------------------
# Export coverage and manifest
# ---------------------------------------------------------------------------------------------------------------


def test_export_includes_properties_with_identifier_links_and_consent_records(tenant, storage) -> None:
    organization_id, user_id = tenant
    with SessionLocal() as db:
        organization = db.get(Organization, organization_id)
        assert organization is not None
        owner = Contact(organization_id=organization_id, first_name="Owner", last_name="Known", is_active=True)
        db.add(owner)
        db.flush()
        property_record = create_property(db, organization=organization)
        property_record.owner_contact_id = owner.id
        db.add(
            ContactConsentRecord(
                organization_id=organization_id,
                contact_id=owner.id,
                channel="email",
                purpose="marketing",
                status="granted",
                policy_version=1,
                source="web_form",
                evidence_note="Ticked the newsletter box on the form",
                recorded_by_user_id=user_id,
            )
        )
        db.commit()
        property_id, owner_id = property_record.id, owner.id

    request_id = _request(organization_id, user_id, "export", ["crm.properties", "crm.contacts"])
    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status in {STATUS_READY, "ready_partial"}
    document = _archive_document(storage, row.artifact_reference)
    properties = document["categories"]["crm.properties"]
    assert [item["id"] for item in properties] == [str(property_id)]
    assert properties[0]["owner_contact_id"] == str(owner_id)
    consent = document["categories"]["crm.contacts/consent_records"]
    assert consent[0]["evidence_note"] == "Ticked the newsletter box on the form"
    assert consent[0]["channel"] == "email"


def test_manifest_discloses_sibvo_owned_data_and_unbuilt_producers(tenant, storage) -> None:
    organization_id, user_id = tenant
    _crm_fixture(organization_id, user_id)
    request_id = _request(organization_id, user_id, "export", ["crm.leads"])
    _run(request_id, organization_id)

    coverage = _archive_document(storage, _row(request_id).artifact_reference)["coverage"]
    owners = {item["category"]: item for item in coverage["sibvo_owned"]}
    assert "Subscriptions, plans and entitlements" in owners
    assert all(item["owner"] for item in coverage["sibvo_owned"])
    assert "SIBVO" in coverage["sibvo_privacy_route"]
    not_implemented = {item["category_key"] for item in coverage["not_implemented_categories"]}
    assert {"messaging.conversations", "voice.call_records", "voice.transcripts", "ai.prompts_and_responses"} <= not_implemented
    assert all(item["reason"] for item in coverage["not_implemented_categories"])


def test_export_never_contains_credentials_or_provider_secrets(tenant, storage) -> None:
    organization_id, user_id = tenant
    request_id = _request(organization_id, user_id, "export", ["crm.leads", "ai.usage"])
    _run(request_id, organization_id)

    document = _archive_document(storage, _row(request_id).artifact_reference)
    # The manifest explains which categories hold secrets. Only the exported categories are scanned.
    text = json.dumps(document["categories"]).lower()
    for forbidden in ("password_hash", "token_hash", "api_key", "encrypted_", "private_key", "secret_"):
        assert forbidden not in text


def test_export_reports_a_cross_organization_request_as_missing(tenant, storage) -> None:
    organization_id, user_id = tenant
    request_id = _request(organization_id, user_id, "export", ["crm.contacts"])
    _run(request_id, organization_id)
    other_organization = uuid4()
    # A request id from another tenant is never returned: the lookup is scoped by organization.
    with pytest.raises(privacy_execution.PrivacyRequestNotFoundError), SessionLocal() as db:
        privacy_execution.open_export(
            db,
            organization_id=other_organization,
            actor_user_id=user_id,
            request_id=request_id,
            storage=storage,
            now=datetime.now(UTC),
        )


# ---------------------------------------------------------------------------------------------------------------
# Execution is explicit and queued
# ---------------------------------------------------------------------------------------------------------------


def test_creating_an_export_queues_its_processing(tenant) -> None:
    organization_id, user_id = tenant
    with TestClient(_app_for(_actor(user_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        response = client.post(
            f"{BASE}/privacy/requests",
            json={"request_type": "export", "categories": ["crm.contacts"], "confirm": True},
        )
    assert response.status_code == 201
    request_id = response.json()["id"]
    with SessionLocal() as db:
        events = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.event_type == privacy_execution.PRIVACY_PROCESS_EVENT_TYPE,
                OutboxEvent.aggregate_id == request_id,
            )
        ).all()
    assert len(events) == 1


def test_a_recorded_deletion_queues_nothing_until_it_is_explicitly_executed(tenant, storage) -> None:
    organization_id, user_id = tenant
    ids = _crm_fixture(organization_id, user_id)
    request_id = _request(organization_id, user_id, "deletion", ["crm.leads"])
    assert _row(request_id).status == STATUS_ELIGIBILITY_RECORDED

    # Recording the request queues no processing, so no worker runs and no data changes.
    with SessionLocal() as db:
        queued = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.aggregate_id == str(request_id),
            )
        ).all()
    assert queued == []
    with SessionLocal() as db:
        lead = db.get(Lead, ids["lead"])
        assert lead is not None and lead.next_action is not None
    assert _row(request_id).status == STATUS_ELIGIBILITY_RECORDED

    _execute(request_id, organization_id, user_id)
    with SessionLocal() as db:
        queued = db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.organization_id == organization_id,
                OutboxEvent.aggregate_id == str(request_id),
            )
        ).all()
    assert len(queued) == 1


def test_execution_is_refused_once_the_deletion_has_run(tenant, storage) -> None:
    organization_id, user_id = tenant
    _crm_fixture(organization_id, user_id)
    request_id = _request(organization_id, user_id, "deletion", ["crm.leads"])
    _execute(request_id, organization_id, user_id)
    _run(request_id, organization_id)
    with pytest.raises(InvalidRequestStateError):
        _execute(request_id, organization_id, user_id)


def test_execute_endpoint_requires_confirmation_and_the_manage_permission(tenant, storage) -> None:
    organization_id, user_id = tenant
    _crm_fixture(organization_id, user_id)
    request_id = _request(organization_id, user_id, "deletion", ["crm.leads"])
    with TestClient(_app_for(_actor(user_id))) as client:
        client.headers.update({"X-Organization-ID": str(organization_id)})
        refused = client.post(f"{BASE}/privacy/requests/{request_id}/execute", json={"confirm": False})
        accepted = client.post(f"{BASE}/privacy/requests/{request_id}/execute", json={"confirm": True})
        missing = client.post(
            f"{BASE}/privacy/requests/{uuid4()}/execute", json={"confirm": True}
        )
    assert refused.status_code == 422
    assert accepted.status_code == 202
    assert missing.status_code == 404


# ---------------------------------------------------------------------------------------------------------------
# CRM free-text deletion and anonymization
# ---------------------------------------------------------------------------------------------------------------


def test_crm_free_text_is_cleared_and_the_structure_is_kept(tenant, storage) -> None:
    organization_id, user_id = tenant
    ids = _crm_fixture(organization_id, user_id)
    request_id = _request(
        organization_id,
        user_id,
        "deletion",
        ["crm.leads", "crm.follow_ups", "crm.customer_profiles", "crm.deals"],
    )
    _execute(request_id, organization_id, user_id)
    _run(request_id, organization_id)

    row = _row(request_id)
    assert row.status == STATUS_PARTIALLY_COMPLETED
    execution = json.loads(row.execution)
    assert execution["crm.leads"]["outcome"] == "anonymized_partial"
    assert execution["crm.deals"]["outcome"] == "anonymized_partial"
    assert "payment_milestones.notes" in execution["crm.deals"]["not_changed"]

    with SessionLocal() as db:
        lead = db.get(Lead, ids["lead"])
        profile = db.get(CustomerProfile, ids["profile"])
        deal = db.get(Deal, ids["deal"])
        follow_up = db.get(FollowUp, ids["follow_up"])
        activity = db.get(Activity, ids["activity"])
        commission = db.get(DealCommission, ids["commission"])
        assert lead is not None and lead.next_action is None
        assert profile is not None and profile.customer_notes is None
        assert deal is not None and deal.notes is None and deal.expected_value == 7500000
        assert follow_up is not None and follow_up.description is None
        assert follow_up.title == REDACTED_NAME
        assert activity is not None and activity.description is None and activity.details is None
        assert activity.title == REDACTED_NAME
        # Financial and contractual fields are kept.
        assert commission is not None and commission.terms == "Agreed two percent on completion"


def test_a_deletion_writes_counts_and_outcomes_but_no_personal_text(tenant, storage) -> None:
    organization_id, user_id = tenant
    _crm_fixture(organization_id, user_id)
    request_id = _request(organization_id, user_id, "deletion", ["crm.leads", "crm.follow_ups"])
    _execute(request_id, organization_id, user_id)
    _run(request_id, organization_id)

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action.like("privacy.deletion.%"),
            )
        ).all()
    assert events, "the deletion must be audited"
    serialized = json.dumps([event.event_metadata for event in events])
    for personal in ("Call back about the budget", "Discuss the parking", "private detail", "Wants a south-facing"):
        assert personal not in serialized


def test_a_legal_hold_placed_after_the_request_blocks_the_execution(tenant, storage) -> None:
    organization_id, user_id = tenant
    ids = _crm_fixture(organization_id, user_id)
    request_id = _request(organization_id, user_id, "deletion", ["crm.leads"])
    with SessionLocal() as db:
        place_legal_hold(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            category_key="crm.leads",
            reason="Dispute pending with the buyer",
        )
        db.commit()
    _execute(request_id, organization_id, user_id)
    _run(request_id, organization_id)

    execution = _execution(request_id)
    assert execution["crm.leads"]["outcome"] == "skipped"
    assert "legal_hold_active" in execution["crm.leads"]["reasons"]
    with SessionLocal() as db:
        lead = db.get(Lead, ids["lead"])
        assert lead is not None and lead.next_action == "Call back about the budget on Tuesday"


def test_a_failed_object_removal_rolls_the_document_row_back(tenant, storage, monkeypatch) -> None:
    organization_id, user_id = tenant
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

    def refuse(_key: str) -> None:
        raise StorageError("object store unavailable")

    monkeypatch.setattr(storage, "delete", refuse)
    request_id = _request(organization_id, user_id, "deletion", ["documents.files"])
    _execute(request_id, organization_id, user_id)
    with pytest.raises(StorageError):
        _run(request_id, organization_id)

    # The row and the object both survive, so the request can be retried without an orphan.
    with SessionLocal() as db:
        assert db.get(Document, document_id) is not None
    assert storage.exists(key)
    assert _row(request_id).status == STATUS_ELIGIBILITY_RECORDED


def test_contact_anonymization_clears_the_consent_evidence_note(tenant, storage) -> None:
    organization_id, user_id = tenant
    with SessionLocal() as db:
        contact = Contact(organization_id=organization_id, first_name="Asha", last_name="Rao", email="a@example.test", is_active=True)
        db.add(contact)
        db.flush()
        db.add(
            ContactConsentRecord(
                organization_id=organization_id,
                contact_id=contact.id,
                channel="email",
                purpose="marketing",
                status="granted",
                policy_version=1,
                source="web_form",
                evidence_note="Said yes on the phone",
                recorded_by_user_id=user_id,
            )
        )
        db.commit()
        contact_id = contact.id

    request_id = _request(organization_id, user_id, "deletion", ["crm.contacts"])
    _execute(request_id, organization_id, user_id)
    _run(request_id, organization_id)

    with SessionLocal() as db:
        contact = db.get(Contact, contact_id)
        consent = db.scalar(select(ContactConsentRecord).where(ContactConsentRecord.contact_id == contact_id))
        assert contact is not None and contact.first_name == REDACTED_NAME
        assert consent is not None and consent.evidence_note is None
        assert consent.status == "granted"


# ---------------------------------------------------------------------------------------------------------------
# Import attachments
# ---------------------------------------------------------------------------------------------------------------


def _import_batch(organization_id: UUID, upload_root: Path, body: bytes) -> tuple[UUID, str]:
    batch_id = uuid4()
    key = f"{organization_id}/{batch_id.hex}/contacts.csv"
    path = upload_root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    with SessionLocal() as db:
        db.add(
            ImportBatch(
                id=batch_id,
                organization_id=organization_id,
                source_filename="contacts.csv",
                source_format="csv",
                content_type="text/csv",
                file_size_bytes=len(body),
                status="completed",
                storage_backend="local",
                storage_key=key,
            )
        )
        db.commit()
    return batch_id, key


def test_import_attachment_is_exported_as_a_document_file(tenant, storage, upload_root) -> None:
    organization_id, user_id = tenant
    batch_id, _key = _import_batch(organization_id, upload_root, b"name,phone\nAsha,+911234567890\n")
    request_id = _request(organization_id, user_id, "export", ["documents.files"])
    _run(request_id, organization_id)

    row = _row(request_id)
    document = _archive_document(storage, row.artifact_reference)
    attachments = [item for item in document["categories"]["documents.files"] if item["kind"] == "import_attachment"]
    assert [item["id"] for item in attachments] == [str(batch_id)]
    members = _archive_members(storage, row.artifact_reference)
    assert members[attachments[0]["archive_path"]] == b"name,phone\nAsha,+911234567890\n"


def test_import_attachment_deletion_removes_the_file_and_keeps_the_batch_row(tenant, storage, upload_root) -> None:
    organization_id, user_id = tenant
    batch_id, key = _import_batch(organization_id, upload_root, b"name\nAsha\n")
    request_id = _request(organization_id, user_id, "deletion", ["documents.files"])
    _execute(request_id, organization_id, user_id)
    _run(request_id, organization_id)

    assert not (upload_root / key).exists()
    with SessionLocal() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None and batch.storage_key is None
        assert batch.source_filename == REDACTED_NAME
    execution = _execution(request_id)
    assert execution["documents.files"]["outcome"] == "deleted_partial"
    assert _row(request_id).status == STATUS_PARTIALLY_COMPLETED


def test_an_import_attachment_outside_the_upload_root_is_never_read(tenant, storage, upload_root) -> None:
    organization_id, user_id = tenant
    batch_id = uuid4()
    with SessionLocal() as db:
        db.add(
            ImportBatch(
                id=batch_id,
                organization_id=organization_id,
                source_filename="escape.csv",
                source_format="csv",
                content_type="text/csv",
                file_size_bytes=4,
                status="completed",
                storage_backend="local",
                storage_key="../../outside.csv",
            )
        )
        db.commit()
    request_id = _request(organization_id, user_id, "export", ["documents.files"])
    _run(request_id, organization_id)

    row = _row(request_id)
    # Only the documents category was requested, and it cannot be exported completely, so nothing is produced.
    assert row.status == STATUS_BLOCKED
    assert json.loads(row.execution)["not_exported"][0]["reason"] == "stored_object_missing"


# ---------------------------------------------------------------------------------------------------------------
# Retention audit
# ---------------------------------------------------------------------------------------------------------------


def test_a_retention_run_records_the_policy_version_it_applied(tenant, storage) -> None:
    organization_id, user_id = tenant
    with SessionLocal() as db:
        set_retention_policy(
            db, organization_id=organization_id, actor_user_id=user_id, category_key="documents.files", retention_days=365
        )
        db.commit()
    with SessionLocal() as db:
        enforce_retention(db, organization_id=organization_id, storage=storage, now=datetime.now(UTC))
        db.commit()
    with SessionLocal() as db:
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == "privacy.retention.enforced",
            )
        )
    assert event is not None
    assert json.loads(event.event_metadata)["policy_version"] == 1


# ---------------------------------------------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------------------------------------------


def test_outbox_failure_text_redacts_personal_values() -> None:
    assert _describe_error(ValueError("owner a.person@example.test is invalid")) == "ValueError: owner [email] is invalid"
    assert "a.person" not in _describe_error(KeyError("a.person@example.test"))


def test_a_failed_retention_organization_logs_the_exception_type_only(tenant, storage, monkeypatch, caplog) -> None:
    organization_id, user_id = tenant
    with SessionLocal() as db:
        set_retention_policy(
            db, organization_id=organization_id, actor_user_id=user_id, category_key="documents.files", retention_days=30
        )
        db.commit()

    def fail(*_args, **_kwargs):
        raise ValueError("record for a.person@example.test could not be read")

    monkeypatch.setattr(privacy_maintenance, "enforce_retention", fail)
    with caplog.at_level(logging.ERROR):
        report = privacy_maintenance.run_retention(
            session_factory=SessionLocal, now=datetime.now(UTC), storage=storage
        )
    assert report["failed"] >= 1
    logged = " ".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert "ValueError" in logged
    assert "a.person@example.test" not in logged


def test_site_visits_referrals_notifications_and_contact_restrictions_are_exported(tenant, storage) -> None:
    from app.db.models.notification import Notification
    from app.db.models.notification_preference import NotificationPreference
    from app.db.models.referral import Referral
    from app.db.models.site_visit import SiteVisit
    from app.db.models.team_member_removal import TeamMemberRemoval

    organization_id, user_id = tenant
    with SessionLocal() as db:
        organization = db.get(Organization, organization_id)
        assert organization is not None
        property_record = create_property(db, organization=organization)
        contact = Contact(organization_id=organization_id, first_name="Referee", last_name="Person", is_active=True)
        db.add(contact)
        db.flush()
        lead = create_lead(db, organization=organization)
        db.add(
            SiteVisit(
                organization_id=organization_id,
                property_id=property_record.id,
                lead_id=lead.id,
                owner_user_id=user_id,
                scheduled_at=datetime.now(UTC) + timedelta(days=2),
                status=SiteVisit.STATUS_SCHEDULED,
                notes="Bring the floor plan",
                feedback="Liked the balcony",
            )
        )
        db.add(
            Referral(
                organization_id=organization_id,
                referrer_contact_id=contact.id,
                referral_name="Meera Shah",
                referral_phone="+919876500000",
                referral_email="meera@example.test",
                status="NEW",
                notes="Referred by a neighbour",
            )
        )
        db.add(
            Notification(
                organization_id=organization_id,
                recipient_user_id=user_id,
                event_type="follow_up_due",
                title="Follow-up due",
                message="Call Asha Rao today",
            )
        )
        db.add(
            NotificationPreference(
                organization_id=organization_id,
                user_id=user_id,
                enabled=True,
                follow_ups_enabled=True,
                deals_enabled=True,
                site_visits_enabled=True,
                leads_enabled=True,
                automation_enabled=False,
            )
        )
        db.add(ContactDoNotDisturb(organization_id=organization_id, contact_id=contact.id, set_by_user_id=user_id))
        db.add(
            TeamMemberRemoval(
                organization_id=organization_id,
                membership_id=uuid4(),
                target_user_id=user_id,
                actor_user_id=user_id,
                reason="Left the team",
                seat_outcome="released",
            )
        )
        db.commit()

    request_id = _request(
        organization_id,
        user_id,
        "export",
        ["crm.site_visits", "crm.referrals", "messaging.notifications", "crm.contacts", "team.invitations"],
    )
    _run(request_id, organization_id)

    row = _row(request_id)
    document = _archive_document(storage, row.artifact_reference)
    assert document["categories"]["crm.site_visits"][0]["feedback"] == "Liked the balcony"
    assert document["categories"]["crm.referrals"][0]["referral_email"] == "meera@example.test"
    assert document["categories"]["messaging.notifications"][0]["message"] == "Call Asha Rao today"
    assert document["categories"]["messaging.notifications/preferences"][0]["follow_ups_enabled"] is True
    assert document["categories"]["crm.contacts/do_not_disturb"][0]["contact_id"]
    assert document["categories"]["team.invitations/membership_removals"][0]["reason"] == "Left the team"

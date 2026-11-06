"""DFR1-050 final decisions: import batch minimisation, intake fingerprint replacement, derived digests, requirement
history, manifest limitations, and authorization of the explicit deletion step.

All rows and files go to the isolated test database and to temporary directories.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import get_settings
from app.db.models.agent import AgentExecution
from app.db.models.audit_event import AuditEvent
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_history import CustomerRequirementHistory
from app.db.models.customer_requirement_location import CustomerRequirementLocation
from app.db.models.customer_requirement_possession_parking_preference import (
    CustomerRequirementPossessionParkingPreference,
)
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.import_batch import ImportBatch
from app.db.models.lead_intake import LeadIntakeSubmission
from app.db.models.lead_priority import LeadPriorityScore
from app.db.models.organization import Organization
from app.db.session import SessionLocal
from app.governance import privacy_execution
from app.governance.privacy import place_legal_hold
from app.governance.privacy_derived import (
    PRIVACY_LIMITATIONS,
    RETAINED_PERSONAL_DATA_HISTORY,
)
from app.imports import storage as imports_storage
from app.storage import LocalObjectStorage
from tests.agents_support import create_user_in
from tests.test_deals_api import create_lead
from tests.test_governance_api import _app_for
from tests.test_privacy_derived import (
    _actor,
    _agent_run,
    _derived_cleanup,
    _document_of,
    _execute,
    _request,
    _row,
    _run,
)

BASE = "/api/v1/governance"
ORIGINAL_DIGEST = "d" * 64  # stands in for a real submission digest in the tests below


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalObjectStorage:
    store = LocalObjectStorage(tmp_path / "objects")
    monkeypatch.setattr(privacy_execution, "get_object_storage", lambda: store)
    return store


@pytest.fixture
def upload_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
def org(world) -> Iterator[SimpleNamespace]:
    yield world
    with SessionLocal() as db:
        # Requirement rows reference leads, so they are removed before the lead cleanup in _derived_cleanup.
        for model in (
            CustomerRequirementHistory,
            CustomerRequirementLocation,
            CustomerRequirementPropertyPreference,
            CustomerRequirementPossessionParkingPreference,
            CustomerRequirement,
            ImportBatch,
            LeadIntakeSubmission,
        ):
            db.execute(delete(model).where(model.organization_id.in_([world.org.id, world.other_org.id])))
        db.commit()
    _derived_cleanup((world.org.id, world.other_org.id))


def _batch(organization_id: UUID, key: str | None, *, source: str, error: str | None, body: bytes | None,
           upload_root: Path) -> UUID:
    batch_id = uuid4()
    if key is not None and body is not None:
        path = upload_root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    with SessionLocal() as db:
        db.add(
            ImportBatch(
                id=batch_id,
                organization_id=organization_id,
                source_filename=source,
                source_format="csv",
                content_type="text/csv",
                file_size_bytes=len(body) if body is not None else None,
                status="completed_with_errors" if error else "completed",
                total_rows=3,
                processed_rows=3,
                successful_rows=2,
                failed_rows=1,
                skipped_rows=0,
                error_summary=error,
                storage_backend="local" if key else None,
                storage_key=key,
            )
        )
        db.commit()
    return batch_id


def _delete_category(org, category: str) -> UUID:
    request_id = _request(org.org.id, org.owner.id, "deletion", [category])
    _execute(request_id, org.org.id, org.owner.id)
    _run(request_id, org.org.id)
    return request_id


# ---------------------------------------------------------------------------------------------------------------
# 3. Import batches
# ---------------------------------------------------------------------------------------------------------------


def test_import_batch_deletion_clears_names_and_error_text_and_keeps_only_the_technical_record(org, upload_root, storage) -> None:
    key = f"{org.org.id}/{uuid4().hex}/contacts.csv"
    batch_id = _batch(
        org.org.id, key, source="Asha Rao family contacts.csv",
        error="Row 2: Asha Rao +919876543210 has an invalid email", body=b"name,phone\nAsha,+919876543210\n",
        upload_root=upload_root,
    )
    request_id = _delete_category(org, "documents.files")

    assert not (upload_root / key).exists()
    with SessionLocal() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None
        assert batch.source_filename == "Redacted"
        assert batch.error_summary is None
        assert batch.storage_key is None and batch.storage_backend is None
        # The minimum technical record that remains.
        assert batch.organization_id == org.org.id
        assert batch.source_format == "csv"
        assert batch.status == "completed_with_errors"
        assert (batch.total_rows, batch.processed_rows, batch.successful_rows, batch.failed_rows) == (3, 3, 2, 1)
        assert batch.created_at is not None
    execution = json.loads(_row(request_id).execution)["documents.files"]
    assert execution["outcome"] == "deleted_partial"


def test_a_batch_whose_file_was_already_removed_still_loses_its_name_and_error_text(org, upload_root, storage) -> None:
    batch_id = _batch(org.org.id, None, source="Meera Shah list.csv", error="Phone +91 98765 43210 invalid",
                      body=None, upload_root=upload_root)
    _delete_category(org, "documents.files")
    with SessionLocal() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch is not None and batch.source_filename == "Redacted" and batch.error_summary is None


def test_import_batches_of_another_organization_are_not_touched(org, upload_root, storage) -> None:
    other_batch = _batch(org.other_org.id, None, source="Other tenant names.csv", error=None, body=None,
                         upload_root=upload_root)
    _delete_category(org, "documents.files")
    with SessionLocal() as db:
        batch = db.get(ImportBatch, other_batch)
        assert batch is not None and batch.source_filename == "Other tenant names.csv"


# ---------------------------------------------------------------------------------------------------------------
# 5. Lead intake fingerprint and derived digests
# ---------------------------------------------------------------------------------------------------------------


def _intake(org, *, payload: dict, digest: str) -> UUID:
    with SessionLocal() as db:
        row = LeadIntakeSubmission(
            organization_id=org.org.id,
            source_channel="form",
            external_reference=f"asha-{uuid4().hex[:8]}@example.test",
            payload_hash=digest,
            raw_payload=payload,
            normalized_payload={"name": "Asha Rao"},
            validation_problems=[],
            status=LeadIntakeSubmission.STATUS_RECEIVED,
            candidate_contact_ids=[],
            submitted_by_user_id=org.owner.id,
            decision="accepted",
            decision_reason="Matched by phone",
        )
        db.add(row)
        db.commit()
        return row.id


def test_lead_intake_deletion_replaces_the_digest_and_the_reference_and_keeps_the_decision(org, storage) -> None:
    intake_id = _intake(org, payload={"name": "Asha Rao", "phone": "+919876543210"}, digest=ORIGINAL_DIGEST)
    _delete_category(org, "crm.lead_intake")

    with SessionLocal() as db:
        row = db.get(LeadIntakeSubmission, intake_id)
        assert row is not None
        assert row.raw_payload == {} and row.normalized_payload is None
        assert row.payload_hash != ORIGINAL_DIGEST and len(row.payload_hash) == 64
        assert row.payload_hash == hashlib.sha256(f"redacted:lead_intake_submissions:{intake_id}:payload_hash".encode()).hexdigest()
        assert "@example.test" not in row.external_reference and row.external_reference == f"redacted-{intake_id}"
        # The decision and the links that make the record auditable stay.
        assert row.decision == "accepted" and row.status == LeadIntakeSubmission.STATUS_RECEIVED
        assert row.decision_reason is None  # personal text, cleared
        assert row.submitted_by_user_id == org.owner.id


def test_no_stored_row_keeps_the_original_digest_after_deletion(org, storage) -> None:
    _intake(org, payload={"name": "Asha Rao"}, digest=ORIGINAL_DIGEST)
    _delete_category(org, "crm.lead_intake")
    with SessionLocal() as db:
        found = db.scalars(select(LeadIntakeSubmission.id).where(LeadIntakeSubmission.payload_hash == ORIGINAL_DIGEST)).all()
    assert found == []


def test_agent_run_and_lead_score_digests_are_replaced_on_clearing(org, storage) -> None:
    execution_id = _agent_run(org)
    with SessionLocal() as db:
        original = db.get(AgentExecution, execution_id).input_hash
        lead = create_lead(db, organization=db.get(Organization, org.org.id))
        score = LeadPriorityScore(
            organization_id=org.org.id, lead_id=lead.id, ruleset_version="v1", score=40, band="low",
            method="rule_based_baseline", confidence="low", insufficient_data=True, factors=[],
            missing_factors=["budget"], requirement_summary=[], input_hash=ORIGINAL_DIGEST,
            computed_at=_now(), computed_by_user_id=org.owner.id,
        )
        db.add(score)
        db.commit()
        score_id = score.id
    _delete_category(org, "ai.execution_traces")
    _delete_category(org, "crm.lead_intelligence")

    with SessionLocal() as db:
        run = db.get(AgentExecution, execution_id)
        assert run is not None and run.input_hash != original
        assert run.input_hash == hashlib.sha256(f"redacted:agent_executions:{execution_id}:input_hash".encode()).hexdigest()
        stored = db.get(LeadPriorityScore, score_id)
        assert stored is not None and stored.input_hash != ORIGINAL_DIGEST and stored.score == 40


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


# ---------------------------------------------------------------------------------------------------------------
# 4. Requirement history and requirement tables
# ---------------------------------------------------------------------------------------------------------------

# Every string column on the requirement tables, reviewed against the models. Each one is a code, a reference, or a
# place name that the requirement itself depends on. None is free text about a person.
REVIEWED_REQUIREMENT_STRING_COLUMNS = {
    "customer_requirements": {"status", "budget_currency", "transaction_type"},
    "customer_requirement_locations": {"city", "locality"},
    "customer_requirement_property_preferences": {"property_type"},
    "customer_requirement_possession_parking_preferences": {"possession_preference", "parking_preference"},
    "customer_requirement_history": {"change_type"},
}


def test_requirement_string_columns_are_the_reviewed_codes_and_places_only() -> None:
    from sqlalchemy import String

    import app.db.models  # noqa: F401
    from app.db.base import Base

    for table_name, reviewed in REVIEWED_REQUIREMENT_STRING_COLUMNS.items():
        table = Base.metadata.tables[table_name]
        string_columns = {column.name for column in table.columns if isinstance(column.type, String)}
        assert string_columns <= reviewed | {"organization_id"}, (table_name, string_columns - reviewed)


def _requirement_fixture(org_id: UUID, lead_id: UUID, owner_id: UUID) -> dict:
    """A requirement with every customer-linked value filled in, plus its history snapshot."""
    from app.db.models.customer_requirement_possession_parking_preference import (
        CustomerRequirementPossessionParkingPreference,
    )
    from app.db.models.customer_requirement_property_preference import (
        CustomerRequirementPropertyPreference,
    )

    with SessionLocal() as db:
        requirement = CustomerRequirement(
            organization_id=org_id, lead_id=lead_id, status="ACTIVE", is_active=True,
            budget_min=5000000, budget_max=8000000, budget_currency="INR", transaction_type="SALE",
        )
        db.add(requirement)
        db.flush()
        db.add(CustomerRequirementLocation(organization_id=org_id, customer_requirement_id=requirement.id,
                                           city="Bengaluru", locality="Whitefield", is_active=True))
        preference = CustomerRequirementPropertyPreference(
            organization_id=org_id, customer_requirement_id=requirement.id, property_type="APARTMENT",
            bhk_min=2, bhk_max=3, is_active=True,
        )
        parking = CustomerRequirementPossessionParkingPreference(
            organization_id=org_id, customer_requirement_id=requirement.id, possession_preference="READY",
            parking_preference="COVERED", parking_spaces_min=2, is_active=True,
        )
        db.add_all([preference, parking])
        db.add(CustomerRequirementHistory(
            organization_id=org_id, customer_requirement_id=requirement.id, version=1, actor_id=owner_id,
            change_type="created",
            snapshot={
                "requirement": {"status": "ACTIVE", "budget_min": "5000000.00", "budget_max": "8000000.00",
                                "budget_currency": "INR", "lead_id": str(lead_id)},
                "locations": [{"city": "Bengaluru", "locality": "Whitefield", "is_active": True}],
                "property_preferences": [{"property_type": "APARTMENT", "bhk_min": 2, "bhk_max": 3}],
                "possession_parking_preference": {"possession_preference": "READY",
                                                  "parking_preference": "COVERED", "parking_spaces_min": 2},
            },
        ))
        db.commit()
        return {"requirement": requirement.id, "preference": preference.id, "parking": parking.id}


def test_customer_linked_values_are_removed_from_current_records_and_kept_structure(org, storage) -> None:
    from app.db.models.customer_requirement_possession_parking_preference import (
        CustomerRequirementPossessionParkingPreference,
    )
    from app.db.models.customer_requirement_property_preference import (
        CustomerRequirementPropertyPreference,
    )

    with SessionLocal() as db:
        lead = create_lead(db, organization=db.get(Organization, org.org.id))
        lead_id = lead.id
        db.commit()
    ids = _requirement_fixture(org.org.id, lead_id, org.owner.id)

    request_id = _delete_category(org, "crm.requirements")
    execution = json.loads(_row(request_id).execution)["crm.requirements"]
    assert execution["outcome"] == "anonymized_partial"
    assert "retained" not in execution["removed"][0]  # removed entries are the removed values
    assert all(item.startswith("retained:") for item in execution["not_changed"])
    assert all(item.startswith("removed:") for item in execution["removed"])

    with SessionLocal() as db:
        requirement = db.get(CustomerRequirement, ids["requirement"])
        assert requirement is not None
        assert requirement.budget_min is None and requirement.budget_max is None
        assert requirement.budget_currency is None and requirement.transaction_type is None
        # Workflow state and referential links stay.
        assert requirement.status == "ACTIVE" and requirement.is_active is True
        assert requirement.lead_id == lead_id
        location = db.scalar(select(CustomerRequirementLocation).where(
            CustomerRequirementLocation.customer_requirement_id == ids["requirement"]))
        assert location is not None and location.city == "Redacted" and location.locality == "Redacted"
        preference = db.get(CustomerRequirementPropertyPreference, ids["preference"])
        assert preference is not None and preference.property_type == "Redacted"
        assert preference.bhk_min is None and preference.bhk_max is None and preference.is_active is True
        parking = db.get(CustomerRequirementPossessionParkingPreference, ids["parking"])
        assert parking is not None and parking.possession_preference == "Redacted"
        assert parking.parking_preference == "Redacted" and parking.parking_spaces_min is None


def test_customer_linked_values_are_removed_from_history_snapshots_and_history_structure_is_kept(org, storage) -> None:
    with SessionLocal() as db:
        lead = create_lead(db, organization=db.get(Organization, org.org.id))
        lead_id = lead.id
        db.commit()
    ids = _requirement_fixture(org.org.id, lead_id, org.owner.id)
    with SessionLocal() as db:
        history = db.scalar(select(CustomerRequirementHistory).where(
            CustomerRequirementHistory.customer_requirement_id == ids["requirement"]))
        history_id, occurred_at = history.id, history.occurred_at

    _delete_category(org, "crm.requirements")

    with SessionLocal() as db:
        history = db.get(CustomerRequirementHistory, history_id)
        assert history is not None
        assert history.version == 1 and history.change_type == "created" and history.occurred_at == occurred_at
        snapshot = history.snapshot
        assert snapshot["requirement"]["budget_min"] is None and snapshot["requirement"]["budget_max"] is None
        assert snapshot["requirement"]["budget_currency"] is None
        assert snapshot["requirement"]["status"] == "ACTIVE"  # workflow status kept
        assert snapshot["requirement"]["lead_id"] == str(lead_id)  # link kept
        assert snapshot["locations"] == [{"city": "Redacted", "locality": "Redacted", "is_active": True}]
        assert snapshot["property_preferences"] == [{"property_type": "Redacted", "bhk_min": None, "bhk_max": None}]
        assert snapshot["possession_parking_preference"] == {
            "possession_preference": "Redacted", "parking_preference": "Redacted", "parking_spaces_min": None,
        }


def test_a_legal_hold_placed_after_the_request_keeps_every_customer_linked_value(org, storage) -> None:
    with SessionLocal() as db:
        lead = create_lead(db, organization=db.get(Organization, org.org.id))
        lead_id = lead.id
        db.commit()
    ids = _requirement_fixture(org.org.id, lead_id, org.owner.id)
    request_id = _request(org.org.id, org.owner.id, "deletion", ["crm.requirements"])
    with SessionLocal() as db:
        place_legal_hold(db, organization_id=org.org.id, actor_user_id=org.owner.id,
                         category_key="crm.requirements", reason="Commercial dispute open")
        db.commit()
    _execute(request_id, org.org.id, org.owner.id)
    _run(request_id, org.org.id)

    assert json.loads(_row(request_id).execution)["crm.requirements"]["outcome"] == "skipped"
    with SessionLocal() as db:
        requirement = db.get(CustomerRequirement, ids["requirement"])
        assert requirement is not None and requirement.budget_min == 5000000 and requirement.transaction_type == "SALE"


def test_post_deletion_verification_detects_a_surviving_customer_value(org, storage) -> None:
    with SessionLocal() as db:
        lead = create_lead(db, organization=db.get(Organization, org.org.id))
        lead_id = lead.id
        db.commit()
    ids = _requirement_fixture(org.org.id, lead_id, org.owner.id)
    _delete_category(org, "crm.requirements")

    with SessionLocal() as db:
        assert privacy_execution._requirement_personal_values_remaining(db, org.org.id) is False
        requirement = db.get(CustomerRequirement, ids["requirement"])
        requirement.budget_max = 9000000  # a value written back after deletion
        db.flush()
        assert privacy_execution._requirement_personal_values_remaining(db, org.org.id) is True
        db.rollback()


def test_requirement_values_of_another_organization_are_untouched(org, storage) -> None:
    with SessionLocal() as db:
        other_lead = create_lead(db, organization=db.get(Organization, org.other_org.id))
        other_lead_id = other_lead.id
        db.commit()
    other = _requirement_fixture(org.other_org.id, other_lead_id, org.other.id)
    _delete_category(org, "crm.requirements")
    with SessionLocal() as db:
        requirement = db.get(CustomerRequirement, other["requirement"])
        assert requirement is not None and requirement.budget_min == 5000000


# ---------------------------------------------------------------------------------------------------------------
# 1, 2, 6. Manifest, retained history, unsupported producers, authorization
# ---------------------------------------------------------------------------------------------------------------


def test_manifest_states_the_human_task_limitation_and_the_unsupported_producers(org, storage) -> None:
    export_id = _request(org.org.id, org.owner.id, "export", ["crm.leads"])
    _run(export_id, org.org.id)
    coverage = _document_of(export_id, storage)["coverage"]

    retained = {item["table"]: item for item in coverage["retained_personal_data_history"]}
    assert "human_task_events" in retained
    assert "separately approved security design" in retained["human_task_events"]["limitation"]
    topics = {item["topic"] for item in coverage["limitations"]}
    assert {"Messages and conversations", "Calls, voice recordings and transcripts", "AI chat prompts and responses"} <= topics
    not_implemented = {item["category_key"] for item in coverage["not_implemented_categories"]}
    assert {"messaging.conversations", "voice.call_records", "voice.transcripts", "ai.prompts_and_responses"} <= not_implemented


def test_limitations_and_retained_history_are_static_and_non_empty() -> None:
    assert RETAINED_PERSONAL_DATA_HISTORY and PRIVACY_LIMITATIONS
    assert all(item["statement"] for item in PRIVACY_LIMITATIONS)


def test_execute_is_refused_for_a_user_without_the_manage_permission(org, storage) -> None:
    request_id = _request(org.org.id, org.owner.id, "deletion", ["crm.leads"])
    reader = create_user_in(org.org, permissions=("governance.privacy.read",))
    with TestClient(_app_for(_actor(reader.id))) as client:
        client.headers.update({"X-Organization-ID": str(org.org.id)})
        response = client.post(f"{BASE}/privacy/requests/{request_id}/execute", json={"confirm": True})
    assert response.status_code == 403
    assert _row(request_id).status == "eligibility_recorded"


def test_execution_request_is_audited_with_the_acting_member(org, storage) -> None:
    request_id = _request(org.org.id, org.owner.id, "deletion", ["crm.leads"])
    _execute(request_id, org.org.id, org.owner.id)
    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).where(
            AuditEvent.organization_id == org.org.id,
            AuditEvent.action == "privacy.deletion.execution_requested",
        ))
    assert event is not None and str(event.user_id) == str(org.owner.id)

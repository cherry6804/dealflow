"""DFR1-050: export and clearing for derived and operational records, and manifest completeness.

Covers the categories added in privacy_derived: agent runs, lead intake and qualification, lead priority,
next-best-action recommendations, human tasks, automation runs, document reviews and knowledge chunks. Each one is
exported without secrets or internal configuration, cleared on deletion while its structure is kept, and protected
by legal holds. Tenant isolation and manifest completeness are checked as well.

All rows go to the isolated test database. Stored objects go to temporary directories.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.agents.runtime import create_execution
from app.auth.dependencies import CurrentUserContext
from app.db.models.activity import Activity
from app.db.models.agent import AgentExecution
from app.db.models.audit_event import AuditEvent
from app.db.models.document import Document
from app.db.models.document_review import DocumentReview
from app.db.models.human_task import HumanTask, HumanTaskEvent
from app.db.models.knowledge_chunk import KnowledgeChunk
from app.db.models.lead import Lead
from app.db.models.lead_intake import LeadIntakeSubmission
from app.db.models.lead_priority import LeadPriorityCorrection, LeadPriorityScore
from app.db.models.organization import Organization
from app.db.models.outbox_event import OutboxEvent
from app.db.models.privacy_records import LegalHold, PrivacyDataRequest, RetentionPolicy
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance import privacy_execution
from app.governance.data_classification import CATEGORIES
from app.governance.privacy import (
    STATUS_ELIGIBILITY_RECORDED,
    create_privacy_request,
    place_legal_hold,
)
from app.governance.privacy_derived import CLEARING_RULES, DERIVED_EXPORTERS
from app.governance.privacy_execution import (
    EXPORTERS,
    SUB_RECORD_EXPORTERS,
    process_privacy_request,
    request_deletion_execution,
)
from app.governance.table_inventory import DISPOSITION_EXPORTED, TABLE_INVENTORY
from app.storage import LocalObjectStorage
from tests.agents_support import config, create_draft, publish
from tests.test_deals_api import create_lead
from tests.test_governance_api import _app_for

BASE = "/api/v1/governance"
INSTRUCTIONS = "Be concise and factual."


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalObjectStorage:
    store = LocalObjectStorage(tmp_path / "objects")
    monkeypatch.setattr(privacy_execution, "get_object_storage", lambda: store)
    return store


def _derived_cleanup(organization_ids: tuple[UUID, ...]) -> None:
    with SessionLocal() as db:
        for organization_id in organization_ids:
            # Human task events are append-only, so a task that has any event cannot be removed. Those tasks stay
            # as residue in the disposable database; every test uses its own organization, so they do not interfere.
            db.execute(
                delete(HumanTask).where(
                    HumanTask.organization_id == organization_id,
                    HumanTask.id.not_in(select(HumanTaskEvent.task_id)),
                )
            )
            for model in (
                KnowledgeChunk,
                DocumentReview,
                LeadPriorityCorrection,
                LeadPriorityScore,
                LeadIntakeSubmission,
                Activity,
                Lead,
                PrivacyDataRequest,
                LegalHold,
                RetentionPolicy,
                OutboxEvent,
                AuditEvent,
            ):
                db.execute(delete(model).where(model.organization_id == organization_id))
        db.commit()


@pytest.fixture
def derived(world) -> Iterator[SimpleNamespace]:
    yield world
    _derived_cleanup((world.org.id, world.other_org.id))


def _request(organization_id: UUID, user_id: UUID, request_type: str, categories: list[str]) -> UUID:
    with SessionLocal() as db:
        row = create_privacy_request(
            db, organization_id=organization_id, actor_user_id=user_id,
            request_type=request_type, category_keys=categories,
        )
        db.commit()
        return row.id


def _run(request_id: UUID, organization_id: UUID) -> None:
    event = SimpleNamespace(payload={"request_id": str(request_id)}, organization_id=organization_id)
    with SessionLocal() as db:
        process_privacy_request(db, event)
        db.commit()


def _execute(request_id: UUID, organization_id: UUID, user_id: UUID) -> None:
    with SessionLocal() as db:
        request_deletion_execution(db, organization_id=organization_id, actor_user_id=user_id, request_id=request_id)
        db.commit()


def _row(request_id: UUID) -> PrivacyDataRequest:
    with SessionLocal() as db:
        row = db.scalar(select(PrivacyDataRequest).where(PrivacyDataRequest.id == request_id))
        assert row is not None
        db.expunge(row)
        return row


def _document_of(request_id: UUID, storage: LocalObjectStorage) -> dict:
    import zipfile

    with storage.open_read(_row(request_id).artifact_reference) as handle, zipfile.ZipFile(BytesIO(handle.read())) as archive:
        return json.loads(archive.read("export.json"))


def _actor(user_id: UUID) -> User:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        db.expunge(user)
        return user


def _agent_run(world) -> UUID:
    """A published agent with one queued run. The run stores the input values and the agent's own configuration."""
    draft = create_draft(world, cfg=config(instructions=INSTRUCTIONS))
    agent_id = draft["id"] if isinstance(draft["id"], UUID) else UUID(draft["id"])
    publish(world, agent_id)
    with SessionLocal() as db:
        execution, _ = create_execution(
            db,
            organization_id=world.org.id,
            agent_id=agent_id,
            user_context=CurrentUserContext(user=_actor(world.member.id)),
            input_values={"contact": str(world.contact_id)},
            idempotency_key=f"derived-{uuid4().hex}",
        )
        db.commit()
        return execution.id


def _seed_lead_records(world) -> dict[str, UUID]:
    """A lead with a priority score, a human correction, and a lead intake submission that carries personal data."""
    with SessionLocal() as db:
        organization = db.get(Organization, world.org.id)
        assert organization is not None
        lead = create_lead(db, organization=organization)
        score = LeadPriorityScore(
            organization_id=world.org.id,
            lead_id=lead.id,
            ruleset_version="v1",
            score=72,
            band="high",
            method="rule_based_baseline",
            confidence="medium",
            insufficient_data=False,
            factors=[{"rule": "budget", "note": "Asha said the budget is 80 lakh"}],
            missing_factors=[],
            requirement_summary=[{"city": "Bengaluru"}],
            input_hash="f" * 64,
            computed_at=datetime.now(UTC),
            computed_by_user_id=world.owner.id,
        )
        db.add(score)
        db.flush()
        db.add(
            LeadPriorityCorrection(
                organization_id=world.org.id,
                score_id=score.id,
                lead_id=lead.id,
                corrected_band="medium",
                corrected_score=55,
                reason="The buyer postponed the purchase by a year",
                idempotency_key=f"correction-{uuid4().hex}",
                actor_user_id=world.owner.id,
            )
        )
        intake = LeadIntakeSubmission(
            organization_id=world.org.id,
            source_channel="form",
            external_reference=f"ref-{uuid4().hex[:8]}",
            payload_hash="a" * 64,
            raw_payload={"name": "Asha Rao", "phone": "+911234567890"},
            normalized_payload={"name": "Asha Rao"},
            validation_problems=[],
            status=LeadIntakeSubmission.STATUS_RECEIVED,
            candidate_contact_ids=[],
            submitted_by_user_id=world.owner.id,
        )
        db.add(intake)
        db.commit()
        return {"lead": lead.id, "score": score.id, "intake": intake.id}


# ---------------------------------------------------------------------------------------------------------------
# Export coverage
# ---------------------------------------------------------------------------------------------------------------


def test_agent_runs_are_exported_with_their_inputs_and_never_their_definitions(derived, storage) -> None:
    execution_id = _agent_run(derived)
    request_id = _request(derived.org.id, derived.owner.id, "export", ["ai.execution_traces"])
    _run(request_id, derived.org.id)

    document = _document_of(request_id, storage)
    runs = document["categories"]["ai.execution_traces"]
    assert [item["id"] for item in runs] == [str(execution_id)]
    assert runs[0]["input_values"] == {"contact": str(derived.contact_id)}
    assert document["categories"]["ai.execution_traces/steps"] == []  # the run has not started, so no steps exist
    serialized = json.dumps(document)
    # Internal configuration and prompts are never exported.
    assert INSTRUCTIONS not in serialized
    assert "idempotency_key" not in serialized
    assert "validation_snapshot" not in serialized


def test_lead_intake_and_priority_records_are_exported_and_their_personal_text_is_cleared(derived, storage) -> None:
    ids = _seed_lead_records(derived)
    export_id = _request(derived.org.id, derived.owner.id, "export", ["crm.lead_intake", "crm.lead_intelligence"])
    _run(export_id, derived.org.id)
    document = _document_of(export_id, storage)
    assert document["categories"]["crm.lead_intake"][0]["raw_payload"]["phone"] == "+911234567890"
    assert document["categories"]["crm.lead_intelligence"][0]["factors"][0]["note"].startswith("Asha said")
    assert document["categories"]["crm.lead_intelligence/corrections"][0]["reason"].startswith("The buyer postponed")

    deletion_id = _request(derived.org.id, derived.owner.id, "deletion", ["crm.lead_intake", "crm.lead_intelligence"])
    _execute(deletion_id, derived.org.id, derived.owner.id)
    _run(deletion_id, derived.org.id)

    with SessionLocal() as db:
        intake = db.get(LeadIntakeSubmission, ids["intake"])
        score = db.get(LeadPriorityScore, ids["score"])
        correction = db.scalar(select(LeadPriorityCorrection).where(LeadPriorityCorrection.score_id == ids["score"]))
        assert intake is not None and intake.raw_payload == {} and intake.normalized_payload is None
        # The digest is replaced by a tombstone (decision 5); the status is kept.
        assert intake.payload_hash != "a" * 64 and intake.status == LeadIntakeSubmission.STATUS_RECEIVED
        assert score is not None and score.factors == [] and score.score == 72 and score.band == "high"
        assert correction is not None and correction.reason == "Redacted" and correction.corrected_score == 55


def test_human_tasks_and_events_are_exported_and_cleared_on_deletion(derived, storage) -> None:
    with SessionLocal() as db:
        task = HumanTask(
            organization_id=derived.org.id,
            kind="approval",
            status=HumanTask.STATUS_PENDING,
            title="Approve the buyer's refund request",
            instructions="The buyer wants the deposit back",
            required_permission="agents.run",
            requested_by_user_id=derived.owner.id,
            version=1,
        )
        db.add(task)
        db.flush()
        db.add(
            HumanTaskEvent(
                organization_id=derived.org.id,
                task_id=task.id,
                event_type="comment",
                actor_user_id=derived.owner.id,
                comment="Call the buyer before deciding",
                detail={"channel": "phone"},
            )
        )
        db.commit()
        task_id = task.id

    export_id = _request(derived.org.id, derived.owner.id, "export", ["automation.human_tasks"])
    _run(export_id, derived.org.id)
    document = _document_of(export_id, storage)
    assert document["categories"]["automation.human_tasks"][0]["instructions"] == "The buyer wants the deposit back"
    assert document["categories"]["automation.human_tasks/events"][0]["comment"] == "Call the buyer before deciding"

    deletion_id = _request(derived.org.id, derived.owner.id, "deletion", ["automation.human_tasks"])
    _execute(deletion_id, derived.org.id, derived.owner.id)
    _run(deletion_id, derived.org.id)
    with SessionLocal() as db:
        task = db.get(HumanTask, task_id)
        event = db.scalar(select(HumanTaskEvent).where(HumanTaskEvent.task_id == task_id))
        assert task is not None and task.title == "Redacted" and task.instructions is None
        assert task.status == HumanTask.STATUS_PENDING
        # The history is append-only: the event keeps its comment, and the deletion says so.
        assert event is not None and event.comment == "Call the buyer before deciding"
    execution = json.loads(_row(deletion_id).execution)["automation.human_tasks"]
    assert execution["outcome"] == "anonymized_partial"
    assert any(item.startswith("retained: human_task_events") for item in execution["not_changed"])
    assert execution["outcome"] != "deleted"


def _stored_document(world, storage: LocalObjectStorage) -> UUID:
    """A document with a stored file and a matching checksum, so the documents export can complete."""
    # The shared agent fixture stores a document with no file. An export refuses a missing file for the whole
    # category, so that placeholder is removed first.
    with SessionLocal() as db:
        db.execute(delete(Document).where(Document.id == world.document_id))
        db.commit()
    document_id = uuid4()
    key = f"{world.org.id}/{document_id.hex}/brochure.txt"
    content = b"South-facing balcony, two bedrooms."
    storage.put(key, BytesIO(content))
    with SessionLocal() as db:
        db.add(
            Document(
                id=document_id,
                organization_id=world.org.id,
                original_filename="brochure.txt",
                display_name="Brochure",
                category=Document.CATEGORY_AGREEMENT,
                document_type="Brochure",
                content_type="text/plain",
                file_extension=".txt",
                file_size_bytes=len(content),
                checksum_sha256=hashlib.sha256(content).hexdigest(),
                storage_backend="local",
                storage_key=key,
                access_classification=Document.CLASSIFICATION_INTERNAL,
                status=Document.STATUS_AVAILABLE,
                scan_status=Document.SCAN_CLEAN,
                uploaded_by_user_id=world.owner.id,
                created_by_user_id=world.owner.id,
            )
        )
        db.commit()
    return document_id


def test_knowledge_chunks_are_exported_without_vectors_and_deleted_on_request(derived, storage) -> None:
    document_id = _stored_document(derived, storage)
    with SessionLocal() as db:
        db.add(
            KnowledgeChunk(
                organization_id=derived.org.id,
                document_id=document_id,
                chunk_index=0,
                content="The flat has a south-facing balcony.",
                content_hash="b" * 64,
                embedding_model="test-embedding",
                embedding=[0.12, 0.34, 0.56],
            )
        )
        db.add(
            DocumentReview(
                organization_id=derived.org.id,
                document_id=document_id,
                method="pdf_text",
                page_count=2,
                title="Sale deed for Asha Rao",
                author="Registrar office",
                summary_text="Sale deed between Asha Rao and the seller",
                fields=[{"name": "buyer", "value": "Asha Rao"}],
            )
        )
        db.commit()

    export_id = _request(derived.org.id, derived.owner.id, "export", ["ai.embeddings", "documents.files"])
    _run(export_id, derived.org.id)
    document = _document_of(export_id, storage)
    assert document["coverage"]["not_exported"] == []
    chunk = document["categories"]["ai.embeddings"][0]
    assert chunk["content"] == "The flat has a south-facing balcony."
    assert "embedding" not in chunk
    review = document["categories"]["documents.files/reviews"][0]
    assert review["title"] == "Sale deed for Asha Rao"

    deletion_id = _request(derived.org.id, derived.owner.id, "deletion", ["ai.embeddings"])
    _execute(deletion_id, derived.org.id, derived.owner.id)
    _run(deletion_id, derived.org.id)
    with SessionLocal() as db:
        remaining = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.organization_id == derived.org.id)).all()
    assert remaining == []
    execution = json.loads(_row(deletion_id).execution)
    assert execution["ai.embeddings"]["outcome"] == "deleted"
    assert execution["ai.embeddings"]["count"] == 1


# ---------------------------------------------------------------------------------------------------------------
# Holds, isolation and clearing rules
# ---------------------------------------------------------------------------------------------------------------


def test_a_legal_hold_keeps_agent_run_inputs_in_place(derived, storage) -> None:
    execution_id = _agent_run(derived)
    request_id = _request(derived.org.id, derived.owner.id, "deletion", ["ai.execution_traces"])
    with SessionLocal() as db:
        place_legal_hold(db, organization_id=derived.org.id, actor_user_id=derived.owner.id,
                         category_key="ai.execution_traces", reason="Regulator request open")
        db.commit()
    _execute(request_id, derived.org.id, derived.owner.id)
    _run(request_id, derived.org.id)

    execution = json.loads(_row(request_id).execution)
    assert execution["ai.execution_traces"]["outcome"] == "skipped"
    with SessionLocal() as db:
        row = db.get(AgentExecution, execution_id)
        assert row is not None and row.input_values == {"contact": str(derived.contact_id)}


def test_agent_run_deletion_clears_inputs_and_keeps_the_run_record(derived, storage) -> None:
    execution_id = _agent_run(derived)
    request_id = _request(derived.org.id, derived.owner.id, "deletion", ["ai.execution_traces"])
    _execute(request_id, derived.org.id, derived.owner.id)
    _run(request_id, derived.org.id)

    execution = json.loads(_row(request_id).execution)["ai.execution_traces"]
    assert execution["outcome"] == "anonymized_partial"
    assert "agent_executions.status" in execution["not_changed"]
    with SessionLocal() as db:
        row = db.get(AgentExecution, execution_id)
        assert row is not None and row.input_values == {}
        assert row.status  # the run state is kept
        assert row.correlation_id  # operational correlation is kept


def test_another_organization_derived_records_are_never_exported(derived, storage) -> None:
    _seed_lead_records(derived)
    other = derived.other_org
    with SessionLocal() as db:
        db.add(
            LeadIntakeSubmission(
                organization_id=other.id,
                source_channel="form",
                external_reference="other-ref",
                payload_hash="c" * 64,
                raw_payload={"name": "Other Tenant Buyer"},
                validation_problems=[],
                status=LeadIntakeSubmission.STATUS_RECEIVED,
                candidate_contact_ids=[],
                submitted_by_user_id=derived.other.id,
            )
        )
        db.commit()
    export_id = _request(derived.org.id, derived.owner.id, "export", ["crm.lead_intake"])
    _run(export_id, derived.org.id)
    serialized = json.dumps(_document_of(export_id, storage))
    assert "Other Tenant Buyer" not in serialized


def test_an_export_of_derived_records_is_refused_without_the_manage_permission(derived, storage) -> None:
    with TestClient(_app_for(_actor(derived.member.id))) as client:
        client.headers.update({"X-Organization-ID": str(derived.org.id)})
        response = client.post(
            f"{BASE}/privacy/requests",
            json={"request_type": "export", "categories": ["ai.execution_traces"], "confirm": True},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------------------------------------------
# Manifest and register completeness
# ---------------------------------------------------------------------------------------------------------------

# Categories whose producers exist and that are deliberately not exported. Each one is justified in the register.
EXPLICITLY_NOT_EXPORTED = {"billing.records", "audit.events"}


def test_every_producing_category_is_exported_or_explicitly_excluded() -> None:
    exported = set(EXPORTERS) | {"documents.files", "messaging.email_outbox"}
    for category in CATEGORIES:
        if not category.producer_exists or not category.organization_owned:
            continue
        if category.key in exported or category.key in EXPLICITLY_NOT_EXPORTED:
            continue
        pytest.fail(f"{category.key} has a producer but is neither exported nor explicitly excluded")


def test_every_derived_clearing_rule_names_a_registered_category() -> None:
    keys = {category.key for category in CATEGORIES}
    assert set(CLEARING_RULES) <= keys
    assert set(DERIVED_EXPORTERS) <= keys


def test_the_manifest_not_covered_list_matches_the_inventory() -> None:
    expected = {table for table, entry in TABLE_INVENTORY.items() if entry.disposition != DISPOSITION_EXPORTED}
    listed = {item["table"] for item in privacy_execution.NOT_COVERED_TABLES}
    assert listed == expected
    assert all(item["reason"] for item in privacy_execution.NOT_COVERED_TABLES)


def test_every_exported_inventory_entry_names_an_export_category() -> None:
    keys = set(EXPORTERS) | set(SUB_RECORD_EXPORTERS) | {"documents.files", "messaging.email_outbox"}
    for table, entry in TABLE_INVENTORY.items():
        if entry.disposition == DISPOSITION_EXPORTED:
            assert entry.category in {c.key for c in CATEGORIES}, table
            assert any(entry.category == key or entry.category in key for key in keys), table


def test_a_recorded_deletion_stays_eligibility_recorded_until_executed(derived, storage) -> None:
    request_id = _request(derived.org.id, derived.owner.id, "deletion", ["crm.leads"])
    assert _row(request_id).status == STATUS_ELIGIBILITY_RECORDED


def test_a_legal_hold_blocks_human_task_clearing_and_task_fields_stay(derived, storage) -> None:
    with SessionLocal() as db:
        task = HumanTask(
            organization_id=derived.org.id,
            kind="approval",
            status=HumanTask.STATUS_PENDING,
            title="Approve the refund",
            instructions="Refund the deposit to the buyer",
            required_permission="agents.run",
            requested_by_user_id=derived.owner.id,
            version=1,
        )
        db.add(task)
        db.flush()
        db.commit()
        task_id = task.id
    # The request is recorded first, then the hold is placed. The hold must still block the execution.
    deletion_id = _request(derived.org.id, derived.owner.id, "deletion", ["automation.human_tasks"])
    with SessionLocal() as db:
        place_legal_hold(db, organization_id=derived.org.id, actor_user_id=derived.owner.id,
                         category_key="automation.human_tasks", reason="Dispute open")
        db.commit()
    _execute(deletion_id, derived.org.id, derived.owner.id)
    _run(deletion_id, derived.org.id)

    assert json.loads(_row(deletion_id).execution)["automation.human_tasks"]["outcome"] == "skipped"
    with SessionLocal() as db:
        task = db.get(HumanTask, task_id)
        assert task is not None and task.instructions == "Refund the deposit to the buyer"

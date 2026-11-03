"""Privacy governed changes record evidence independently of the business transaction (WP3).

A governed change records a ``requested`` row in its own committed transaction before the change, and an
``outcome`` row in the business transaction. These tests prove the evidence survives a rollback, and that a change
does not run when its requested record cannot be written.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import delete, select

from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_REQUESTED,
    AuditPersistenceError,
)
from app.db.models.audit_event import AuditEvent
from app.db.models.privacy_records import PrivacyDataRequest
from app.db.session import SessionLocal
from app.governance import privacy as privacy_module
from app.governance import privacy_execution
from app.governance.privacy import (
    PRIVACY_EVENT_TYPE,
    STATUS_ELIGIBILITY_RECORDED,
    record_completed_privacy_event,
    record_requested_privacy_event,
)
from tests.test_team_api import create_owner_manager


@pytest.fixture
def org() -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    user, organization = create_owner_manager(permissions=("governance.privacy.manage",))
    yield organization.id, user.id
    with SessionLocal() as db:
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization.id))
        db.commit()


def _rows(organization_id: uuid.UUID, action: str) -> list[AuditEvent]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.event_type == PRIVACY_EVENT_TYPE,
                AuditEvent.action == action,
            )
        ).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def _deletion_request(organization_id: uuid.UUID, user_id: uuid.UUID) -> PrivacyDataRequest:
    """An eligible deletion held in memory. Only the audit writes touch the database in these tests."""
    return PrivacyDataRequest(
        id=uuid.uuid4(),
        organization_id=organization_id,
        requested_by_user_id=user_id,
        request_type=PrivacyDataRequest.TYPE_DELETION,
        status=STATUS_ELIGIBILITY_RECORDED,
        categories=json.dumps(["crm.contacts"]),
        decisions=json.dumps({"crm.contacts": {"eligible": True, "reasons": []}}),
        attempt_count=0,
        execution="{}",
    )


def test_a_requested_record_survives_the_rollback_of_its_business_transaction(org) -> None:
    organization_id, user_id = org
    action = "privacy.deletion.requested"
    with SessionLocal() as db:
        record_requested_privacy_event(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            action=action,
            resource_type="privacy_request",
            resource_id=str(uuid.uuid4()),
            metadata={"probe": True},
        )
        db.rollback()

    rows = _rows(organization_id, action)
    assert len(rows) == 1
    assert rows[0].outcome == OUTCOME_REQUESTED


def test_an_outcome_record_is_removed_by_the_rollback_of_its_business_transaction(org) -> None:
    organization_id, user_id = org
    action = "privacy.deletion.completed"
    with SessionLocal() as db:
        requested = record_requested_privacy_event(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            action="privacy.deletion.requested",
            resource_type="privacy_request",
            resource_id=str(uuid.uuid4()),
            metadata={},
        )
        db.commit()
    with SessionLocal() as db:
        record_completed_privacy_event(
            db,
            requested=requested,
            action=action,
            resource_type="privacy_request",
            resource_id=str(requested.resource_id),
            metadata={},
        )
        db.rollback()

    assert _rows(organization_id, action) == []
    kept = _rows(organization_id, "privacy.deletion.requested")
    assert len(kept) == 1 and kept[0].outcome == OUTCOME_REQUESTED


def test_processing_without_a_user_is_attributed_to_the_privacy_system_actor(org) -> None:
    organization_id, _user_id = org
    with SessionLocal() as db:
        row = record_requested_privacy_event(
            db,
            organization_id=organization_id,
            actor_user_id=None,
            action="privacy.retention.requested",
            resource_type="retention_policy",
            resource_id="crm.contacts",
            metadata={"retention_days": 30},
        )
        db.commit()
        assert row.user_id is None
        assert row.organization_id == organization_id
        assert row.outcome == OUTCOME_REQUESTED
        assert json.loads(row.event_metadata) == {"retention_days": 30}


def test_a_deletion_that_fails_after_its_requested_record_keeps_the_evidence_and_no_outcome(org, monkeypatch) -> None:
    organization_id, user_id = org
    request = _deletion_request(organization_id, user_id)

    def fail(*args, **kwargs):
        raise RuntimeError("storage unavailable mid-deletion")

    monkeypatch.setattr(privacy_execution, "_execute_category", fail)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError):
            privacy_execution.execute_deletion(
                db, request, storage=_NoStorage(), now=_now()
            )
        db.rollback()

    requested = _rows(organization_id, "privacy.deletion.requested")
    assert len(requested) == 1
    assert requested[0].outcome == OUTCOME_REQUESTED
    assert json.loads(requested[0].event_metadata)["eligible"] == ["crm.contacts"]
    assert _rows(organization_id, "privacy.deletion.blocked") == []
    assert _rows(organization_id, "privacy.deletion.completed") == []


def test_a_change_does_not_run_when_its_requested_record_cannot_be_written(org, monkeypatch) -> None:
    organization_id, user_id = org
    request = _deletion_request(organization_id, user_id)
    executed: list[str] = []

    def record_executed(*args, **kwargs):
        executed.append("executed")

    def unavailable(*args, **kwargs):
        raise AuditPersistenceError("The audit record could not be written.")

    monkeypatch.setattr(privacy_execution, "_execute_category", record_executed)
    monkeypatch.setattr(privacy_execution, "record_requested_privacy_event", unavailable)
    with SessionLocal() as db:
        with pytest.raises(AuditPersistenceError):
            privacy_execution.execute_deletion(db, request, storage=_NoStorage(), now=_now())
        db.rollback()

    assert executed == []
    assert request.status == STATUS_ELIGIBILITY_RECORDED


def test_outcome_records_are_linked_to_their_requested_record(org) -> None:
    organization_id, user_id = org
    with SessionLocal() as db:
        requested = record_requested_privacy_event(
            db,
            organization_id=organization_id,
            actor_user_id=user_id,
            action="privacy.export.generation",
            resource_type="privacy_request",
            resource_id=str(uuid.uuid4()),
            metadata={},
        )
        db.commit()
        requested_id = str(requested.id)
    with SessionLocal() as db:
        record_completed_privacy_event(
            db,
            requested=db.get(AuditEvent, uuid.UUID(requested_id)),
            action="privacy.export.ready",
            resource_type="privacy_request",
            resource_id=str(uuid.uuid4()),
            metadata={},
        )
        db.commit()

    completed = _rows(organization_id, "privacy.export.ready")
    assert len(completed) == 1
    assert completed[0].outcome == OUTCOME_COMPLETED
    assert completed[0].causation_id == requested_id


class _NoStorage:
    """Storage that must not be touched. The deletion never reaches it in these tests."""

    def exists(self, key: str) -> bool:  # pragma: no cover - never reached
        raise AssertionError("storage must not be used")


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def test_the_privacy_helpers_are_the_only_governed_privacy_audit_writers() -> None:
    """Every privacy governed change goes through the WP3 pair, so none can skip the independent record."""
    import pathlib

    source = pathlib.Path(privacy_execution.__file__).read_text(encoding="utf-8")
    assert "AuditEvent(" not in source
    assert "audit_privacy_event" not in source
    assert privacy_module.PRIVACY_SYSTEM_ACTOR is not None

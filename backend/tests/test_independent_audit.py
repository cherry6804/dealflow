"""Independent audit persistence: durability, fail-closed behaviour, idempotency and attribution (WS6 WP3).

Runs on PostgreSQL. Concurrency cases use real threads with separate sessions, and rollback cases roll back
the business session that triggered the audit, which is the situation WP3 must survive.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.governance import router as governance_router
from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_DENIED,
    OUTCOME_REQUESTED,
    AuditPayloadError,
    AuditPersistenceError,
    encode_metadata,
    persist_independent_audit_event,
)
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.session import SessionLocal, get_db_session
from app.errors import register_error_handlers
from app.governance import service as capability_service
from app.governance.ai_execution import AiExecutionDenied, require_ai_execution
from app.governance.capabilities import AI_MASTER, AUTOMATION_MASTER
from app.governance.service import set_capability_enabled
from app.governance.usage_ledger import UsageUnit, change_budget
from tests.test_team_api import (
    TestingSessionLocal,
    create_manager,
    create_owner_manager,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
EVENT_TYPE = "governance"


def _cleanup(organization_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.execute(delete(OrganizationCapabilitySetting).where(
            OrganizationCapabilitySetting.organization_id == organization_id))
        db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization_id))
        db.commit()


@pytest.fixture
def owned() -> Iterator[tuple[UUID, UUID]]:
    user, organization = create_manager(permissions=("governance.capabilities.manage", "governance.budgets.manage"))
    yield organization.id, user.id
    _cleanup(organization.id)


def _rows(organization_id: UUID) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditEvent).where(AuditEvent.organization_id == organization_id)).all())


def _setting_exists(organization_id: UUID) -> bool:
    with SessionLocal() as db:
        return db.scalar(select(OrganizationCapabilitySetting.id).where(
            OrganizationCapabilitySetting.organization_id == organization_id)) is not None


def _race(functions: list[Callable]) -> tuple[list, list]:
    barrier = threading.Barrier(len(functions))
    results: list = [None] * len(functions)
    errors: list = [None] * len(functions)

    def run(index: int, fn: Callable) -> None:
        barrier.wait()
        try:
            results[index] = fn()
        except (AuditPersistenceError, AuditPayloadError) as exc:
            errors[index] = exc

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(functions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "a race thread did not finish"
    return results, errors


# --- Durability when the business transaction rolls back -----------------------------------------


def test_a_requested_record_persists_when_the_business_transaction_rolls_back(owned) -> None:
    organization_id, user_id = owned
    db = SessionLocal()
    try:
        set_capability_enabled(db, organization_id=organization_id, actor_user_id=user_id,
                               capability_key=AUTOMATION_MASTER, is_enabled=True)
        db.rollback()
    finally:
        db.close()

    rows = _rows(organization_id)
    assert [row.outcome for row in rows] == [OUTCOME_REQUESTED]
    assert not _setting_exists(organization_id), "the change itself must roll back with its transaction"


def test_a_denial_persists_when_the_request_rolls_back(owned) -> None:
    organization_id, _ = owned
    db = SessionLocal()
    try:
        with pytest.raises(AiExecutionDenied):
            require_ai_execution(db, organization_id=organization_id, capability_key=AI_MASTER)
        db.rollback()
    finally:
        db.close()

    denials = [row for row in _rows(organization_id) if row.outcome == OUTCOME_DENIED]
    assert len(denials) == 1
    assert denials[0].action == "denied"
    assert json.loads(denials[0].event_metadata)["reason_code"]


def test_a_successful_budget_change_writes_a_requested_then_a_linked_completed_record(owned) -> None:
    organization_id, user_id = owned
    with SessionLocal() as db:
        change_budget(db, organization_id=organization_id, actor_user_id=user_id,
                      unit=UsageUnit.TOKENS_OUTPUT, limit_quantity=500, moment=NOW)
        db.commit()

    rows = _rows(organization_id)
    requested = [row for row in rows if row.outcome == OUTCOME_REQUESTED]
    completed = [row for row in rows if row.outcome == OUTCOME_COMPLETED]
    assert len(requested) == 1 and len(completed) == 1
    assert completed[0].causation_id == str(requested[0].id)
    assert completed[0].correlation_id == requested[0].correlation_id
    assert completed[0].user_id == user_id == requested[0].user_id
    assert completed[0].organization_id == organization_id


# --- Fail-closed behaviour ------------------------------------------------------------------------


def test_a_failed_requested_record_stops_the_change(owned, monkeypatch) -> None:
    organization_id, user_id = owned

    def unavailable(*args, **kwargs):
        raise AuditPersistenceError("The audit record could not be written.")

    monkeypatch.setattr(capability_service, "persist_independent_audit_event", unavailable)
    with SessionLocal() as db:
        with pytest.raises(AuditPersistenceError):
            set_capability_enabled(db, organization_id=organization_id, actor_user_id=user_id,
                                   capability_key=AUTOMATION_MASTER, is_enabled=True)
        db.rollback()

    assert not _setting_exists(organization_id)
    assert _rows(organization_id) == []


def test_a_database_refusal_of_the_audit_write_is_reported_as_unavailable(owned) -> None:
    # An organization that does not exist violates the foreign key, so the independent write fails.
    with pytest.raises(AuditPersistenceError):
        persist_independent_audit_event(
            SessionLocal(),
            organization_id=uuid4(),
            actor_user_id=None,
            event_type=EVENT_TYPE,
            action="test.unknown_organization",
            decision="allowed",
            outcome=OUTCOME_REQUESTED,
        )


def test_an_audit_outage_returns_503_and_leaves_the_setting_unchanged(monkeypatch) -> None:
    # Capability changes are owner-only, so the request must come from an owner.
    user, organization = create_owner_manager(permissions=("governance.capabilities.manage",))
    organization_id = organization.id

    def unavailable(*args, **kwargs):
        raise AuditPersistenceError("The audit record could not be written.")

    monkeypatch.setattr(capability_service, "persist_independent_audit_event", unavailable)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(governance_router)

    def db_override():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = db_override
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    try:
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization_id)})
            response = client.patch(
                f"/api/v1/governance/capabilities/{AUTOMATION_MASTER}",
                json={"is_enabled": True, "confirm": True},
            )
    finally:
        _cleanup(organization_id)

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "AUDIT_UNAVAILABLE"
    assert "Retry-After" in response.headers
    assert not _setting_exists(organization_id)


# --- Idempotency and concurrency ------------------------------------------------------------------


def test_a_repeated_key_returns_the_stored_row(owned) -> None:
    organization_id, user_id = owned
    kwargs = {
        "organization_id": organization_id,
        "actor_user_id": user_id,
        "event_type": EVENT_TYPE,
        "action": "test.repeat",
        "decision": "allowed",
        "outcome": OUTCOME_REQUESTED,
        "idempotency_key": "op-1",
    }
    first = persist_independent_audit_event(SessionLocal(), **kwargs)
    second = persist_independent_audit_event(SessionLocal(), **kwargs)

    assert first.id == second.id
    assert len([row for row in _rows(organization_id) if row.idempotency_key == "op-1"]) == 1


def test_concurrent_writes_with_one_key_produce_one_row(owned) -> None:
    organization_id, user_id = owned

    def write() -> AuditEvent:
        return persist_independent_audit_event(
            SessionLocal(), organization_id=organization_id, actor_user_id=user_id, event_type=EVENT_TYPE,
            action="test.concurrent", decision="allowed", outcome=OUTCOME_REQUESTED, idempotency_key="race-key",
        )

    results, errors = _race([write for _ in range(6)])

    assert errors == [None] * 6
    assert len({row.id for row in results}) == 1
    assert len([row for row in _rows(organization_id) if row.idempotency_key == "race-key"]) == 1


def test_concurrent_distinct_events_are_all_persisted(owned) -> None:
    organization_id, user_id = owned

    def write(index: int) -> AuditEvent:
        return persist_independent_audit_event(
            SessionLocal(), organization_id=organization_id, actor_user_id=user_id, event_type=EVENT_TYPE,
            action=f"test.distinct.{index}", decision="allowed", outcome=OUTCOME_REQUESTED,
        )

    results, errors = _race([lambda i=i: write(i) for i in range(8)])

    assert errors == [None] * 8
    assert len({row.id for row in results}) == 8
    assert len([row for row in _rows(organization_id) if row.action.startswith("test.distinct.")]) == 8


# --- Attribution and tenant scope -----------------------------------------------------------------


def test_attribution_is_recorded_for_the_organization_and_actor(owned) -> None:
    organization_id, user_id = owned
    row = persist_independent_audit_event(
        SessionLocal(), organization_id=organization_id, actor_user_id=user_id, event_type=EVENT_TYPE,
        action="test.attribution", decision="allowed", outcome=OUTCOME_REQUESTED, correlation_id="corr-42",
    )

    assert row.organization_id == organization_id
    assert row.user_id == user_id
    assert row.correlation_id == "corr-42"


def test_operations_in_one_organization_never_write_into_another(owned) -> None:
    organization_id, user_id = owned
    other_org = uuid4()
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=organization_id, actor_user_id=user_id,
                               capability_key=AUTOMATION_MASTER, is_enabled=True)
        db.commit()

    assert _rows(organization_id)
    assert _rows(other_org) == []


# --- Sensitive content is refused -----------------------------------------------------------------


@pytest.mark.parametrize(
    "metadata",
    [
        {"api_key": "x"},
        {"password": "x"},
        {"access_token": "x"},
        {"client_secret": "x"},
        {"authorization": "Bearer x"},
        {"nested": {"ciphertext": "x"}},
        {"items": [{"private_key": "x"}]},
    ],
)
def test_sensitive_metadata_is_refused_before_any_write(owned, metadata) -> None:
    organization_id, user_id = owned
    with pytest.raises(AuditPayloadError):
        persist_independent_audit_event(
            SessionLocal(), organization_id=organization_id, actor_user_id=user_id, event_type=EVENT_TYPE,
            action="test.sensitive", decision="allowed", outcome=OUTCOME_REQUESTED, metadata=metadata,
        )
    assert _rows(organization_id) == []


def test_safe_metadata_is_stored_in_canonical_form() -> None:
    assert encode_metadata({"b": 2, "a": [1, "x", None]}) == '{"a":[1,"x",null],"b":2}'
    assert encode_metadata(None) is None


def test_oversized_metadata_is_refused() -> None:
    with pytest.raises(AuditPayloadError):
        encode_metadata({"note": "x" * 5000})


def test_non_scalar_values_are_refused() -> None:
    with pytest.raises(AuditPayloadError):
        encode_metadata({"value": object()})


def test_an_unsupported_outcome_is_rejected_without_writing(owned) -> None:
    organization_id, user_id = owned
    with pytest.raises(ValueError):
        persist_independent_audit_event(
            SessionLocal(), organization_id=organization_id, actor_user_id=user_id, event_type=EVENT_TYPE,
            action="test.bad_outcome", decision="allowed", outcome="maybe",
        )
    assert _rows(organization_id) == []

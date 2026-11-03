"""DFR1-017: every usage reversal is audited, linked and fails closed (WP3 pattern).

The reversal returns quantity to the budget. Its requested record is committed independently before the budget
changes, and the completed record is written in the business transaction, linked to the requested one. A failed
requested write leaves the budget unchanged. Repeating a reversal changes nothing and writes no new record.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_REQUESTED,
    AuditPersistenceError,
)
from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.session import SessionLocal
from app.governance import usage_ledger
from app.governance.usage_ledger import (
    InvalidUsageStateError,
    UsageInvariantError,
    UsageUnit,
    configure_budget,
    record,
    reverse,
)
from tests.test_team_api import create_owner_manager

UNIT = UsageUnit.TOKENS_OUTPUT
ACTION = usage_ledger.USAGE_ADJUSTMENT_ACTION


@pytest.fixture
def org() -> Iterator[tuple[uuid.UUID, uuid.UUID]]:
    user, organization = create_owner_manager(permissions=())
    yield organization.id, user.id
    with SessionLocal() as db:
        for model in (AiUsageEvent, OrganizationUsageBudget, AuditEvent):
            db.execute(delete(model).where(model.organization_id == organization.id))
        db.commit()


def _recorded(organization_id: uuid.UUID, key: str, quantity: int = 40) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        configure_budget(db, organization_id=organization_id, unit=UNIT, limit_quantity=100, moment=now)
        record(
            db,
            organization_id=organization_id,
            unit=UNIT,
            quantity=quantity,
            idempotency_key=key,
            occurred_at=now,
            capability_key="ai.assistant",
        )
        db.commit()


def _budget(organization_id: uuid.UUID) -> OrganizationUsageBudget:
    with SessionLocal() as db:
        row = db.scalar(select(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization_id))
        assert row is not None
        db.expunge(row)
        return row


def _audit(organization_id: uuid.UUID) -> list[AuditEvent]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditEvent).where(AuditEvent.organization_id == organization_id, AuditEvent.action == ACTION)
        ).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def test_a_reversal_returns_quantity_and_records_a_linked_pair(org) -> None:
    organization_id, user_id = org
    _recorded(organization_id, "rev-1")
    assert _budget(organization_id).consumed_quantity == 40

    with SessionLocal() as db:
        event = reverse(db, organization_id=organization_id, idempotency_key="rev-1", actor_user_id=user_id)
        db.commit()
        assert event.status == AiUsageEvent.STATUS_REVERSED

    assert _budget(organization_id).consumed_quantity == 0
    rows = _audit(organization_id)
    requested = [row for row in rows if row.outcome == OUTCOME_REQUESTED]
    completed = [row for row in rows if row.outcome == OUTCOME_COMPLETED]
    assert len(requested) == 1 and len(completed) == 1
    assert completed[0].causation_id == str(requested[0].id)
    assert completed[0].user_id == user_id


def test_a_reversal_without_a_user_is_attributed_to_the_usage_system_actor(org) -> None:
    organization_id, _user_id = org
    _recorded(organization_id, "rev-sys")
    with SessionLocal() as db:
        reverse(db, organization_id=organization_id, idempotency_key="rev-sys")
        db.commit()
    rows = _audit(organization_id)
    assert rows and all(row.user_id is None for row in rows)


def test_repeating_a_reversal_changes_nothing_and_writes_no_new_record(org) -> None:
    organization_id, user_id = org
    _recorded(organization_id, "rev-twice")
    with SessionLocal() as db:
        reverse(db, organization_id=organization_id, idempotency_key="rev-twice", actor_user_id=user_id)
        db.commit()
    before = len(_audit(organization_id))
    with SessionLocal() as db:
        reverse(db, organization_id=organization_id, idempotency_key="rev-twice", actor_user_id=user_id)
        db.commit()
    assert _budget(organization_id).consumed_quantity == 0
    assert len(_audit(organization_id)) == before


def test_reversing_an_unknown_key_is_refused_and_records_nothing(org) -> None:
    organization_id, user_id = org
    _recorded(organization_id, "rev-known")
    with SessionLocal() as db:
        with pytest.raises(InvalidUsageStateError):
            reverse(db, organization_id=organization_id, idempotency_key="missing", actor_user_id=user_id)
        db.rollback()
    assert _audit(organization_id) == []
    assert _budget(organization_id).consumed_quantity == 40


def test_a_failed_requested_record_blocks_the_reversal(org, monkeypatch) -> None:
    organization_id, user_id = org
    _recorded(organization_id, "rev-blocked")

    def unavailable(*args, **kwargs):
        raise AuditPersistenceError("The audit record could not be written.")

    monkeypatch.setattr(usage_ledger, "persist_independent_audit_event", unavailable)
    with SessionLocal() as db:
        with pytest.raises(AuditPersistenceError):
            reverse(db, organization_id=organization_id, idempotency_key="rev-blocked", actor_user_id=user_id)
        db.rollback()
    assert _budget(organization_id).consumed_quantity == 40
    with SessionLocal() as db:
        entry = db.scalar(select(AiUsageEvent).where(AiUsageEvent.idempotency_key == "rev-blocked"))
        assert entry is not None and entry.status == AiUsageEvent.STATUS_RECORDED


def test_rolling_back_the_reversal_keeps_the_requested_record(org) -> None:
    organization_id, user_id = org
    _recorded(organization_id, "rev-rollback")
    with SessionLocal() as db:
        reverse(db, organization_id=organization_id, idempotency_key="rev-rollback", actor_user_id=user_id)
        db.rollback()
    rows = _audit(organization_id)
    assert len(rows) == 1 and rows[0].outcome == OUTCOME_REQUESTED
    assert _budget(organization_id).consumed_quantity == 40


def test_an_inconsistent_budget_is_refused_as_an_invariant_violation(org) -> None:
    organization_id, user_id = org
    _recorded(organization_id, "rev-invariant")
    with SessionLocal() as db:
        budget = db.scalar(select(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization_id))
        budget.consumed_quantity = 1
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(UsageInvariantError):
            reverse(db, organization_id=organization_id, idempotency_key="rev-invariant", actor_user_id=user_id)
        db.rollback()

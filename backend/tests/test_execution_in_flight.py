"""WS6 WP8: in-flight revalidation of a multi-step execution.

The automation path is the only multi-step execution path that exists today. Each test changes one governing
condition after the first step has run, and checks that later steps do not start, that the stop is recorded
durably, and that the execution state is accurate. Budget reservation, consent and approval have no step
boundary on this path, so they are not exercised here. See docs/architecture/execution-gate-lifecycle.md.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import delete, select

from app.automation_rules import execution_service
from app.db.models.automation_execution import AutomationExecution
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.role_permission import RolePermission
from app.db.session import SessionLocal
from app.governance.capabilities import AUTOMATION_DEAL_CREATED_RULES
from app.governance.service import set_capability_enabled
from tests.test_automation_authority import (
    FOLLOW_UP_ACTIONS,
    authority_rows,
    build,
    follow_up_count,
    run,
)

TWO_STEPS = FOLLOW_UP_ACTIONS + [{"type": "CREATE_FOLLOW_UP", "config": {"days_after": 2, "title": "Second"}}]


def _stop_rows(organization_id: UUID):
    with SessionLocal() as db:
        from app.db.models.audit_event import AuditEvent

        return list(db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.action == "execution.stopped",
            )
        ).all())


def _after_step(monkeypatch, *, after_index: int, change) -> None:
    """Run ``change()`` once, right after the step at ``after_index`` has executed."""
    original = execution_service._execute_action
    state = {"changed": False}

    def wrapper(db, **kwargs):
        result = original(db, **kwargs)
        if not state["changed"] and kwargs["action"] is not None:
            state["count"] = state.get("count", -1) + 1
            if state["count"] == after_index:
                state["changed"] = True
                change()
        return result

    monkeypatch.setattr(execution_service, "_execute_action", wrapper)


def _disable_automation(world) -> None:
    with SessionLocal() as db:
        set_capability_enabled(
            db,
            organization_id=world.organization_id,
            actor_user_id=world.activator_id,
            capability_key=AUTOMATION_DEAL_CREATED_RULES,
            is_enabled=False,
        )
        db.commit()


def _remove_permissions(user_id: UUID, organization_id: UUID) -> None:
    with SessionLocal() as db:
        membership = db.scalar(select(Membership).where(
            Membership.user_id == user_id, Membership.organization_id == organization_id))
        role_ids = db.scalars(select(MembershipRole.role_id).where(
            MembershipRole.membership_id == membership.id)).all()
        db.execute(delete(RolePermission).where(RolePermission.role_id.in_(role_ids)))
        db.commit()


def _execution(world) -> AutomationExecution:
    with SessionLocal() as db:
        return db.scalar(select(AutomationExecution).where(
            AutomationExecution.rule_id == world.rule_id, AutomationExecution.event_id == world.deal_id))


def test_disabling_the_switch_stops_the_next_step_and_records_the_stop(monkeypatch) -> None:
    world = build(actions=TWO_STEPS)
    _after_step(monkeypatch, after_index=0, change=lambda: _disable_automation(world))

    summary = run(world)

    assert follow_up_count(world.organization_id) == 1
    status, results = summary[0]
    assert status == AutomationExecution.STATUS_FAILED
    assert [item["status"] for item in results] == ["SUCCEEDED", "STOPPED"]
    assert results[1]["reason_code"] == "capability_disabled"
    stops = _stop_rows(world.organization_id)
    assert [row.decision for row in stops] == ["denied"]
    assert json.loads(stops[0].event_metadata)["step_index"] == 1
    assert _execution(world).error_message.startswith("Execution stopped before a later step")


def test_a_stop_stops_every_later_rule_for_the_same_event(monkeypatch) -> None:
    world = build(actions=TWO_STEPS)
    with SessionLocal() as db:
        from app.db.models.automation_rule import AutomationRule

        rule = db.get(AutomationRule, world.rule_id)
        db.add(AutomationRule(
            organization_id=rule.organization_id,
            name="Second rule",
            description="Runs only if the first is not stopped",
            trigger_type="DEAL_CREATED",
            trigger_config={},
            conditions=[],
            actions=FOLLOW_UP_ACTIONS,
            status=AutomationRule.STATUS_ACTIVE,
            created_by_user_id=rule.created_by_user_id,
            updated_by_user_id=rule.updated_by_user_id,
        ))
        db.commit()
    _after_step(monkeypatch, after_index=0, change=lambda: _disable_automation(world))

    run(world)

    assert follow_up_count(world.organization_id) == 1


def test_permission_revocation_stops_the_next_step(monkeypatch) -> None:
    world = build(actions=TWO_STEPS)
    _after_step(monkeypatch, after_index=0,
                change=lambda: _remove_permissions(world.initiator_id, world.organization_id))

    summary = run(world)

    _, results = summary[0]
    assert [item["status"] for item in results] == ["SUCCEEDED", "STOPPED"]
    assert results[1]["reason_code"] == "permission_denied"
    assert follow_up_count(world.organization_id) == 1


def test_target_owner_revocation_is_refused_at_the_step_not_the_gate(monkeypatch) -> None:
    # The owner is authorized per action (WP5), so the second step is refused as an authority denial and the
    # execution continues to its own result. This is a step failure, not an in-flight stop.
    world = build(actions=TWO_STEPS)
    _after_step(monkeypatch, after_index=0,
                change=lambda: _remove_permissions(world.owner_id, world.organization_id))

    summary = run(world)

    _, results = summary[0]
    assert results[1]["reason_code"] == "target_owner_not_authorized"
    assert all(item["status"] != "STOPPED" for item in results)
    assert _stop_rows(world.organization_id) == []


def test_the_stop_survives_a_rollback_of_the_stopped_work(monkeypatch) -> None:
    world = build(actions=TWO_STEPS)
    _after_step(monkeypatch, after_index=0, change=lambda: _disable_automation(world))

    run(world, rollback=True)

    assert [row.decision for row in _stop_rows(world.organization_id)] == ["denied"]
    assert follow_up_count(world.organization_id) == 0


def test_a_replayed_event_after_a_stop_does_not_duplicate_the_execution(monkeypatch) -> None:
    world = build(actions=TWO_STEPS)
    _after_step(monkeypatch, after_index=0, change=lambda: _disable_automation(world))
    run(world)
    monkeypatch.undo()

    replay = run(world)

    assert replay == []
    with SessionLocal() as db:
        count = len(db.scalars(select(AutomationExecution.id).where(
            AutomationExecution.rule_id == world.rule_id,
            AutomationExecution.event_id == world.deal_id)).all())
    assert count == 1


def test_no_stop_is_recorded_when_nothing_changes() -> None:
    world = build(actions=TWO_STEPS)

    summary = run(world)

    assert summary[0][0] == AutomationExecution.STATUS_SUCCEEDED
    assert _stop_rows(world.organization_id) == []
    assert [row.outcome for row in authority_rows(world.organization_id)].count("requested") == 2

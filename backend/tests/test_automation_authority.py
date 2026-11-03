"""WS6 WP5: authority for automation rules and their actions.

The authority of an automation action is the rule's activator and the deal owner, read from the database at
execution time. The user who created the deal does not authorize the action.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth.dependencies import get_current_user_context
from app.authz.permissions import PERMISSION_DESCRIPTIONS
from app.automation_rules.authority import (
    ACTION_PERMISSIONS,
    AUTOMATION_AUTHORITY_EVENT_TYPE,
    AutomationAuthorityError,
    PermissionChecker,
    authorize_action,
)
from app.automation_rules.execution_service import execute_deal_created_automations
from app.automation_rules.schemas import AutomationRuleCreateRequest
from app.automation_rules.service import (
    activate_automation_rule,
    create_automation_rule,
    disable_automation_rule,
)
from app.db.models.audit_event import AuditEvent
from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.models.deal import Deal
from app.db.models.follow_up import FollowUp
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.db.session import SessionLocal
from tests.governance_helpers import attested_user_context
from tests.test_automation_execution_service import create_active_rule, create_test_deal
from tests.test_automation_rules_api import (
    AUTOMATION_CREATE,
    AUTOMATION_READ,
    AUTOMATION_UPDATE,
    request_as,
)
from tests.test_automation_rules_api import create_authorized_user as create_rules_user
from tests.test_automation_rules_api import create_rule as create_rule_via_api
from tests.test_deals_api import (
    create_authorized_user as create_deals_user,
)
from tests.test_deals_api import (
    create_customer_profile,
    create_lead,
    create_membership,
    create_property,
    create_test_app,
    create_user,
    grant_permission,
)
from tests.test_deals_api import valid_payload as valid_deal_payload

FOLLOW_UP_ACTIONS = [{"type": "CREATE_FOLLOW_UP", "config": {"days_after": 1, "title": "Authority"}}]
ACTIVATOR_PERMISSIONS = ("automation.update", "leads.update")
OWNER_PERMISSIONS = ("leads.update",)


@dataclass(frozen=True)
class World:
    organization_id: UUID
    initiator_id: UUID
    activator_id: UUID
    owner_id: UUID
    lead_id: UUID
    rule_id: UUID
    deal_id: UUID


def _member(db, organization: Organization, permissions: tuple[str, ...]) -> User:
    user = create_user(db)
    membership = create_membership(db, user=user, organization=organization)
    for permission_key in permissions:
        grant_permission(db, membership=membership, permission_key=permission_key)
    return user


def build(
    *,
    activator_permissions: tuple[str, ...] = ACTIVATOR_PERMISSIONS,
    owner_permissions: tuple[str, ...] = OWNER_PERMISSIONS,
    initiator_permissions: tuple[str, ...] = ("deals.create",),
    actions: list[dict] | None = None,
) -> World:
    """An organization with an initiator, a rule activator, a deal owner, an active rule and a deal."""
    with SessionLocal() as db:
        db.expire_on_commit = False
        initiator, organization = create_deals_user(db, permission_keys=initiator_permissions)
        activator = _member(db, organization, activator_permissions)
        owner = _member(db, organization, owner_permissions)
        # The audit writer verifies attribution on its own connection, so members must be committed first.
        db.commit()
        lead = create_lead(db, organization=organization)
        deal = create_test_deal(db, user=owner, organization=organization, lead_id=lead.id)
        rule = create_active_rule(
            db,
            user=activator,
            organization=organization,
            conditions=[],
            actions=actions if actions is not None else FOLLOW_UP_ACTIONS,
        )
        db.commit()
        return World(
            organization_id=organization.id,
            initiator_id=initiator.id,
            activator_id=activator.id,
            owner_id=owner.id,
            lead_id=lead.id,
            rule_id=rule.id,
            deal_id=deal.id,
        )


def new_deal(world: World) -> UUID:
    with SessionLocal() as db:
        owner = db.get(User, world.owner_id)
        organization = db.get(Organization, world.organization_id)
        deal = create_test_deal(db, user=owner, organization=organization, lead_id=world.lead_id)
        db.commit()
        return deal.id


def run(world: World, *, deal_id: UUID | None = None, rollback: bool = False, system: bool = False):
    """Execute deal-created automations for the deal. Returns (status, action_results) per execution."""
    with SessionLocal() as db:
        initiator = db.get(User, world.initiator_id)
        deal = db.get(Deal, deal_id or world.deal_id)
        executions = execute_deal_created_automations(
            db,
            organization_id=world.organization_id,
            deal=deal,
            user_context=None
            if system
            else attested_user_context(initiator, organization_id=world.organization_id),
        )
        summary = [(execution.status, list(execution.action_results)) for execution in executions]
        if rollback:
            db.rollback()
        else:
            db.commit()
    return summary


def authority_rows(organization_id: UUID) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.organization_id == organization_id,
                    AuditEvent.event_type == AUTOMATION_AUTHORITY_EVENT_TYPE,
                )
                .order_by(AuditEvent.occurred_at, AuditEvent.id)
            ).all()
        )


def outcomes(rows: list[AuditEvent]) -> list[str]:
    return sorted(row.outcome for row in rows)


def by_outcome(rows: list[AuditEvent]) -> dict[str, AuditEvent]:
    return {row.outcome: row for row in rows}


def follow_up_count(organization_id: UUID) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(FollowUp.id).where(FollowUp.organization_id == organization_id)).all())


def revoke(world: World, who: str, how: str) -> None:
    user_id = world.activator_id if who == "activator" else world.owner_id
    with SessionLocal() as db:
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user_id, Membership.organization_id == world.organization_id
            )
        )
        if how == "membership":
            membership.is_active = False
        else:
            role_ids = db.scalars(
                select(MembershipRole.role_id).where(MembershipRole.membership_id == membership.id)
            ).all()
            db.execute(delete(RolePermission).where(RolePermission.role_id.in_(role_ids)))
        db.commit()


def reason_of(summary) -> str:
    return summary[0][1][0]["reason_code"]


# --- Action catalogue ---------------------------------------------------------------------------


def test_every_supported_action_maps_to_a_real_permission() -> None:
    # A new action type cannot be accepted by activation without a permission mapping.
    from app.automation_rules.service import SUPPORTED_ACTION_TYPE

    assert SUPPORTED_ACTION_TYPE in ACTION_PERMISSIONS
    assert all(key in PERMISSION_DESCRIPTIONS for key in ACTION_PERMISSIONS.values())


# --- Execution authority ------------------------------------------------------------------------


def test_activator_and_owner_with_the_permission_run_the_action() -> None:
    world = build()

    summary = run(world)

    assert summary[0][0] == AutomationExecution.STATUS_SUCCEEDED
    assert follow_up_count(world.organization_id) == 1
    rows = authority_rows(world.organization_id)
    assert outcomes(rows) == ["completed", "requested"]
    requested = by_outcome(rows)["requested"]
    assert requested.user_id == world.initiator_id
    metadata = json.loads(requested.event_metadata)
    assert metadata["rule_id"] == str(world.rule_id)
    assert metadata["deal_id"] == str(world.deal_id)
    assert metadata["activator_user_id"] == str(world.activator_id)
    assert metadata["owner_user_id"] == str(world.owner_id)
    assert metadata["action_type"] == "CREATE_FOLLOW_UP"
    completed = by_outcome(rows)["completed"]
    assert completed.causation_id == str(requested.id)
    assert json.loads(completed.event_metadata)["execution_status"] == "SUCCEEDED"


def test_the_user_who_created_the_deal_does_not_authorize_the_action() -> None:
    # The initiator holds only deals.create. The action runs because the activator and the owner hold
    # leads.update, not because of the initiator.
    world = build(initiator_permissions=("deals.create",))
    with SessionLocal() as db:
        assert PermissionChecker(db, world.organization_id).holds(world.initiator_id, "leads.update") is False

    assert run(world)[0][0] == AutomationExecution.STATUS_SUCCEEDED


def test_an_owner_without_the_permission_is_denied_even_if_the_initiator_holds_it() -> None:
    world = build(owner_permissions=(), initiator_permissions=("deals.create", "leads.update"))

    summary = run(world)

    assert summary[0][0] == AutomationExecution.STATUS_FAILED
    assert summary[0][1][0]["status"] == "FAILED"
    assert reason_of(summary) == "target_owner_not_authorized"
    assert follow_up_count(world.organization_id) == 0
    rows = authority_rows(world.organization_id)
    assert [(row.outcome, row.decision) for row in rows] == [("denied", "denied")]
    assert json.loads(rows[0].event_metadata)["reason_code"] == "target_owner_not_authorized"
    assert rows[0].user_id == world.initiator_id


def test_an_activator_without_the_action_permission_is_denied() -> None:
    world = build(activator_permissions=("automation.update",))

    summary = run(world)

    assert reason_of(summary) == "activator_not_authorized"
    assert follow_up_count(world.organization_id) == 0


@pytest.mark.parametrize(
    ("who", "how", "expected"),
    [
        ("activator", "membership", "activator_not_authorized"),
        ("activator", "permission", "activator_not_authorized"),
        ("owner", "membership", "target_owner_not_authorized"),
        ("owner", "permission", "target_owner_not_authorized"),
    ],
)
def test_a_permission_removed_after_activation_stops_the_next_execution(who, how, expected) -> None:
    world = build()
    assert run(world)[0][0] == AutomationExecution.STATUS_SUCCEEDED

    revoke(world, who, how)
    later = run(world, deal_id=new_deal(world))

    assert later[0][0] == AutomationExecution.STATUS_FAILED
    assert reason_of(later) == expected
    assert follow_up_count(world.organization_id) == 1


def test_a_rule_with_no_activator_fails_closed() -> None:
    world = build()
    with SessionLocal() as db:
        db.get(AutomationRule, world.rule_id).updated_by_user_id = None
        db.commit()

    summary = run(world)

    assert reason_of(summary) == "activator_missing"
    assert follow_up_count(world.organization_id) == 0


def test_an_unsupported_action_is_denied_and_audited() -> None:
    world = build(actions=[{"type": "SEND_EMAIL", "config": {}}])

    summary = run(world)

    assert reason_of(summary) == "unsupported_action"
    rows = authority_rows(world.organization_id)
    assert [row.outcome for row in rows] == ["denied"]
    assert json.loads(rows[0].event_metadata)["action_type"] == "SEND_EMAIL"
    assert "SEND_EMAIL" not in ACTION_PERMISSIONS


def test_a_rule_from_another_organization_cannot_be_authorized_for_this_deal() -> None:
    world_a = build()
    world_b = build()
    with SessionLocal() as db:
        decision = authorize_action(
            PermissionChecker(db, world_a.organization_id),
            rule=db.get(AutomationRule, world_b.rule_id),
            deal=db.get(Deal, world_a.deal_id),
            action_type="CREATE_FOLLOW_UP",
        )
    assert decision.allowed is False
    assert decision.reason_code == "organization_mismatch"

    run(world_a)
    assert follow_up_count(world_b.organization_id) == 0


def test_a_permission_in_another_organization_does_not_authorize() -> None:
    # The owner holds leads.update only in a different organization. It does not count here.
    world = build(owner_permissions=())
    other = build()
    with SessionLocal() as db:
        organization = db.get(Organization, world.organization_id)
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == world.owner_id, Membership.organization_id == organization.id
            )
        )
        other_organization = db.get(Organization, other.organization_id)
        foreign = create_membership(db, user=db.get(User, world.owner_id), organization=other_organization)
        grant_permission(db, membership=foreign, permission_key="leads.update")
        assert membership is not None
        db.commit()

    assert reason_of(run(world)) == "target_owner_not_authorized"


def test_a_system_actor_never_runs_automation() -> None:
    world = build()

    assert run(world, system=True) == []
    assert follow_up_count(world.organization_id) == 0
    assert authority_rows(world.organization_id) == []


# --- Durable audit, rollback and retry ----------------------------------------------------------


def test_a_denial_survives_the_transaction_rolling_back() -> None:
    world = build(owner_permissions=())

    run(world, rollback=True)

    rows = authority_rows(world.organization_id)
    assert [row.outcome for row in rows] == ["denied"]
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(AutomationExecution.id).where(AutomationExecution.rule_id == world.rule_id)
            )
            is None
        )


def test_an_allowed_decision_survives_a_rollback_but_no_completion_is_claimed() -> None:
    world = build()

    run(world, rollback=True)

    assert [row.outcome for row in authority_rows(world.organization_id)] == ["requested"]
    assert follow_up_count(world.organization_id) == 0


def test_retrying_the_same_event_does_not_duplicate_decisions_or_work() -> None:
    world = build()

    run(world)
    again = run(world)

    assert again == []
    assert outcomes(authority_rows(world.organization_id)) == ["completed", "requested"]
    assert follow_up_count(world.organization_id) == 1


# --- Rule activation ----------------------------------------------------------------------------


def _draft_rule(db, organization_id: UUID, user_id: UUID) -> AutomationRule:
    payload = AutomationRuleCreateRequest(
        name="Authority",
        trigger_type="DEAL_CREATED",
        trigger_config={"source": "deals"},
        conditions=[],
        actions=FOLLOW_UP_ACTIONS,
    )
    rule = create_automation_rule(db, organization_id=organization_id, user_id=user_id, payload=payload)
    db.commit()
    return rule


def _user_in_new_organization(permissions: tuple[str, ...]):
    with SessionLocal() as db:
        db.expire_on_commit = False
        user, organization = create_deals_user(db, permission_keys=permissions)
        rule = _draft_rule(db, organization.id, user.id)
        return user.id, organization.id, rule.id


def test_activation_needs_the_permission_of_every_action() -> None:
    user_id, organization_id, rule_id = _user_in_new_organization(("automation.update",))

    with SessionLocal() as db:
        with pytest.raises(AutomationAuthorityError) as denied:
            activate_automation_rule(db, organization_id=organization_id, rule_id=rule_id, user_id=user_id)
        db.rollback()

    assert denied.value.permission_key == "leads.update"
    with SessionLocal() as db:
        assert db.get(AutomationRule, rule_id).status == AutomationRule.STATUS_DRAFT
    rows = authority_rows(organization_id)
    assert [(row.action, row.outcome) for row in rows] == [("automation.rule.activate", "denied")]


def test_activation_rechecks_the_activation_permission_on_the_server() -> None:
    user_id, organization_id, rule_id = _user_in_new_organization(("leads.update",))

    with SessionLocal() as db:
        with pytest.raises(AutomationAuthorityError) as denied:
            activate_automation_rule(db, organization_id=organization_id, rule_id=rule_id, user_id=user_id)
        db.rollback()

    assert denied.value.permission_key == "automation.update"


def test_a_successful_activation_is_recorded_and_the_activator_becomes_the_authority() -> None:
    user_id, organization_id, rule_id = _user_in_new_organization(ACTIVATOR_PERMISSIONS)

    with SessionLocal() as db:
        rule = activate_automation_rule(db, organization_id=organization_id, rule_id=rule_id, user_id=user_id)
        assert rule.updated_by_user_id == user_id
        db.commit()

    rows = authority_rows(organization_id)
    assert outcomes(rows) == ["completed", "requested"]
    assert by_outcome(rows)["completed"].causation_id == str(by_outcome(rows)["requested"].id)
    assert all(row.user_id == user_id for row in rows)


def test_an_activation_that_rolls_back_leaves_no_completion() -> None:
    user_id, organization_id, rule_id = _user_in_new_organization(ACTIVATOR_PERMISSIONS)

    with SessionLocal() as db:
        activate_automation_rule(db, organization_id=organization_id, rule_id=rule_id, user_id=user_id)
        db.rollback()

    with SessionLocal() as db:
        assert db.get(AutomationRule, rule_id).status == AutomationRule.STATUS_DRAFT
    assert [row.outcome for row in authority_rows(organization_id)] == ["requested"]


def test_reactivating_by_another_user_changes_whose_authority_applies() -> None:
    world = build()
    with SessionLocal() as db:
        organization = db.get(Organization, world.organization_id)
        successor = _member(db, organization, ACTIVATOR_PERMISSIONS)
        db.commit()
        successor_id = successor.id
    with SessionLocal() as db:
        disable_automation_rule(
            db, organization_id=world.organization_id, rule_id=world.rule_id, user_id=world.activator_id
        )
        activate_automation_rule(
            db, organization_id=world.organization_id, rule_id=world.rule_id, user_id=successor_id
        )
        db.commit()

    # The first activator no longer matters. The successor is the authority.
    revoke(world, "activator", "membership")
    assert run(world)[0][0] == AutomationExecution.STATUS_SUCCEEDED


def test_a_successor_who_lacks_the_permission_cannot_take_over_a_rule() -> None:
    world = build()
    with SessionLocal() as db:
        organization = db.get(Organization, world.organization_id)
        weak = _member(db, organization, ("automation.update",))
        db.commit()
        weak_id = weak.id
    with SessionLocal() as db:
        disable_automation_rule(
            db, organization_id=world.organization_id, rule_id=world.rule_id, user_id=world.activator_id
        )
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(AutomationAuthorityError):
            activate_automation_rule(
                db, organization_id=world.organization_id, rule_id=world.rule_id, user_id=weak_id
            )
        db.rollback()

    with SessionLocal() as db:
        assert db.get(AutomationRule, world.rule_id).status == AutomationRule.STATUS_DISABLED
    assert run(world) == []


# --- API ----------------------------------------------------------------------------------------


def test_the_activate_route_returns_403_and_leaves_the_rule_a_draft() -> None:
    with SessionLocal() as db:
        user, organization = create_rules_user(
            db, permission_keys=(AUTOMATION_READ, AUTOMATION_CREATE, AUTOMATION_UPDATE)
        )
        with request_as(user=user, organization=organization) as client:
            created = create_rule_via_api(client)
            response = client.post(f"/api/v1/automation-rules/{created['id']}/activate")
            status = client.get(f"/api/v1/automation-rules/{created['id']}").json()["status"]

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "AUTOMATION_AUTHORITY_DENIED"
    assert status == AutomationRule.STATUS_DRAFT


def test_the_routes_require_the_authoring_permissions() -> None:
    with SessionLocal() as db:
        user, organization = create_rules_user(db, permission_keys=(AUTOMATION_READ, AUTOMATION_CREATE))
        with request_as(user=user, organization=organization) as client:
            created = create_rule_via_api(client)
            patched = client.patch(f"/api/v1/automation-rules/{created['id']}", json={"name": "Changed"})
            activated = client.post(f"/api/v1/automation-rules/{created['id']}/activate")

    assert patched.status_code == 403
    assert activated.status_code == 403


def test_a_denied_action_does_not_affect_manual_deal_creation() -> None:
    # The creator owns the new deal and lacks leads.update. The rule is active and valid. The deal is
    # created, the action is denied, and nothing is created for the lead.
    with SessionLocal() as db:
        db.expire_on_commit = False
        creator, organization = create_deals_user(db, permission_keys=("deals.create", "deals.read"))
        activator = _member(db, organization, ACTIVATOR_PERMISSIONS)
        db.commit()
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        lead = create_lead(db, organization=organization)
        rule = create_active_rule(
            db, user=activator, organization=organization, conditions=[], actions=FOLLOW_UP_ACTIONS
        )
        db.commit()
        payload = valid_deal_payload(
            customer_profile_id=customer.id, property_id=property_record.id, lead_id=lead.id
        )

    app = create_test_app(user=creator)
    app.dependency_overrides[get_current_user_context] = lambda: attested_user_context(
        creator, organization_id=organization.id
    )
    with TestClient(app) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        response = client.post("/api/v1/deals", json=payload)

    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        assert db.get(Deal, UUID(response.json()["id"])) is not None
        execution = db.scalar(select(AutomationExecution).where(AutomationExecution.rule_id == rule.id))
        assert execution.status == AutomationExecution.STATUS_FAILED
        assert execution.action_results[0]["reason_code"] == "target_owner_not_authorized"
    assert follow_up_count(organization.id) == 0


def test_an_inactive_creator_does_not_stop_manual_deal_creation() -> None:
    # The rule's creator left the organization. The action is denied, and the failed execution must not raise
    # from the notification step, which would otherwise roll back the deal creation.
    world = build()
    with SessionLocal() as db:
        creator = db.get(AutomationRule, world.rule_id)
        assert creator.created_by_user_id == world.activator_id
    revoke(world, "activator", "membership")

    summary = run(world)

    assert reason_of(summary) == "activator_not_authorized"
    with SessionLocal() as db:
        assert db.get(Deal, world.deal_id) is not None

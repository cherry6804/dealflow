"""Typed AI tool registry and authorization (DFR1-018).

Tests use the real database, the real permission checks, the real execution gate and the real audit tables. Test-only seams,
each the same as in ``test_ai_gateway.py``:

- readiness, the AI actor key, the AI resource gate and the AI rate decision are patched where a production approval
  is pending. ``test_production_gate_refuses_a_tool_call_without_approvals`` asserts the production denial.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, text

from app.ai_tools import service as tools
from app.ai_tools.definitions import (
    OutputField,
    OutputType,
    ParameterType,
    ToolDefinition,
    ToolParameter,
)
from app.ai_tools.registry import DEFAULT_REGISTRY, ToolRegistrationError, ToolRegistry
from app.ai_tools.service import ToolExecutionError, invoke_tool
from app.auth.dependencies import CurrentUserContext
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.session import SessionLocal
from app.governance import execution_gate
from app.governance.capabilities import AI_MASTER
from app.governance.execution_gate import GateOutcome
from app.governance.service import set_capability_enabled
from tests.governance_helpers import (
    allow_actor_execution_permission,
    allow_organization_entitlements,
    allow_provider_readiness,
)
from tests.test_team_api import create_manager, create_owner_manager

ASSISTANT = "ai.assistant"
FOUND = (OutputField("found", OutputType.BOOLEAN),)
CONTACT_TOOL = "contacts.get"


@pytest.fixture
def world() -> Iterator[SimpleNamespace]:
    """Two organizations. Organization A has a contact. A member of A holds contacts.read and the test-only actor grant."""
    owner_a, org_a = create_owner_manager(permissions=("contacts.read",))
    member_a, member_org = create_manager(permissions=("contacts.read", "governance.consent.read"))
    other_b, org_b = create_owner_manager(permissions=("contacts.read",))
    organizations = {org_a.id, org_b.id, member_org.id}
    with SessionLocal() as db:
        contact = Contact(organization_id=org_a.id, first_name="Ada", last_name="Lovelace",
                          email="ada@example.test", phone="+10000000000", is_active=True)
        db.add(contact)
        db.commit()
        contact_id = contact.id
    with SessionLocal() as db:
        member_contact = Contact(organization_id=member_org.id, first_name="Grace", last_name="Hopper",
                                 email="grace@example.test", phone="+10000000001", is_active=True)
        db.add(member_contact)
        db.commit()
        member_contact_id = member_contact.id
    world = SimpleNamespace(
        owner_a=owner_a, org_a=org_a, member_a=member_a, member_org=member_org,
        other_b=other_b, org_b=org_b, contact_id=contact_id, member_contact_id=member_contact_id,
    )
    yield world
    with SessionLocal() as db:
        for organization_id in organizations:
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
            db.execute(delete(Contact).where(Contact.organization_id == organization_id))
        db.commit()


def _enable_ai(monkeypatch, organization, owner, *, switch: bool = True) -> None:
    allow_organization_entitlements(monkeypatch)
    allow_provider_readiness(monkeypatch)
    allow_actor_execution_permission(monkeypatch, "governance.consent.read")
    monkeypatch.setitem(execution_gate.RATE_EXECUTION_TYPE, ASSISTANT, "ai_tool_test")
    monkeypatch.setattr(execution_gate, "consume_or_deny",
                        lambda db, **kwargs: SimpleNamespace(allowed=True, reason_code="allowed"))
    with SessionLocal() as db:
        for key in (AI_MASTER, ASSISTANT):
            set_capability_enabled(db, organization_id=organization.id, actor_user_id=owner.id,
                                   capability_key=key, is_enabled=switch)
        db.commit()


def _pass_resource(monkeypatch) -> None:
    def passed(db, request, outcomes):
        outcomes.append(GateOutcome(gate="resource", allowed=True, reason_code="allowed_all"))

    monkeypatch.setattr(execution_gate, "_gate_resource", passed)


def _invoke(world, *, user, organization, tool=CONTACT_TOOL, arguments=None, registry=DEFAULT_REGISTRY):
    if arguments is None:
        contact = world.member_contact_id if organization.id == world.member_org.id else world.contact_id
        arguments = {"contact_id": str(contact)}
    with SessionLocal() as db:
        result = invoke_tool(
            db,
            organization_id=organization.id,
            tool_key=tool,
            arguments=arguments,
            user_context=CurrentUserContext(user=user),
            registry=registry,
        )
        db.commit()
    return result


def _audit(organization_id) -> list[AuditEvent]:
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).where(
            AuditEvent.organization_id == organization_id, AuditEvent.event_type == tools.TOOL_AUDIT_EVENT)).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def _counting_registry(handler, *, permission="contacts.read", parameters=(), timeout_ms=2_000) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        key="contacts.probe", description="test tool", capability_key=ASSISTANT,
        required_permission=permission, parameters=parameters, handler=handler, timeout_ms=timeout_ms,
        output_schema=(
            OutputField("text", OutputType.STRING),
            OutputField("n", OutputType.INTEGER, required=False),
            OutputField("when", OutputType.STRING, required=False),
        ),
    ))
    return registry


# --- registry rules -------------------------------------------------------------------------


def test_the_release_registers_exactly_the_approved_read_only_tools() -> None:
    # The approved catalogue: one read tool per CRM area the release exposes. Follow-ups and site visits are not exposed.
    assert DEFAULT_REGISTRY.keys() == (
        "contacts.get",
        "deals.get",
        "leads.get",
        "properties.get",
        "requirements.get",
    )
    definition = DEFAULT_REGISTRY.get(CONTACT_TOOL)
    assert definition is not None and definition.read_only is True
    assert definition.required_permission == "contacts.read"
    assert definition.capability_key == ASSISTANT
    registered = DEFAULT_REGISTRY.keys()
    for key in registered:
        tool = DEFAULT_REGISTRY.get(key)
        assert tool is not None and tool.read_only is True and tool.capability_key == ASSISTANT


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"read_only": False}, "read-only"),
        ({"required_permission": "not.a.real.key"}, "catalogue"),
        ({"capability_key": "deals.create"}, "AI capability"),
        ({"capability_key": "ai.unknown_capability"}, "AI capability"),
        ({"key": "Bad Key"}, "area.action"),
        ({"timeout_ms": 0}, "timeout"),
    ],
)
def test_the_registry_refuses_definitions_that_break_the_rules(changes, message) -> None:
    base = {
        "key": "contacts.probe", "description": "x", "capability_key": ASSISTANT,
        "required_permission": "contacts.read", "parameters": (), "handler": lambda db, o, a: {},
        "output_schema": FOUND,
    }
    registry = ToolRegistry()
    with pytest.raises(ToolRegistrationError, match=message):
        registry.register(ToolDefinition(**{**base, **changes}))


def test_the_registry_refuses_duplicate_keys_and_duplicate_parameters() -> None:
    registry = ToolRegistry()
    definition = ToolDefinition(key="contacts.probe", description="x", capability_key=ASSISTANT,
                                required_permission="contacts.read", parameters=(), handler=lambda db, o, a: {},
                                output_schema=FOUND)
    registry.register(definition)
    with pytest.raises(ToolRegistrationError, match="already registered"):
        registry.register(definition)
    dup = ToolDefinition(key="contacts.dup", description="x", capability_key=ASSISTANT,
                         required_permission="contacts.read",
                         parameters=(ToolParameter("a", ParameterType.STRING), ToolParameter("a", ParameterType.STRING)),
                         handler=lambda db, o, a: {}, output_schema=FOUND)
    with pytest.raises(ToolRegistrationError, match="unique"):
        registry.register(dup)


# --- strict schemas ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"contact_id": str(uuid.uuid4()), "extra": 1},
        {"contact_id": 12},
        {"contact_id": "not-a-uuid"},
        {"contact_id": True},
        {"contact_id": None},
    ],
)
def test_invalid_arguments_are_refused_before_the_tool_or_the_gate_runs(world, monkeypatch, arguments) -> None:
    called = []
    registry = _counting_registry(lambda db, o, a: called.append(1) or {}, parameters=(
        ToolParameter("contact_id", ParameterType.UUID),))
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    result = _invoke(world, user=world.owner_a, organization=world.org_a, tool="contacts.probe",
                     arguments=arguments, registry=registry)
    assert result.outcome == "denied"
    assert result.reason_code == "invalid_arguments"
    assert called == []


def test_integer_and_string_limits_are_enforced() -> None:
    from app.ai_tools.validation import InvalidArgumentsError, validate_arguments

    definition = ToolDefinition(
        key="contacts.probe", description="x", capability_key=ASSISTANT, required_permission="contacts.read",
        parameters=(ToolParameter("count", ParameterType.INTEGER, minimum=1, maximum=5),
                    ToolParameter("label", ParameterType.STRING, max_length=4)),
        handler=lambda db, o, a: {},
    )
    assert validate_arguments(definition, {"count": 3, "label": "ok"}) == {"count": 3, "label": "ok"}
    for bad in ({"count": True, "label": "ok"}, {"count": 0, "label": "ok"}, {"count": 6, "label": "ok"},
                {"count": 1, "label": "toolong"}, {"count": 1, "label": "   "}):
        with pytest.raises(InvalidArgumentsError):
            validate_arguments(definition, bad)


# --- authorization and the gate -----------------------------------------------------------------


def test_a_member_with_the_permission_reads_a_contact_with_minimum_data(world, monkeypatch) -> None:
    _enable_ai(monkeypatch, world.member_org, world.member_a)
    _pass_resource(monkeypatch)
    result = _invoke(world, user=world.member_a, organization=world.member_org)
    assert result.outcome == "succeeded"
    assert result.data == {"found": True, "contact": {"id": str(world.member_contact_id),
                                                       "display_name": "Grace Hopper", "is_active": True}}
    # Personal contact details are not returned to the agent.
    assert "grace@example.test" not in json.dumps(result.data)
    assert "+10000000001" not in json.dumps(result.data)


def test_a_successful_call_writes_linked_requested_and_completed_records(world, monkeypatch) -> None:
    _enable_ai(monkeypatch, world.member_org, world.member_a)
    _pass_resource(monkeypatch)
    result = _invoke(world, user=world.member_a, organization=world.member_org)
    assert result.succeeded
    rows = _audit(world.member_org.id)
    requested = [row for row in rows if row.outcome == "requested"]
    completed = [row for row in rows if row.outcome == "completed"]
    assert len(requested) == 1 and len(completed) == 1
    assert completed[0].causation_id == str(requested[0].id)
    # Argument names and the target identifier only. The argument values are not recorded.
    metadata = json.loads(requested[0].event_metadata)
    assert metadata["argument_names"] == ["contact_id"]
    assert metadata["target_id"] == str(world.member_contact_id)


def test_an_unknown_tool_is_refused_the_same_way_as_a_missing_one(world, monkeypatch) -> None:
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    result = _invoke(world, user=world.member_a, organization=world.member_org, tool="contacts.delete_everything")
    assert result.outcome == "denied"
    assert result.reason_code == "tool_not_registered"


def test_a_member_without_the_tool_permission_is_refused_and_the_tool_does_not_run(world, monkeypatch) -> None:
    called = []
    registry = _counting_registry(lambda db, o, a: called.append(1) or {"found": True})
    user, org = create_manager(permissions=("deals.read",))
    try:
        _enable_ai(monkeypatch, org, user)
        result = _invoke(world, user=user, organization=org, tool="contacts.probe", registry=registry,
                         arguments={})
        assert result.outcome == "denied"
        assert result.reason_code == "permission_denied"
        assert called == []
        assert any(row.outcome == "denied" for row in _audit(org.id))
    finally:
        with SessionLocal() as db:
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == org.id))
            db.commit()


def test_privilege_escalation_through_an_owner_only_tool_is_refused(world, monkeypatch) -> None:
    """A tool that needs an owner-only key cannot be used by a manager, whatever the tool says it needs."""
    called = []
    registry = _counting_registry(lambda db, o, a: called.append(1) or {}, permission="governance.capabilities.manage")
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    result = _invoke(world, user=world.member_a, organization=world.member_org, tool="contacts.probe",
                     registry=registry, arguments={})
    assert result.outcome == "denied"
    assert result.reason_code == "permission_denied"
    assert called == []


def test_a_disabled_capability_stops_the_tool_at_the_gate(world, monkeypatch) -> None:
    _enable_ai(monkeypatch, world.org_a, world.owner_a, switch=False)
    _pass_resource(monkeypatch)
    result = _invoke(world, user=world.member_a, organization=world.member_org)
    assert result.outcome == "denied"
    assert result.reason_code != "ok"


def test_production_gate_refuses_a_tool_call_without_approvals(world, monkeypatch) -> None:
    """Without the test seams: no approved AI actor key, no AI resource store and no AI rate rule. The call is refused."""
    allow_organization_entitlements(monkeypatch)
    allow_provider_readiness(monkeypatch)
    with SessionLocal() as db:
        for key in (AI_MASTER, ASSISTANT):
            set_capability_enabled(db, organization_id=world.member_org.id, actor_user_id=world.member_a.id,
                                   capability_key=key, is_enabled=True)
        db.commit()
    result = _invoke(world, user=world.member_a, organization=world.member_org)
    assert result.outcome == "denied"
    assert result.reason_code == "permission_denied"  # the actor key is not approved yet


# --- tenant isolation ----------------------------------------------------------------------------


def test_another_organizations_contact_looks_the_same_as_a_missing_one(world, monkeypatch) -> None:
    _enable_ai(monkeypatch, world.org_b, world.other_b)
    _pass_resource(monkeypatch)
    cross = _invoke(world, user=world.other_b, organization=world.org_b)
    missing = _invoke(world, user=world.other_b, organization=world.org_b,
                      arguments={"contact_id": str(uuid.uuid4())})
    assert cross.outcome == missing.outcome == "succeeded"
    assert cross.data == missing.data == {"found": False}


def test_a_user_cannot_act_in_an_organization_they_do_not_belong_to(world, monkeypatch) -> None:
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _invoke(world, user=world.other_b, organization=world.org_a)
    assert result.outcome == "denied"
    assert result.reason_code == "permission_denied"
    attempts = [row for row in _audit(world.org_a.id) if row.outcome == "denied"]
    assert attempts, "a cross-tenant attempt must still leave a record"
    assert json.loads(attempts[0].event_metadata)["attempted_user_id"] == str(world.other_b.id)


# --- failure isolation ----------------------------------------------------------------------------


def test_a_database_timeout_is_reported_and_rolled_back_alone(world, monkeypatch) -> None:
    def slow(db, organization_id, arguments):
        db.execute(text("SELECT pg_sleep(1)"))
        return {}

    registry = _counting_registry(slow, timeout_ms=100)
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _invoke(world, user=world.owner_a, organization=world.org_a, tool="contacts.probe",
                     registry=registry, arguments={})
    assert result.outcome == "failed"
    assert result.reason_code == "tool_timeout"
    with SessionLocal() as db:
        assert db.scalar(select(Contact.id).where(Contact.id == world.contact_id)) == world.contact_id


def test_a_controlled_handler_failure_does_not_expose_its_message(world, monkeypatch) -> None:
    def failing(db, organization_id, arguments):
        raise ToolExecutionError("internal detail that must not leak")

    registry = _counting_registry(failing)
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _invoke(world, user=world.owner_a, organization=world.org_a, tool="contacts.probe",
                     registry=registry, arguments={})
    assert result.outcome == "failed"
    assert result.reason_code == "tool_failed"
    assert "internal detail" not in repr(result)


def test_a_database_error_is_reported_as_a_failed_tool(world, monkeypatch) -> None:
    def broken(db, organization_id, arguments):
        db.execute(text("SELECT * FROM a_table_that_does_not_exist"))
        return {}

    registry = _counting_registry(broken)
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _invoke(world, user=world.owner_a, organization=world.org_a, tool="contacts.probe",
                     registry=registry, arguments={})
    assert result.outcome == "failed"
    assert result.reason_code == "tool_failed"


def test_an_oversized_result_is_refused_before_it_is_returned(world, monkeypatch) -> None:
    registry = _counting_registry(lambda db, o, a: {"text": "x" * 20_000})
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _invoke(world, user=world.owner_a, organization=world.org_a, tool="contacts.probe",
                     registry=registry, arguments={})
    assert result.outcome == "failed"
    assert result.reason_code == "result_too_large"
    assert result.data is None


def test_the_tool_result_must_be_plain_json_only(world, monkeypatch) -> None:
    # A datetime is not a JSON primitive, so the output contract refuses it rather than converting it silently.
    registry = _counting_registry(lambda db, o, a: {"when": datetime(2026, 1, 1, tzinfo=UTC), "n": 1})
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _invoke(world, user=world.owner_a, organization=world.org_a, tool="contacts.probe",
                     registry=registry, arguments={})
    assert result.outcome == "failed"
    assert result.reason_code == "output_contract_violation"
    assert result.data is None

"""Exact output contracts, per-tool authorization, initiating-actor attribution and deferred-tool refusal (DFR1-018).

The pure contract tests build tool definitions in memory. The authorization and attribution tests use the real database, the
real permission and membership checks, the real execution gate and the real audit tables, through the ``crm`` fixture of
``test_ai_tools_crm.py``. The only seams are the ones that file already documents.
"""

# ruff: noqa: F401, F811
# The ``crm`` fixture is requested by name in each test, so its import looks redefined to the linter.
from __future__ import annotations

import json
import uuid
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.configuration import ConfigurationError, normalise_configuration
from app.agents.runtime import _execute_step
from app.ai_tools import service as tools
from app.ai_tools.builtin import (
    CONTACT_OUTPUT,
    DEAL_OUTPUT,
    LEAD_OUTPUT,
    PROPERTY_OUTPUT,
    REQUIREMENT_OUTPUT,
)
from app.ai_tools.definitions import (
    MAX_OUTPUT_DEPTH,
    OutputField,
    OutputType,
    ToolDefinition,
)
from app.ai_tools.registry import DEFAULT_REGISTRY, ToolRegistrationError, ToolRegistry
from app.ai_tools.service import AgentInvocation, ToolExecutionError, invoke_tool
from app.ai_tools.validation import OutputContractError, validate_output
from app.auth.dependencies import CurrentUserContext
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.deal import Deal
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.models.property import Property
from app.db.models.user import User
from app.db.session import SessionLocal
from app.governance.capabilities import AI_MASTER
from app.governance.service import set_capability_enabled
from tests.agents_support import config
from tests.test_ai_tools import ASSISTANT, FOUND
from tests.test_ai_tools_crm import (
    SECRET_ADDRESS,
    SECRET_CUSTOMER,
    SECRET_DEAL_NOTE,
    SECRET_EMAIL,
    SECRET_NOTE,
    _assert_no_secrets,
    _other_contact,
    crm,
)
from tests.test_deals_api import create_membership, create_user, grant_permission

S = OutputType.STRING
I = OutputType.INTEGER
B = OutputType.BOOLEAN
O = OutputType.OBJECT

TOOL_TARGETS = {
    "contacts.get": "contact_id",
    "leads.get": "lead_id",
    "requirements.get": "requirement_id",
    "properties.get": "property_id",
    "deals.get": "deal_id",
}
TOOL_PERMISSIONS = {
    "contacts.get": "contacts.read",
    "leads.get": "leads.read",
    "requirements.get": "requirements.read",
    "properties.get": "properties.read",
    "deals.get": "deals.read",
}
DEFERRED_NAMES = (
    "whatsapp.send",
    "messenger.send",
    "instagram.send",
    "telephony.call",
    "voice.call",
    "email.send",
    "sms.send",
    "contacts.call",
    "channel.send",
)


def _definition(handler, *, schema=FOUND, **changes) -> ToolDefinition:
    values = {
        "key": "contacts.probe",
        "description": "test tool",
        "capability_key": ASSISTANT,
        "required_permission": "contacts.read",
        "parameters": (),
        "handler": handler,
        "output_schema": schema,
    }
    values.update(changes)
    return ToolDefinition(**values)


def _validate(schema, data):
    return validate_output(_definition(lambda db, o, a: {}, schema=schema), data)


# --- exact output contracts (pure) ---------------------------------------------------------------

NESTED = (
    OutputField("found", B),
    OutputField(
        "entity",
        O,
        required=False,
        fields=(
            OutputField("id", S),
            OutputField("count", I, required=False, nullable=True),
            OutputField(
                "detail",
                O,
                required=False,
                fields=(OutputField("note", S, nullable=True),),
            ),
            OutputField(
                "tags", OutputType.ARRAY, required=False, items=OutputField("item", S)
            ),
        ),
    ),
)


def test_a_result_that_matches_the_nested_contract_is_returned_as_a_fresh_copy() -> (
    None
):
    data = {
        "found": True,
        "entity": {
            "id": "x",
            "count": None,
            "detail": {"note": None},
            "tags": ["a", "b"],
        },
    }
    checked = _validate(NESTED, data)
    assert checked == data
    assert checked is not data and checked["entity"] is not data["entity"]


def test_optional_objects_and_fields_may_be_absent() -> None:
    assert _validate(NESTED, {"found": False}) == {"found": False}
    assert _validate(NESTED, {"found": True, "entity": {"id": "x"}}) == {
        "found": True,
        "entity": {"id": "x"},
    }


@pytest.mark.parametrize(
    "data, message",
    [
        ({"found": True, "entity": {"id": "x", "secret": "s"}}, "undeclared field"),
        (
            {
                "found": True,
                "entity": {"id": "x", "detail": {"note": "n", "email": "e"}},
            },
            "undeclared field",
        ),
        ({"found": True, "extra": 1}, "undeclared field"),
        ({"found": True, "entity": {"count": 1}}, "entity.id is required"),
        ({"entity": {"id": "x"}}, "found is required"),
        ({"found": True, "entity": {"id": 7}}, "wrong type"),
        ({"found": 1, "entity": {"id": "x"}}, "wrong type"),
        ({"found": True, "entity": {"id": "x", "count": True}}, "wrong type"),
        ({"found": True, "entity": {"id": "x", "count": 1.5}}, "wrong type"),
        ({"found": True, "entity": {"id": None}}, "may not be null"),
        ({"found": True, "entity": ["not", "an", "object"]}, "must be an object"),
        ({"found": True, "entity": {"id": "x", "tags": "a,b"}}, "must be an array"),
        ({"found": True, "entity": {"id": "x", "tags": ["a", 2]}}, "wrong type"),
        ({"found": True, "entity": {"id": "x", "tags": [None]}}, "may not be null"),
        (
            {
                "found": True,
                "entity": {"id": "x", "detail": {"note": {"deep": "structure"}}},
            },
            "wrong type",
        ),
        (
            {"found": True, "entity": {"id": "x", "detail": {"note": ["list"]}}},
            "wrong type",
        ),
        (["not", "an", "object"], "must be an object"),
        ({}, "found is required"),
    ],
)
def test_a_result_outside_the_nested_contract_is_refused(data, message) -> None:
    with pytest.raises(OutputContractError, match=message):
        _validate(NESTED, data)


def test_an_undeclared_nested_array_is_refused_even_when_the_object_is_declared() -> (
    None
):
    schema = (
        OutputField("found", B),
        OutputField("entity", O, fields=(OutputField("id", S),)),
    )
    with pytest.raises(OutputContractError, match="undeclared field"):
        _validate(schema, {"found": True, "entity": {"id": "x", "tags": ["a"]}})


def test_a_result_deeper_than_its_contract_is_refused_and_declared_depth_passes() -> (
    None
):
    schema = (
        OutputField(
            "top",
            O,
            fields=(
                OutputField(
                    "mid",
                    O,
                    fields=(OutputField("low", O, fields=(OutputField("c2", S),)),),
                ),
            ),
        ),
    )
    with pytest.raises(OutputContractError, match="undeclared field"):
        _validate(schema, {"top": {"mid": {"low": {"c2": "x", "deeper": {"y": 1}}}}})
    assert _validate(schema, {"top": {"mid": {"low": {"c2": "x"}}}}) == {
        "top": {"mid": {"low": {"c2": "x"}}}
    }


def deepest_object(levels: int) -> OutputField:
    """An object nested ``levels`` object levels deep, ending in one string field."""
    field = OutputField("leaf", S)
    for index in range(levels):
        field = OutputField(f"level{index}", O, fields=(field,))
    return field


@pytest.mark.parametrize(
    "schema",
    [
        (OutputField("found", B), OutputField("a", O, fields=(deepest_object(4),))),
        (OutputField("arr", OutputType.ARRAY),),
        (OutputField("arr", OutputType.ARRAY, items=OutputField("item", O)),),
        (OutputField("plain", S, fields=(OutputField("x", S),)),),
        (OutputField("plain", S, items=OutputField("x", S)),),
        (OutputField("found", B), OutputField("found", B)),
        (),
    ],
)
def test_the_registry_refuses_output_contracts_that_are_too_deep_or_malformed(
    schema,
) -> None:
    with pytest.raises(ToolRegistrationError):
        ToolRegistry().register(_definition(lambda db, o, a: {}, schema=schema))


def test_the_release_depth_limit_is_three_object_levels() -> None:
    assert MAX_OUTPUT_DEPTH == 3


@pytest.mark.parametrize(
    "schema, data",
    [
        (CONTACT_OUTPUT, {"found": False}),
        (
            CONTACT_OUTPUT,
            {
                "found": True,
                "contact": {"id": "x", "display_name": "A B", "is_active": True},
            },
        ),
        (
            LEAD_OUTPUT,
            {
                "found": True,
                "lead": {
                    "id": "x",
                    "contact_id": "y",
                    "status": "NEW",
                    "interest": None,
                    "outcome": None,
                    "next_action_at": None,
                    "is_active": True,
                },
            },
        ),
        (
            REQUIREMENT_OUTPUT,
            {
                "found": True,
                "requirement": {
                    "id": "x",
                    "status": "ACTIVE",
                    "is_active": True,
                    "budget_min": None,
                    "budget_max": None,
                    "budget_currency": None,
                },
            },
        ),
        (
            PROPERTY_OUTPUT,
            {
                "found": True,
                "property": {
                    "id": "x",
                    "status": None,
                    "transaction_type": None,
                    "property_type": None,
                    "city": None,
                    "locality": None,
                    "bhk": None,
                    "price": None,
                    "currency": None,
                },
            },
        ),
        (
            DEAL_OUTPUT,
            {
                "found": True,
                "deal": {
                    "id": "x",
                    "stage": "NEW",
                    "expected_value": None,
                    "currency": "INR",
                    "property_id": "p",
                    "lead_id": None,
                    "customer_profile_id": "c",
                },
            },
        ),
    ],
)
def test_every_built_in_contract_accepts_its_real_shape_including_nulls(
    schema, data
) -> None:
    assert _validate(schema, data) == data


@pytest.mark.parametrize(
    "schema, entity, field, value",
    [
        (CONTACT_OUTPUT, "contact", "email", "x@example.test"),
        (LEAD_OUTPUT, "lead", "next_action", "private note"),
        (REQUIREMENT_OUTPUT, "requirement", "customer_name", "Name"),
        (PROPERTY_OUTPUT, "property", "address_line_1", "42 Street"),
        (DEAL_OUTPUT, "deal", "notes", "private"),
    ],
)
def test_every_built_in_contract_refuses_a_withheld_field_added_to_its_object(
    schema, entity, field, value
) -> None:
    with pytest.raises(OutputContractError, match="undeclared field"):
        _validate(schema, {"found": True, entity: {"id": "x", field: value}})


# --- exact output contract at invocation -----------------------------------------------------------


def _run(
    crm,
    *,
    tool,
    arguments,
    user=None,
    organization=None,
    registry=DEFAULT_REGISTRY,
    **kwargs,
):
    with SessionLocal() as db:
        result = invoke_tool(
            db,
            organization_id=(organization or crm.org).id,
            tool_key=tool,
            arguments=arguments,
            user_context=CurrentUserContext(user=user or crm.member),
            registry=registry,
            **kwargs,
        )
        db.commit()
    return result


def _audit_rows(organization_id) -> list[AuditEvent]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditEvent).where(
                AuditEvent.organization_id == organization_id,
                AuditEvent.event_type == tools.TOOL_AUDIT_EVENT,
            )
        ).all()
        for row in rows:
            db.expunge(row)
        return list(rows)


def _pair(organization_id) -> tuple[AuditEvent, AuditEvent]:
    """The requested and completed records of one call. The requested record is committed separately, so timestamps do not order them."""
    rows = _audit_rows(organization_id)
    requested = [row for row in rows if row.outcome == "requested"]
    completed = [row for row in rows if row.outcome == "completed"]
    assert len(requested) == 1 and len(completed) == 1
    assert completed[0].causation_id == str(requested[0].id)
    return requested[0], completed[0]


def _enable(crm, *, switch: bool) -> None:
    with SessionLocal() as db:
        for key in (AI_MASTER, ASSISTANT):
            set_capability_enabled(
                db,
                organization_id=crm.org.id,
                actor_user_id=crm.member.id,
                capability_key=key,
                is_enabled=switch,
            )
        db.commit()


def _spied(
    calls: list[str], key: str, *, raises: Exception | None = None, returns=None
) -> ToolRegistry:
    """A registry where every built-in handler records its call. ``key`` may fail or return a fixed result instead."""
    registry = ToolRegistry()
    names = DEFAULT_REGISTRY.keys()
    for name in names:
        original = DEFAULT_REGISTRY.get(name)

        def handler(db, organization_id, arguments, _original=original, _name=name):
            calls.append(_name)
            if _name == key and raises is not None:
                raise raises
            if _name == key and returns is not None:
                return returns
            return _original.handler(db, organization_id, arguments)

        registry.register(replace(original, handler=handler))
    return registry


@pytest.fixture
def scoped_member(crm):
    """Make a member of the member's organization with exactly the permissions a test names."""

    def make(*, permissions: tuple[str, ...]) -> User:
        with SessionLocal() as db:
            organization = db.get(Organization, crm.org.id)
            user = create_user(db)
            membership = create_membership(db, user=user, organization=organization)
            # The actor gate needs the consent permission in every case. Only the tool permission varies per test.
            for permission in (*permissions, "governance.consent.read"):
                grant_permission(db, membership=membership, permission_key=permission)
            db.commit()
            user_id = user.id
        with SessionLocal() as db:
            return db.get(User, user_id)

    return make


@pytest.fixture
def records(crm):
    """One record per tool in the member's organization, and one in another organization: (own id, other id)."""
    with SessionLocal() as db:
        # The crm member holds the other four read permissions; contacts.read is granted here for the contact tool.
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == crm.member.id,
                Membership.organization_id == crm.org.id,
            )
        )
        grant_permission(db, membership=membership, permission_key="contacts.read")
        db.commit()
    with SessionLocal() as db:
        contact = db.scalar(
            select(Contact).where(
                Contact.organization_id == crm.org.id,
                Contact.first_name == SECRET_CUSTOMER,
            )
        )
        other_contact = _other_contact(db, crm.other_org.id)
        other_requirement = CustomerRequirement(
            organization_id=crm.other_org.id, status="ACTIVE", is_active=True
        )
        other_property = Property(
            organization_id=crm.other_org.id,
            status="AVAILABLE",
            transaction_type="SALE",
            property_type="APARTMENT",
            city="Pune",
            locality="Baner",
            bhk=3,
            price=Decimal(1),
            currency="INR",
        )
        db.add_all([other_requirement, other_property])
        db.flush()
        profile = CustomerProfile(
            organization_id=crm.other_org.id,
            contact_id=other_contact.id,
            is_active=True,
        )
        db.add(profile)
        db.flush()
        other_deal = Deal(
            organization_id=crm.other_org.id,
            customer_profile_id=profile.id,
            property_id=other_property.id,
            owner_user_id=crm.other.id,
            stage="NEW",
            expected_value=Decimal(1),
            currency="INR",
        )
        db.add(other_deal)
        db.commit()
        return {
            "contacts.get": (contact.id, other_contact.id),
            "leads.get": (crm.lead, crm.other_lead),
            "requirements.get": (crm.requirement, other_requirement.id),
            "properties.get": (crm.property, other_property.id),
            "deals.get": (crm.deal, other_deal.id),
        }


def _own(records, tool) -> str:
    return str(records[tool][0])


def _other(records, tool) -> str:
    return str(records[tool][1])


@pytest.mark.parametrize("tool", sorted(TOOL_TARGETS))
def test_each_tool_returns_its_declared_shape_for_its_own_record(
    crm, records, tool
) -> None:
    result = _run(crm, tool=tool, arguments={TOOL_TARGETS[tool]: _own(records, tool)})
    assert result.succeeded
    assert result.data["found"] is True
    assert SECRET_EMAIL not in json.dumps(result.data)
    assert SECRET_NOTE not in json.dumps(
        result.data
    ) and SECRET_DEAL_NOTE not in json.dumps(result.data)
    assert SECRET_ADDRESS not in json.dumps(result.data)


# --- per-tool authorization ----------------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(TOOL_TARGETS))
def test_a_record_in_another_organization_is_reported_as_missing_and_its_data_never_returned(
    crm, records, tool
) -> None:
    calls: list[str] = []
    result = _run(
        crm,
        tool=tool,
        arguments={TOOL_TARGETS[tool]: _other(records, tool)},
        registry=_spied(calls, tool),
    )
    assert result.succeeded and result.data == {"found": False}
    assert calls == [tool], "the read runs once, inside the caller's organization"


@pytest.mark.parametrize("tool", sorted(TOOL_TARGETS))
def test_a_user_outside_the_organization_is_refused_before_the_handler_reads_anything(
    crm, records, tool
) -> None:
    calls: list[str] = []
    result = _run(
        crm,
        tool=tool,
        arguments={TOOL_TARGETS[tool]: _own(records, tool)},
        user=crm.other,
        registry=_spied(calls, tool),
    )
    assert (result.outcome, result.reason_code) == ("denied", "permission_denied")
    assert calls == []


@pytest.mark.parametrize("tool", sorted(TOOL_TARGETS))
def test_an_inactive_user_is_refused_before_the_handler_reads_anything(
    crm, records, tool
) -> None:
    calls: list[str] = []
    inactive = SimpleNamespace(id=crm.member.id, is_active=False)
    result = _run(
        crm,
        tool=tool,
        arguments={TOOL_TARGETS[tool]: _own(records, tool)},
        user=inactive,
        registry=_spied(calls, tool),
    )
    assert (result.outcome, result.reason_code) == ("denied", "permission_denied")
    assert calls == []


@pytest.mark.parametrize("tool", sorted(TOOL_TARGETS))
def test_a_member_without_the_tool_own_permission_is_refused_before_the_handler(
    crm, records, scoped_member, tool
) -> None:
    member = scoped_member(
        permissions=tuple(p for name, p in TOOL_PERMISSIONS.items() if name != tool)
    )
    calls: list[str] = []
    result = _run(
        crm,
        tool=tool,
        arguments={TOOL_TARGETS[tool]: _own(records, tool)},
        user=member,
        registry=_spied(calls, tool),
    )
    assert (result.outcome, result.reason_code) == ("denied", "permission_denied")
    assert calls == []


@pytest.mark.parametrize("tool", sorted(TOOL_TARGETS))
def test_a_member_with_only_the_tool_permission_reads_the_record(
    crm, records, scoped_member, tool
) -> None:
    member = scoped_member(permissions=(TOOL_PERMISSIONS[tool],))
    result = _run(
        crm, tool=tool, arguments={TOOL_TARGETS[tool]: _own(records, tool)}, user=member
    )
    assert result.succeeded and result.data["found"] is True


@pytest.mark.parametrize("tool", sorted(TOOL_TARGETS))
def test_a_disabled_ai_capability_stops_each_tool_at_the_gate_before_the_handler(
    crm, records, tool
) -> None:
    calls: list[str] = []
    _enable(crm, switch=False)
    try:
        result = _run(
            crm,
            tool=tool,
            arguments={TOOL_TARGETS[tool]: _own(records, tool)},
            registry=_spied(calls, tool),
        )
    finally:
        _enable(crm, switch=True)
    assert result.outcome == "denied"
    assert calls == []


def test_a_tool_cannot_be_pointed_at_another_tenant_by_an_argument(
    crm, records
) -> None:
    result = _run(
        crm,
        tool="contacts.get",
        arguments={
            "contact_id": _own(records, "contacts.get"),
            "organization_id": str(crm.other_org.id),
        },
    )
    assert (result.outcome, result.reason_code) == ("denied", "invalid_arguments")
    assert _audit_rows(crm.org.id) == []


# --- initiating-actor attribution ----------------------------------------------------------------


def _metadata(row) -> dict:
    return json.loads(row.event_metadata)


def test_a_direct_invocation_records_the_user_tool_version_operation_target_and_correlation(
    crm, records
) -> None:
    result = _run(
        crm, tool="leads.get", arguments={"lead_id": _own(records, "leads.get")}
    )
    assert result.succeeded
    requested, completed = _pair(crm.org.id)
    assert requested.user_id == crm.member.id and completed.user_id == crm.member.id
    assert (requested.outcome, completed.outcome) == ("requested", "completed")
    assert completed.causation_id == str(requested.id)
    assert completed.correlation_id == requested.correlation_id
    meta = _metadata(requested)
    assert (
        meta["tool"] == "leads.get"
        and meta["tool_version"] == 1
        and meta["operation"] == "read"
    )
    assert meta["initiated_by_user_id"] == str(crm.member.id)
    assert meta["target_type"] == "lead" and meta["target_id"] == _own(
        records, "leads.get"
    )
    assert meta["argument_names"] == ["lead_id"]
    assert "agent_id" not in meta and "idempotency_key" not in meta
    done = _metadata(completed)
    assert done["status"] == "succeeded" and done["reason"] == "ok"


def test_an_agent_invocation_keeps_the_initiating_human_and_adds_the_agent_context(
    crm, records
) -> None:
    agent = AgentInvocation(
        agent_id=uuid.uuid4(),
        agent_execution_id=uuid.uuid4(),
        correlation_id="exec-corr-1",
    )
    result = _run(
        crm,
        tool="deals.get",
        arguments={"deal_id": _own(records, "deals.get")},
        agent=agent,
        idempotency_key="tool:exec:0",
    )
    assert result.succeeded
    requested, completed = _pair(crm.org.id)
    assert requested.user_id == crm.member.id
    assert requested.correlation_id == "exec-corr-1" == completed.correlation_id
    meta = _metadata(requested)
    assert meta["initiated_by_user_id"] == str(crm.member.id)
    assert meta["agent_id"] == str(agent.agent_id)
    assert meta["agent_execution_id"] == str(agent.agent_execution_id)
    assert meta["idempotency_key"] == "tool:exec:0"
    assert _metadata(completed)["agent_execution_id"] == str(agent.agent_execution_id)


def test_a_failed_agent_invocation_keeps_its_full_attribution(crm, records) -> None:
    agent = AgentInvocation(
        agent_id=uuid.uuid4(),
        agent_execution_id=uuid.uuid4(),
        correlation_id="exec-corr-2",
    )
    registry = _spied([], "contacts.get", raises=ToolExecutionError("internal detail"))
    result = _run(
        crm,
        tool="contacts.get",
        arguments={"contact_id": _own(records, "contacts.get")},
        registry=registry,
        agent=agent,
        idempotency_key="tool:exec:1",
    )
    assert (result.outcome, result.reason_code) == ("failed", "tool_failed")
    assert "internal detail" not in repr(result)
    _, completed = _pair(crm.org.id)
    done = _metadata(completed)
    assert done["status"] == "failed" and done["reason"] == "tool_failed"
    assert done["initiated_by_user_id"] == str(crm.member.id)
    assert done["agent_execution_id"] == str(agent.agent_execution_id)
    assert done["idempotency_key"] == "tool:exec:1"
    assert completed.decision == "allowed", (
        "the gate allowed the call, so a failure is not recorded as a denial"
    )


def test_an_output_contract_violation_is_audited_as_a_failed_call_with_its_attribution(
    crm, records
) -> None:
    agent = AgentInvocation(
        agent_id=uuid.uuid4(),
        agent_execution_id=uuid.uuid4(),
        correlation_id="exec-corr-3",
    )
    leaking = {
        "found": True,
        "contact": {
            "id": "x",
            "display_name": "A",
            "is_active": True,
            "email": SECRET_EMAIL,
        },
    }
    result = _run(
        crm,
        tool="contacts.get",
        arguments={"contact_id": _own(records, "contacts.get")},
        registry=_spied([], "contacts.get", returns=leaking),
        agent=agent,
    )
    assert (result.outcome, result.reason_code) == (
        "failed",
        "output_contract_violation",
    )
    assert result.data is None and SECRET_EMAIL not in repr(result)
    _, completed = _pair(crm.org.id)
    done = _metadata(completed)
    assert done["reason"] == "output_contract_violation"
    assert done["agent_execution_id"] == str(agent.agent_execution_id)
    assert SECRET_EMAIL not in completed.event_metadata


def test_retries_of_the_same_agent_step_are_linked_by_key_and_each_attempt_is_audited(
    crm, records
) -> None:
    agent = AgentInvocation(
        agent_id=uuid.uuid4(),
        agent_execution_id=uuid.uuid4(),
        correlation_id="exec-corr-4",
    )
    arguments = {"lead_id": _own(records, "leads.get")}
    for _ in range(2):
        assert _run(
            crm,
            tool="leads.get",
            arguments=arguments,
            agent=agent,
            idempotency_key="tool:exec:2",
        ).succeeded
    rows = _audit_rows(crm.org.id)
    requested = [row for row in rows if row.outcome == "requested"]
    completed = [row for row in rows if row.outcome == "completed"]
    assert len(requested) == 2 and len(completed) == 2
    assert {_metadata(row)["idempotency_key"] for row in rows} == {"tool:exec:2"}
    assert {row.correlation_id for row in rows} == {"exec-corr-4"}
    assert {row.causation_id for row in completed} == {
        str(row.id) for row in requested
    }, "each attempt pairs its own records"


def test_a_denied_agent_invocation_by_a_non_member_keeps_the_human_and_the_agent_context(
    crm, records
) -> None:
    agent = AgentInvocation(
        agent_id=uuid.uuid4(),
        agent_execution_id=uuid.uuid4(),
        correlation_id="exec-corr-5",
    )
    result = _run(
        crm,
        tool="contacts.get",
        arguments={"contact_id": _own(records, "contacts.get")},
        user=crm.other,
        agent=agent,
    )
    assert (result.outcome, result.reason_code) == ("denied", "permission_denied")
    (denial,) = [row for row in _audit_rows(crm.org.id) if row.decision == "denied"]
    meta = _metadata(denial)
    assert meta["initiated_by_user_id"] == str(crm.other.id)
    assert meta["attempted_user_id"] == str(crm.other.id)
    assert meta["agent_execution_id"] == str(agent.agent_execution_id)
    assert denial.user_id != crm.other.id, (
        "a non-member's attempt is recorded under the system actor"
    )


def test_a_denied_direct_invocation_by_a_member_is_audited_to_that_member(
    crm, records, scoped_member
) -> None:
    member = scoped_member(permissions=("leads.read",))
    result = _run(
        crm,
        tool="contacts.get",
        arguments={"contact_id": _own(records, "contacts.get")},
        user=member,
    )
    assert result.reason_code == "permission_denied"
    (denial,) = [row for row in _audit_rows(crm.org.id) if row.decision == "denied"]
    assert denial.user_id == member.id
    assert _metadata(denial)["initiated_by_user_id"] == str(member.id)


def test_identifiers_supplied_as_arguments_cannot_change_the_actor_or_tenant(
    crm, records
) -> None:
    for extra in (
        "initiated_by_user_id",
        "user_id",
        "organization_id",
        "agent_id",
        "agent_execution_id",
    ):
        result = _run(
            crm,
            tool="leads.get",
            arguments={"lead_id": _own(records, "leads.get"), extra: str(uuid.uuid4())},
        )
        assert (result.outcome, result.reason_code) == (
            "denied",
            "invalid_arguments",
        ), extra
    assert _audit_rows(crm.org.id) == []


def test_the_audit_trail_holds_identifiers_only_and_no_argument_values(
    crm, records
) -> None:
    _run(
        crm,
        tool="requirements.get",
        arguments={"requirement_id": _own(records, "requirements.get")},
    )
    for row in _audit_rows(crm.org.id):
        _assert_no_secrets(_metadata(row))
        assert (
            SECRET_NOTE not in row.event_metadata
            and SECRET_DEAL_NOTE not in row.event_metadata
        )
        assert SECRET_ADDRESS not in row.event_metadata


# --- deferred communication and voice tools ------------------------------------------------------


@pytest.mark.parametrize("name", DEFERRED_NAMES)
def test_a_deferred_tool_name_is_not_in_the_registry(name) -> None:
    assert DEFAULT_REGISTRY.get(name) is None


@pytest.mark.parametrize(
    "alias",
    [
        "contact.get",
        "Contacts.Get",
        "CONTACTS.GET",
        " contacts.get",
        "contacts.get ",
        "contacts.get/",
        "contacts-get",
        "contacts.get\n",
        "contacts:get",
        "contacts/get",
        "contacts.get;drop",
    ],
)
def test_an_alias_or_a_spelling_variant_is_not_a_registered_tool(
    crm, records, alias
) -> None:
    assert DEFAULT_REGISTRY.get(alias) is None
    result = _run(
        crm, tool=alias, arguments={"contact_id": _own(records, "contacts.get")}
    )
    assert (result.outcome, result.reason_code) == ("denied", "tool_not_registered")


@pytest.mark.parametrize("name", DEFERRED_NAMES)
def test_a_deferred_tool_is_refused_by_direct_service_invocation_and_leaves_no_record(
    crm, records, name
) -> None:
    result = _run(crm, tool=name, arguments={})
    assert (result.outcome, result.reason_code) == ("denied", "tool_not_registered")
    assert _audit_rows(crm.org.id) == []


@pytest.mark.parametrize("name", ["whatsapp.send", "messenger.send", "telephony.call"])
def test_a_deferred_tool_cannot_be_planned_by_an_agent(name) -> None:
    raw = config(tools=[name], steps=[{"kind": "tool", "tool": name, "arguments": {}}])
    with pytest.raises(ConfigurationError):
        normalise_configuration(
            raw, registered_tools=frozenset(DEFAULT_REGISTRY.keys())
        )


@pytest.mark.parametrize("name", ["whatsapp.send", "voice.call"])
def test_an_agent_runtime_tool_step_naming_a_deferred_tool_fails_closed(
    crm, records, name
) -> None:
    execution = SimpleNamespace(
        organization_id=crm.org.id,
        input_values={},
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        correlation_id="exec-corr-deferred",
        tool_calls=0,
    )
    with SessionLocal() as db:
        outcome = _execute_step(
            db,
            execution,
            {"kind": "tool", "tool": name, "arguments": {}},
            index=0,
            outputs={},
            user_context=CurrentUserContext(user=crm.member),
            max_retries=0,
            sleep=lambda seconds: None,
        )
        db.commit()
    assert outcome == ("failed", "tool_not_registered", None)
    assert _audit_rows(crm.org.id) == []


def test_an_agent_runtime_tool_step_runs_a_registered_tool_with_the_execution_context(
    crm, records
) -> None:
    execution = SimpleNamespace(
        organization_id=crm.org.id,
        input_values={},
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        correlation_id="exec-corr-runtime",
        tool_calls=0,
    )
    with SessionLocal() as db:
        status, reason, output = _execute_step(
            db,
            execution,
            {
                "kind": "tool",
                "tool": "contacts.get",
                "arguments": {"contact_id": _own(records, "contacts.get")},
            },
            index=3,
            outputs={},
            user_context=CurrentUserContext(user=crm.member),
            max_retries=0,
            sleep=lambda seconds: None,
        )
        db.commit()
    assert (status, reason) == ("succeeded", None)
    assert output["tool"] == "contacts.get" and output["output"]["found"] is True
    requested, _completed = _pair(crm.org.id)
    meta = _metadata(requested)
    assert requested.user_id == crm.member.id
    assert meta["agent_id"] == str(execution.agent_id)
    assert meta["agent_execution_id"] == str(execution.id)
    assert meta["idempotency_key"] == f"tool:{execution.id}:3"
    assert requested.correlation_id == "exec-corr-runtime"

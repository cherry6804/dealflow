"""Tool contract, versioning, availability and attribution for the typed AI tool registry (DFR1-018).

Builds on ``test_ai_tools.py``: the same real database, permission checks, execution gate and audit tables. These tests cover
the contract rules added in this story: pinned versions, availability, the output contract, deferred channel and voice tools,
and the agent execution identifier carried into every audit record for a call.
"""

# ruff: noqa: F401, F811
# The ``world`` fixture is requested by name in each test, so its import looks redefined to the linter.
from __future__ import annotations

import json
import uuid

import pytest

from app.ai_tools import service as tools
from app.ai_tools.definitions import ToolDefinition
from app.ai_tools.registry import DEFAULT_REGISTRY, ToolRegistrationError, ToolRegistry
from app.ai_tools.service import invoke_tool
from app.ai_tools.validation import OutputContractError, validate_output
from app.auth.dependencies import CurrentUserContext
from app.db.session import SessionLocal
from tests.test_ai_tools import (  # fixture and helpers shared with the registry suite
    ASSISTANT,
    _audit,
    _counting_registry,
    _enable_ai,
    _invoke,
    _pass_resource,
    world,
)

PROBE = "contacts.probe"


def _probe_definition(handler, **changes) -> ToolDefinition:
    values = {
        "key": PROBE,
        "description": "test tool",
        "capability_key": ASSISTANT,
        "required_permission": "contacts.read",
        "parameters": (),
        "handler": handler,
        "output_fields": ("found", "detail"),
    }
    values.update(changes)
    return ToolDefinition(**values)


def _call(world, registry, **kwargs):
    with SessionLocal() as db:
        result = invoke_tool(
            db,
            organization_id=world.org_a.id,
            tool_key=PROBE,
            arguments={},
            user_context=CurrentUserContext(user=world.owner_a),
            registry=registry,
            **kwargs,
        )
        db.commit()
    return result


# --- registry rules for the new contract fields ------------------------------------------------


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"version": 0}, "starts at 1"),
        ({"output_fields": ()}, "output fields"),
        ({"output_fields": ("found", "found")}, "output fields"),
        ({"output_fields": ("Bad Field",)}, "output field name"),
        ({"key": "whatsapp.send"}, "deferred"),
        ({"key": "messenger.reply"}, "deferred"),
        ({"key": "contacts.call"}, "deferred"),
        ({"capability_key": "ai.voice"}, "deferred"),
    ],
)
def test_the_registry_refuses_contract_and_deferred_definitions(
    changes, message
) -> None:
    with pytest.raises(ToolRegistrationError, match=message):
        ToolRegistry().register(_probe_definition(lambda db, o, a: {}, **changes))


def test_every_release_tool_is_versioned_available_and_declares_its_output() -> None:
    keys = DEFAULT_REGISTRY.keys()
    for key in keys:
        definition = DEFAULT_REGISTRY.get(key)
        assert definition is not None
        assert definition.version == 1
        assert definition.available is True
        assert set(definition.output_fields) >= {"found"}


def test_no_deferred_communication_or_voice_tool_is_registered() -> None:
    deferred_areas = {
        "whatsapp",
        "messenger",
        "instagram",
        "telephony",
        "voice",
        "sms",
        "email",
        "call",
        "channel",
    }
    keys = DEFAULT_REGISTRY.keys()
    for key in keys:
        assert key.split(".", 1)[0] not in deferred_areas
        assert DEFAULT_REGISTRY.get(key).capability_key != "ai.voice"


# --- output contract -------------------------------------------------------------------------


def test_output_must_hold_only_declared_fields_and_primitives() -> None:
    definition = _probe_definition(lambda db, o, a: {})
    assert validate_output(definition, {"found": False}) == {"found": False}
    assert validate_output(
        definition, {"found": True, "detail": {"a": 1, "b": None, "c": True}}
    )
    for bad in (
        {},
        {"found": True, "secret": "x"},
        {"found": True, "detail": {"nested": {"deeper": 1}}},
        {"found": True, "detail": [1, 2]},
        {"found": True, "detail": object()},
        ["not", "an", "object"],
    ):
        with pytest.raises(OutputContractError):
            validate_output(definition, bad)


def test_a_result_with_an_undeclared_field_is_refused_and_not_returned(
    world, monkeypatch
) -> None:
    registry = ToolRegistry()
    registry.register(
        _probe_definition(
            lambda db, o, a: {"found": True, "leaked_email": "ada@example.test"}
        )
    )
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _call(world, registry)
    assert result.outcome == "failed"
    assert result.reason_code == "output_contract_violation"
    assert result.data is None
    assert "ada@example.test" not in repr(result)
    completed = [row for row in _audit(world.org_a.id) if row.outcome == "completed"]
    assert (
        completed
        and json.loads(completed[-1].event_metadata)["reason"]
        == "output_contract_violation"
    )


def test_a_built_in_tool_returns_its_declared_shape_for_a_missing_record(
    world, monkeypatch
) -> None:
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _invoke(
        world,
        user=world.owner_a,
        organization=world.org_a,
        arguments={"contact_id": str(uuid.uuid4())},
    )
    assert result.succeeded
    assert result.data == {"found": False}


# --- versions and availability ---------------------------------------------------------------


def test_a_pinned_version_that_differs_from_the_current_one_is_refused_before_the_handler(
    world, monkeypatch
) -> None:
    calls: list[int] = []

    def handler(db, o, a):
        calls.append(1)
        return {"found": True}

    registry = ToolRegistry()
    registry.register(_probe_definition(handler))
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _call(world, registry, tool_version=2)
    assert result.outcome == "denied"
    assert result.reason_code == "unsupported_tool_version"
    assert calls == []


def test_the_current_pinned_version_runs(world, monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(_probe_definition(lambda db, o, a: {"found": True}))
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    result = _call(world, registry, tool_version=1)
    assert result.succeeded


def test_an_unavailable_tool_is_refused_before_the_gate_and_the_handler(
    world, monkeypatch
) -> None:
    calls: list[int] = []

    def handler(db, o, a):
        calls.append(1)
        return {"found": True}

    registry = ToolRegistry()
    registry.register(_probe_definition(handler, available=False))
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    before = len(_audit(world.org_a.id))
    result = _call(world, registry)
    assert result.outcome == "denied"
    assert result.reason_code == "tool_unavailable"
    assert calls == []
    assert len(_audit(world.org_a.id)) == before


# --- attribution ------------------------------------------------------------------------------


def test_the_agent_execution_identifier_is_carried_into_the_requested_and_completed_records(
    world, monkeypatch
) -> None:
    registry = ToolRegistry()
    registry.register(_probe_definition(lambda db, o, a: {"found": True}))
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    execution_id = uuid.uuid4()
    result = _call(world, registry, agent_execution_id=execution_id)
    assert result.succeeded
    rows = [
        row for row in _audit(world.org_a.id) if row.action == tools.TOOL_INVOKE_ACTION
    ]
    assert len(rows) == 2
    for row in rows:
        metadata = json.loads(row.event_metadata)
        assert metadata["tool"] == PROBE
        assert metadata["tool_version"] == 1
        assert metadata["agent_execution_id"] == str(execution_id)
    requested = next(row for row in rows if row.outcome == "requested")
    completed = next(row for row in rows if row.outcome == "completed")
    assert completed.causation_id == str(requested.id)
    assert completed.correlation_id == requested.correlation_id


def test_a_permission_denial_inside_an_agent_run_keeps_the_execution_identifier(
    world, monkeypatch
) -> None:
    registry = _counting_registry(lambda db, o, a: {"found": True})
    _enable_ai(monkeypatch, world.org_a, world.owner_a)
    _pass_resource(monkeypatch)
    execution_id = uuid.uuid4()
    with SessionLocal() as db:
        result = invoke_tool(
            db,
            organization_id=world.org_a.id,
            tool_key=PROBE,
            arguments={},
            user_context=CurrentUserContext(user=world.member_a),
            registry=registry,
            agent_execution_id=execution_id,
        )
        db.commit()
    assert result.reason_code == "permission_denied"
    denials = [row for row in _audit(world.org_a.id) if row.decision == "denied"]
    assert denials and json.loads(denials[-1].event_metadata)[
        "agent_execution_id"
    ] == str(execution_id)


def test_the_built_in_tool_list_is_unchanged_by_the_contract_work() -> None:
    assert set(DEFAULT_REGISTRY.keys()) == {
        "contacts.get",
        "deals.get",
        "leads.get",
        "properties.get",
        "requirements.get",
    }

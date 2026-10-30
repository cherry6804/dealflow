"""Capability policy engine: defaults, hierarchy, fail-closed gates and tenant isolation."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.session import SessionLocal
from app.governance.capabilities import (
    AI_MASTER,
    AUTOMATION_DEAL_CREATED_RULES,
    AUTOMATION_MASTER,
    CAPABILITY_BY_KEY,
    ancestry,
)
from app.governance.policy import (
    REASON_ALLOWED,
    REASON_CAPABILITY_DISABLED,
    REASON_MASTER_DISABLED,
    REASON_PROVIDER_NOT_CONNECTED,
    REASON_UNKNOWN_CAPABILITY,
    evaluate_capability,
)
from app.governance.service import set_capability_enabled
from tests.governance_helpers import attested_user_context
from tests.test_team_api import create_manager


@pytest.fixture
def tenant() -> Iterator[tuple[UUID, UUID]]:
    """Yield (organization_id, actor_user_id) for a fresh organization."""
    user, organization = create_manager(permissions=())
    yield organization.id, user.id
    with SessionLocal() as db:
        db.execute(
            delete(OrganizationCapabilitySetting).where(
                OrganizationCapabilitySetting.organization_id == organization.id
            )
        )
        db.commit()


def _set(tenant: tuple[UUID, UUID], key: str, enabled: bool) -> None:
    organization_id, actor_user_id = tenant
    with SessionLocal() as db:
        set_capability_enabled(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            capability_key=key,
            is_enabled=enabled,
        )
        db.commit()


def _decide(organization_id: UUID, key: str):
    # These tests exercise the switches. The entitlement is satisfied by an attested snapshot
    # for the same organization, so only the switch decides the outcome.
    context = attested_user_context(SimpleNamespace(id=uuid4()), organization_id=organization_id)
    with SessionLocal() as db:
        return evaluate_capability(
            db, organization_id=organization_id, capability_key=key, user_context=context
        )


def test_every_capability_is_disabled_by_default(tenant) -> None:
    organization_id, _ = tenant

    for key in CAPABILITY_BY_KEY:
        decision = _decide(organization_id, key)
        assert decision.allowed is False, key
        assert decision.reason_code in {REASON_MASTER_DISABLED, REASON_CAPABILITY_DISABLED}, key


def test_unknown_capability_fails_closed(tenant) -> None:
    organization_id, _ = tenant

    decision = _decide(organization_id, "ai.does_not_exist")

    assert decision.allowed is False
    assert decision.reason_code == REASON_UNKNOWN_CAPABILITY


def test_child_stays_denied_while_its_master_is_off(tenant) -> None:
    organization_id, _ = tenant
    _set(tenant, AUTOMATION_DEAL_CREATED_RULES, True)

    decision = _decide(organization_id, AUTOMATION_DEAL_CREATED_RULES)

    assert decision.allowed is False
    assert decision.reason_code == REASON_MASTER_DISABLED


def test_master_and_capability_on_allows_a_capability_with_no_extra_gates(tenant) -> None:
    organization_id, _ = tenant
    _set(tenant, AUTOMATION_MASTER, True)
    _set(tenant, AUTOMATION_DEAL_CREATED_RULES, True)

    decision = _decide(organization_id, AUTOMATION_DEAL_CREATED_RULES)

    assert decision.allowed is True
    assert decision.reason_code == REASON_ALLOWED
    assert decision.policy_version >= 1


def test_disabling_the_master_blocks_its_children_immediately(tenant) -> None:
    organization_id, _ = tenant
    _set(tenant, AUTOMATION_MASTER, True)
    _set(tenant, AUTOMATION_DEAL_CREATED_RULES, True)
    assert _decide(organization_id, AUTOMATION_DEAL_CREATED_RULES).allowed is True

    _set(tenant, AUTOMATION_MASTER, False)

    decision = _decide(organization_id, AUTOMATION_DEAL_CREATED_RULES)
    assert decision.allowed is False
    assert decision.reason_code == REASON_MASTER_DISABLED


def test_ai_capability_fails_closed_without_a_provider(tenant) -> None:
    organization_id, _ = tenant
    _set(tenant, AI_MASTER, True)
    _set(tenant, "ai.assistant", True)

    decision = _decide(organization_id, "ai.assistant")

    assert decision.allowed is False
    assert decision.reason_code == REASON_PROVIDER_NOT_CONNECTED


def test_channel_capability_fails_closed_without_a_provider(tenant) -> None:
    organization_id, _ = tenant
    _set(tenant, "channels.email", True)

    decision = _decide(organization_id, "channels.email")

    assert decision.allowed is False
    assert decision.reason_code == REASON_PROVIDER_NOT_CONNECTED


def test_policy_version_increases_on_every_change(tenant) -> None:
    organization_id, _ = tenant
    _set(tenant, AUTOMATION_MASTER, True)
    first = _decide(organization_id, AUTOMATION_MASTER).policy_version

    _set(tenant, AUTOMATION_MASTER, False)
    second = _decide(organization_id, AUTOMATION_MASTER).policy_version

    assert second == first + 1


def test_enablement_is_scoped_to_one_organization(tenant) -> None:
    _set(tenant, AUTOMATION_MASTER, True)
    _set(tenant, AUTOMATION_DEAL_CREATED_RULES, True)
    _, other_organization = create_manager(permissions=())

    decision = _decide(other_organization.id, AUTOMATION_DEAL_CREATED_RULES)

    assert decision.allowed is False
    assert decision.reason_code == REASON_MASTER_DISABLED


def test_ancestry_runs_from_master_to_capability() -> None:
    chain = ancestry(CAPABILITY_BY_KEY[AUTOMATION_DEAL_CREATED_RULES])

    assert [item.key for item in chain] == [AUTOMATION_MASTER, AUTOMATION_DEAL_CREATED_RULES]

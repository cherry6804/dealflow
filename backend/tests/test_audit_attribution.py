"""Trusted audit attribution: the writer verifies organization and actor before it writes (WS6 WP3 hardening).

Runs on PostgreSQL. Each refusal case asserts two things: the writer raises ``AuditAttributionError``, and no
audit row is written for the organization the attribution claimed. Valid attributions and allowlisted system
actors must still write, and the requested/completed lifecycle and idempotency must be unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update

from app.audit.attribution import (
    SYSTEM_ACTORS,
    AuditAttribution,
    AuditAttributionError,
    system_attribution,
    user_attribution,
)
from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_DENIED,
    OUTCOME_REQUESTED,
    persist_independent_audit_event,
)
from app.auth.dependencies import CurrentUserContext
from app.db.models.audit_event import AuditEvent
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.models.organization_capability_setting import OrganizationCapabilitySetting
from app.db.session import SessionLocal
from app.governance.ai_execution import require_ai_execution
from app.governance.capabilities import AI_MASTER, AUTOMATION_MASTER
from app.governance.service import set_capability_enabled
from tests.test_team_api import create_manager

EVENT_TYPE = "governance"
ACTION = "test.attribution"


def _cleanup(*organization_ids: UUID) -> None:
    with SessionLocal() as db:
        for organization_id in organization_ids:
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
            db.execute(delete(OrganizationCapabilitySetting).where(
                OrganizationCapabilitySetting.organization_id == organization_id))
        db.commit()


@pytest.fixture
def tenants() -> Iterator[dict]:
    """Two organizations, each with one member. Their members are not members of the other."""
    member_a, org_a = create_manager(permissions=("governance.capabilities.manage",))
    member_b, org_b = create_manager(permissions=("governance.capabilities.manage",))
    yield {
        "org_a": org_a.id,
        "member_a": member_a.id,
        "org_b": org_b.id,
        "member_b": member_b.id,
    }
    _cleanup(org_a.id, org_b.id)


def _rows(organization_id: UUID) -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(AuditEvent).where(AuditEvent.organization_id == organization_id)).all())


def _write(attribution: AuditAttribution, *, action: str = ACTION, outcome: str = OUTCOME_REQUESTED,
           idempotency_key: str | None = None) -> AuditEvent:
    return persist_independent_audit_event(
        SessionLocal(),
        attribution=attribution,
        event_type=EVENT_TYPE,
        action=action,
        decision="allowed",
        outcome=outcome,
        idempotency_key=idempotency_key,
    )


# --- Valid attributions -------------------------------------------------------------------------


def test_a_matching_user_and_organization_are_recorded_exactly(tenants) -> None:
    row = _write(user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"]))

    assert row.organization_id == tenants["org_a"]
    assert row.user_id == tenants["member_a"]
    stored = _rows(tenants["org_a"])
    assert [item.id for item in stored] == [row.id]


def test_a_system_actor_writes_without_a_user_when_the_organization_is_valid(tenants) -> None:
    row = _write(system_attribution(organization_id=tenants["org_a"], system_actor="ai_execution_gate"))

    assert row.user_id is None
    assert row.organization_id == tenants["org_a"]
    assert len(_rows(tenants["org_a"])) == 1


# --- Refusals: mismatched, forged and cross-tenant attribution -----------------------------------


def test_a_user_claimed_in_an_organization_they_do_not_belong_to_is_refused(tenants) -> None:
    # Member A is real, but is not a member of organization B.
    with pytest.raises(AuditAttributionError):
        _write(user_attribution(organization_id=tenants["org_b"], actor_user_id=tenants["member_a"]))
    assert _rows(tenants["org_b"]) == []


def test_a_forged_user_identity_is_refused(tenants) -> None:
    forged = uuid4()
    with pytest.raises(AuditAttributionError):
        _write(user_attribution(organization_id=tenants["org_a"], actor_user_id=forged))
    assert _rows(tenants["org_a"]) == []


def test_a_cross_tenant_attribution_into_another_organization_is_refused(tenants) -> None:
    # Member B is a real member of organization B. Claiming organization A for them must fail.
    with pytest.raises(AuditAttributionError):
        _write(user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_b"]))
    assert _rows(tenants["org_a"]) == []
    assert _rows(tenants["org_b"]) == []


def test_an_inactive_membership_is_refused(tenants) -> None:
    with SessionLocal() as db:
        db.execute(update(Membership).where(
            Membership.user_id == tenants["member_a"],
            Membership.organization_id == tenants["org_a"],
        ).values(is_active=False))
        db.commit()
    try:
        with pytest.raises(AuditAttributionError):
            _write(user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"]))
        assert _rows(tenants["org_a"]) == []
    finally:
        with SessionLocal() as db:
            db.execute(update(Membership).where(
                Membership.user_id == tenants["member_a"],
                Membership.organization_id == tenants["org_a"],
            ).values(is_active=True))
            db.commit()


def test_an_inactive_organization_is_refused_even_for_a_member(tenants) -> None:
    with SessionLocal() as db:
        db.execute(update(Organization).where(Organization.id == tenants["org_a"]).values(is_active=False))
        db.commit()
    try:
        with pytest.raises(AuditAttributionError):
            _write(user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"]))
        with pytest.raises(AuditAttributionError):
            _write(system_attribution(organization_id=tenants["org_a"], system_actor="ai_execution_gate"))
        assert _rows(tenants["org_a"]) == []
    finally:
        with SessionLocal() as db:
            db.execute(update(Organization).where(Organization.id == tenants["org_a"]).values(is_active=True))
            db.commit()


def test_an_unknown_organization_is_refused_for_a_system_actor_too(tenants) -> None:
    unknown = uuid4()
    with pytest.raises(AuditAttributionError):
        _write(system_attribution(organization_id=unknown, system_actor="ai_execution_gate"))
    assert _rows(unknown) == []


def test_a_refused_attribution_does_not_block_a_later_valid_write(tenants) -> None:
    with pytest.raises(AuditAttributionError):
        _write(user_attribution(organization_id=tenants["org_a"], actor_user_id=uuid4()))
    row = _write(user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"]))
    assert [item.id for item in _rows(tenants["org_a"])] == [row.id]


# --- Attribution objects reject malformed input --------------------------------------------------


def test_an_attribution_must_name_exactly_one_actor(tenants) -> None:
    with pytest.raises(ValueError):
        AuditAttribution(organization_id=tenants["org_a"])
    with pytest.raises(ValueError):
        AuditAttribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"], system_actor="ai_execution_gate")


def test_an_unlisted_system_actor_is_rejected_before_any_write(tenants) -> None:
    with pytest.raises(ValueError):
        system_attribution(organization_id=tenants["org_a"], system_actor="caller_supplied")
    assert _rows(tenants["org_a"]) == []
    assert SYSTEM_ACTORS == frozenset({"ai_execution_gate", "automation_rate_limit"})


# --- End to end: governed operations inherit the verification ------------------------------------


def test_a_governed_change_with_a_forged_actor_changes_nothing(tenants) -> None:
    with SessionLocal() as db:
        with pytest.raises(AuditAttributionError):
            set_capability_enabled(db, organization_id=tenants["org_a"], actor_user_id=uuid4(),
                                   capability_key=AUTOMATION_MASTER, is_enabled=True)
        db.rollback()
    with SessionLocal() as db:
        assert db.scalar(select(OrganizationCapabilitySetting.id).where(
            OrganizationCapabilitySetting.organization_id == tenants["org_a"])) is None
    assert _rows(tenants["org_a"]) == []


def test_a_denial_for_a_user_outside_the_organization_is_refused_not_recorded(tenants) -> None:
    # The user context names member A, but the request is for organization B. The denial cannot be
    # attributed to B, so it is refused. The denial is not written, and the refusal is reported.
    user_context = CurrentUserContext(user=_user(tenants["member_a"]))
    with SessionLocal() as db, pytest.raises(AuditAttributionError):
        require_ai_execution(db, organization_id=tenants["org_b"], capability_key=AI_MASTER,
                             user_context=user_context)
    assert _rows(tenants["org_b"]) == []


def test_a_denial_without_a_user_is_recorded_as_a_system_action(tenants) -> None:
    from app.governance.ai_execution import AiExecutionDenied

    with SessionLocal() as db:
        with pytest.raises(AiExecutionDenied):
            require_ai_execution(db, organization_id=tenants["org_a"], capability_key=AI_MASTER)
        db.rollback()
    denials = [row for row in _rows(tenants["org_a"]) if row.outcome == OUTCOME_DENIED]
    assert len(denials) == 1
    assert denials[0].user_id is None


# --- Existing guarantees still hold with verification in place -----------------------------------


def test_repeated_keys_still_return_the_stored_row(tenants) -> None:
    attribution = user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"])
    first = _write(attribution, idempotency_key="verified-key", outcome=OUTCOME_COMPLETED)
    second = _write(attribution, idempotency_key="verified-key", outcome=OUTCOME_COMPLETED)
    assert first.id == second.id
    assert len([row for row in _rows(tenants["org_a"]) if row.idempotency_key == "verified-key"]) == 1


def test_the_requested_row_survives_rollback_for_a_verified_actor(tenants) -> None:
    attribution = user_attribution(organization_id=tenants["org_a"], actor_user_id=tenants["member_a"])
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=tenants["org_a"], actor_user_id=tenants["member_a"],
                               capability_key=AUTOMATION_MASTER, is_enabled=True)
        db.rollback()
    rows = _rows(tenants["org_a"])
    assert [row.outcome for row in rows] == [OUTCOME_REQUESTED]
    assert rows[0].user_id == attribution.actor_user_id


def _user(user_id: UUID):
    from app.db.models.user import User

    with SessionLocal() as db:
        return db.get(User, user_id)

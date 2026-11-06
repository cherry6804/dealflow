"""Read-only CRM tools for AI agents: data minimisation, tenant isolation, authorization and audit (DFR1-018).

These tests use the real database, the real permission and membership checks, the real execution gate and the real audit tables.
Only the same seams as ``test_ai_tools.py`` are used: entitlement, readiness, the actor key, the resource gate and the rate decision.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.ai_tools import service as tools
from app.ai_tools.registry import DEFAULT_REGISTRY
from app.ai_tools.service import invoke_tool
from app.auth.dependencies import CurrentUserContext
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.deal import Deal
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.models.property import Property
from app.db.session import SessionLocal
from app.governance import execution_gate
from app.governance.capabilities import AI_MASTER
from app.governance.service import set_capability_enabled
from tests.governance_helpers import (
    allow_actor_execution_permission,
    allow_organization_entitlements,
    allow_provider_readiness,
)
from tests.test_deals_api import create_membership, create_user, grant_permission
from tests.test_team_api import create_manager

ASSISTANT = "ai.assistant"
SECRET_NOTE = "PRIVATE-NEXT-ACTION-NOTE"
SECRET_DEAL_NOTE = "PRIVATE-DEAL-NOTE"
SECRET_CUSTOMER = "Secret Customer Name"
SECRET_EMAIL = "secret.customer@example.test"
SECRET_ADDRESS = "42 Hidden Street"


@pytest.fixture
def crm(monkeypatch) -> Iterator[SimpleNamespace]:
    """One organization with one record of each kind, containing values that must never leave the tool, plus a second organization."""
    member, org = create_manager(permissions=("leads.read", "requirements.read", "properties.read", "deals.read",
                                              "governance.consent.read"))
    other, other_org = create_manager(permissions=("leads.read", "requirements.read", "properties.read", "deals.read"))
    allow_organization_entitlements(monkeypatch)
    allow_provider_readiness(monkeypatch)
    allow_actor_execution_permission(monkeypatch, "governance.consent.read")
    monkeypatch.setitem(execution_gate.RATE_EXECUTION_TYPE, ASSISTANT, "ai_tool_crm_test")
    monkeypatch.setattr(execution_gate, "consume_or_deny",
                        lambda db, **kwargs: SimpleNamespace(allowed=True, reason_code="allowed"))

    def passed(db, request, outcomes):
        from app.governance.execution_gate import GateOutcome
        outcomes.append(GateOutcome(gate="resource", allowed=True, reason_code="allowed_all"))

    monkeypatch.setattr(execution_gate, "_gate_resource", passed)
    with SessionLocal() as db:
        for key in (AI_MASTER, ASSISTANT):
            set_capability_enabled(db, organization_id=org.id, actor_user_id=member.id, capability_key=key, is_enabled=True)
        db.commit()

    ids = {}
    with SessionLocal() as db:
        contact = Contact(organization_id=org.id, first_name=SECRET_CUSTOMER, last_name="Test", email=SECRET_EMAIL,
                          phone="+10000000002", is_active=True)
        db.add(contact)
        db.flush()
        lead = Lead(organization_id=org.id, contact_id=contact.id, status="QUALIFIED", interest="HIGH", is_active=True,
                    next_action=SECRET_NOTE, next_action_at=datetime(2030, 1, 2, 10, tzinfo=UTC))
        requirement = CustomerRequirement(organization_id=org.id, status="ACTIVE", is_active=True,
                                          budget_min=Decimal(5000000), budget_max=Decimal(9000000),
                                          budget_currency="INR")
        property_record = Property(organization_id=org.id, status="AVAILABLE", transaction_type="SALE",
                                   property_type="APARTMENT", city="Bengaluru", locality="Whitefield", bhk=2,
                                   price=Decimal(9500000), currency="INR", address_line_1=SECRET_ADDRESS)
        profile = CustomerProfile(organization_id=org.id, contact_id=contact.id, is_active=True)
        db.add_all([lead, requirement, property_record, profile])
        db.flush()
        deal = Deal(organization_id=org.id, customer_profile_id=profile.id, property_id=property_record.id,
                    lead_id=lead.id, owner_user_id=member.id, stage="NEGOTIATION", expected_value=Decimal(9500000),
                    currency="INR", notes=SECRET_DEAL_NOTE)
        db.add(deal)
        db.flush()
        ids.update(lead=lead.id, requirement=requirement.id, property=property_record.id, deal=deal.id)
        other_lead = Lead(organization_id=other_org.id, contact_id=_other_contact(db, other_org.id).id, status="NEW",
                          interest="LOW", is_active=True)
        db.add(other_lead)
        db.commit()
        ids["other_lead"] = other_lead.id

    yield SimpleNamespace(member=member, org=org, other=other, other_org=other_org, **ids)

    with SessionLocal() as db:
        for organization_id in {org.id, other_org.id}:
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
            db.execute(delete(Deal).where(Deal.organization_id == organization_id))
            db.execute(delete(Lead).where(Lead.organization_id == organization_id))
            db.execute(delete(CustomerRequirement).where(CustomerRequirement.organization_id == organization_id))
            db.execute(delete(Property).where(Property.organization_id == organization_id))
            db.execute(delete(CustomerProfile).where(CustomerProfile.organization_id == organization_id))
            db.execute(delete(Contact).where(Contact.organization_id == organization_id))
        db.commit()


def _other_contact(db, organization_id) -> Contact:
    contact = Contact(organization_id=organization_id, first_name="Other", last_name="Customer", is_active=True)
    db.add(contact)
    db.flush()
    return contact


def _call(crm, *, tool: str, arguments: dict, user=None, organization=None):
    with SessionLocal() as db:
        result = invoke_tool(
            db,
            organization_id=(organization or crm.org).id,
            tool_key=tool,
            arguments=arguments,
            user_context=CurrentUserContext(user=user or crm.member),
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


def _assert_no_secrets(data) -> None:
    text = json.dumps(data)
    for secret in (SECRET_NOTE, SECRET_DEAL_NOTE, SECRET_CUSTOMER, SECRET_EMAIL, SECRET_ADDRESS, "+1000"):
        assert secret not in text


# --- valid reads and data minimisation ----------------------------------------------------------


def test_each_read_tool_returns_only_its_minimum_fields(crm):
    lead = _call(crm, tool="leads.get", arguments={"lead_id": str(crm.lead)})
    assert lead.succeeded and set(lead.data["lead"]) == {
        "id", "contact_id", "status", "interest", "outcome", "next_action_at", "is_active"}
    requirement = _call(crm, tool="requirements.get", arguments={"requirement_id": str(crm.requirement)})
    assert requirement.succeeded and set(requirement.data["requirement"]) == {
        "id", "status", "is_active", "budget_min", "budget_max", "budget_currency"}
    assert requirement.data["requirement"]["budget_max"] == "9000000.00"
    prop = _call(crm, tool="properties.get", arguments={"property_id": str(crm.property)})
    assert prop.succeeded and set(prop.data["property"]) == {
        "id", "status", "transaction_type", "property_type", "city", "locality", "bhk", "price", "currency"}
    deal = _call(crm, tool="deals.get", arguments={"deal_id": str(crm.deal)})
    assert deal.succeeded and set(deal.data["deal"]) == {
        "id", "stage", "expected_value", "currency", "property_id", "lead_id", "customer_profile_id"}
    for result in (lead, requirement, prop, deal):
        _assert_no_secrets(result.data)


# --- invalid arguments and model-supplied identity --------------------------------------------


def test_a_tenant_claim_or_unknown_argument_is_refused_before_any_read(crm):
    result = _call(crm, tool="leads.get", arguments={"lead_id": str(crm.lead), "organization_id": str(crm.other_org.id)})
    assert (result.outcome, result.reason_code) == ("denied", "invalid_arguments")
    assert result.data is None
    malformed = _call(crm, tool="deals.get", arguments={"deal_id": "not-a-uuid"})
    assert malformed.reason_code == "invalid_arguments"


def test_an_unregistered_name_is_refused_the_same_way_as_before(crm):
    assert _call(crm, tool="deals.delete", arguments={"deal_id": str(crm.deal)}).reason_code == "tool_not_registered"


def test_write_style_names_are_not_in_the_catalogue():
    registered = DEFAULT_REGISTRY.keys()
    for key in registered:
        assert not key.endswith((".create", ".update", ".delete", ".close", ".send"))


# --- tenant isolation -----------------------------------------------------------------------------


def test_another_organizations_record_looks_exactly_like_a_missing_one(crm):
    other = _call(crm, tool="leads.get", arguments={"lead_id": str(crm.other_lead)})
    missing = _call(crm, tool="leads.get", arguments={"lead_id": str(uuid.uuid4())})
    assert other.succeeded and missing.succeeded
    assert other.data == missing.data == {"found": False}


def test_a_user_cannot_read_through_an_organization_they_do_not_belong_to(crm):
    # The outsider holds the permission in their own organization only. Here they name this organization.
    result = _call(crm, tool="deals.get", arguments={"deal_id": str(crm.deal)}, user=crm.other, organization=crm.org)
    assert (result.outcome, result.reason_code) == ("denied", "permission_denied")
    assert result.data is None


# --- authorization, membership and gate --------------------------------------------------------------


def test_a_member_without_the_tool_permission_is_refused_and_the_read_does_not_run(crm):
    with SessionLocal() as db:
        member = create_user(db)
        membership = create_membership(db, user=member, organization=db.get(Organization, crm.org.id))
        grant_permission(db, membership=membership, permission_key="contacts.read")
        db.commit()
        member_id = member.id
    result = _call(crm, tool="leads.get", arguments={"lead_id": str(crm.lead)}, user=_user(member_id))
    assert (result.outcome, result.reason_code) == ("denied", "permission_denied")
    denials = [row for row in _audit(crm.org.id) if row.decision == "denied"]
    assert denials, "the refused attempt must be audited"


def test_a_revoked_membership_is_refused_and_the_attempt_is_audited_under_the_system_actor(crm):
    with SessionLocal() as db:
        membership = db.scalar(select(Membership).where(Membership.user_id == crm.member.id,
                                                         Membership.organization_id == crm.org.id))
        membership.is_active = False
        db.commit()
    try:
        result = _call(crm, tool="deals.get", arguments={"deal_id": str(crm.deal)})
        assert (result.outcome, result.reason_code) == ("denied", "permission_denied")
        denial = [row for row in _audit(crm.org.id) if row.decision == "denied"][-1]
        metadata = json.loads(denial.event_metadata)
        assert metadata["attempted_user_id"] == str(crm.member.id)
    finally:
        with SessionLocal() as db:
            membership = db.scalar(select(Membership).where(Membership.user_id == crm.member.id,
                                                             Membership.organization_id == crm.org.id))
            membership.is_active = True
            db.commit()


def test_a_disabled_ai_capability_stops_the_read_at_the_gate(crm):
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=crm.org.id, actor_user_id=crm.member.id,
                               capability_key=ASSISTANT, is_enabled=False)
        db.commit()
    result = _call(crm, tool="leads.get", arguments={"lead_id": str(crm.lead)})
    assert result.outcome == "denied" and result.data is None
    assert result.reason_code != "ok"


def test_a_missing_provider_readiness_stops_the_read_at_the_gate(crm, monkeypatch):
    from app.providers.readiness import ConnectionReadiness, ReadinessCode

    monkeypatch.setattr(
        "app.governance.policy.best_provider_readiness",
        lambda db, *, organization_id, provider_keys: ConnectionReadiness(False, ReadinessCode.NOT_CONNECTED, None),
    )
    result = _call(crm, tool="requirements.get", arguments={"requirement_id": str(crm.requirement)})
    assert result.outcome == "denied" and result.data is None


# --- repetition, attribution and audit -------------------------------------------------------------------


def test_repeated_reads_return_the_same_data_and_each_call_is_audited_to_its_user(crm):
    first = _call(crm, tool="properties.get", arguments={"property_id": str(crm.property)})
    second = _call(crm, tool="properties.get", arguments={"property_id": str(crm.property)})
    assert first.data == second.data
    rows = _audit(crm.org.id)
    requested = [row for row in rows if row.outcome == "REQUESTED" or row.outcome == "requested"]
    completed = [row for row in rows if row.outcome == "COMPLETED" or row.outcome == "completed"]
    assert len(requested) >= 2 and len(completed) >= 2
    assert {row.user_id for row in requested} == {crm.member.id}
    for row in requested:
        metadata = json.loads(row.event_metadata)
        assert metadata["argument_names"] == ["property_id"]
        assert metadata["target_id"] == str(crm.property)


def _user(user_id):
    with SessionLocal() as db:
        from app.db.models.user import User
        user = db.get(User, user_id)
        db.expunge(user)
        return user

"""Lead intake, identity resolution, agent-driven qualification and human review (DFR1-021).

The tests use the real database, tenant and permission checks, the real CRM services, the real agent runtime and the scripted
provider boundary. Intake and matching are tested without any AI. Agent runs turn AI on through the same helpers the agent tests
use, and one test shows that a run is refused while AI is off.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.agents import runtime
from app.agents.configuration import ConfigurationError, normalise_configuration
from app.agents.crm_action_catalogue import INTAKE_PROCESS, LEAD_CALCULATE_PRIORITY
from app.agents.handlers import handle_execution_requested
from app.agents.runtime import create_execution
from app.agents.service import AgentError, execution_metrics
from app.agents.templates import (
    IDENTITY_RESOLVER,
    LEAD_SCORING,
    QUALIFICATION,
    RECEPTIONIST,
    TEMPLATES,
)
from app.ai_tools.registry import DEFAULT_REGISTRY
from app.api.lead_intake import router as intake_router
from app.api.lead_qualification import router as qualification_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.config import get_settings
from app.db.models.activity import Activity
from app.db.models.agent import Agent, AgentExecution, AgentExecutionStep, AgentVersion
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.lead_intake import LeadIntakeSubmission, LeadQualificationResult
from app.db.models.lead_priority import LeadPriorityCorrection, LeadPriorityScore
from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal, get_db_session
from app.governance.service import set_capability_enabled
from app.leads.intake import (
    OUTCOME_AMBIGUOUS,
    OUTCOME_MATCHED_CONTACT,
    OUTCOME_NEW_CONTACT,
    IntakeCandidate,
    decide_match,
    validate_intake,
)
from app.leads.intake_service import (
    IntakeError,
    decide_submission,
    process_submission,
    submit_intake,
)
from app.leads.qualification import (
    QualificationError,
    is_stale,
    record_qualification,
    review_qualification,
)
from tests.agents_support import (
    AGENT_CAPABILITY,
    create_draft,
    create_user_in,
    enable_ai,
    keyring,  # noqa: F401
    publish,
    use_provider,
)
from tests.test_ai_gateway import _ok_text
from tests.test_team_api import TestingSessionLocal, create_owner_manager

NOW = datetime(2030, 1, 10, 12, 0, tzinfo=UTC)
MANAGE = ("leads.read", "leads.create", "leads.update", "contacts.read", "contacts.create")


def _cleanup_org(organization_ids) -> None:
    with SessionLocal() as db:
        for organization_id in organization_ids:
            db.execute(delete(LeadQualificationResult).where(LeadQualificationResult.organization_id == organization_id))
            db.execute(delete(LeadIntakeSubmission).where(LeadIntakeSubmission.organization_id == organization_id))
            db.execute(delete(LeadPriorityCorrection).where(LeadPriorityCorrection.organization_id == organization_id))
            db.execute(delete(LeadPriorityScore).where(LeadPriorityScore.organization_id == organization_id))
            db.execute(delete(FollowUp).where(FollowUp.organization_id == organization_id))
            db.execute(delete(Activity).where(Activity.organization_id == organization_id))
            db.execute(delete(AgentExecutionStep).where(AgentExecutionStep.organization_id == organization_id))
            db.execute(delete(AgentExecution).where(AgentExecution.organization_id == organization_id))
            db.execute(delete(AgentVersion).where(AgentVersion.organization_id == organization_id))
            db.execute(delete(Agent).where(Agent.organization_id == organization_id))
            db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization_id))
            db.execute(delete(Lead).where(Lead.organization_id == organization_id))
            db.execute(delete(Contact).where(Contact.organization_id == organization_id))
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.commit()


@pytest.fixture
def orgs() -> Iterator[SimpleNamespace]:
    """AI is off in this organization. Intake and manual CRM work must still succeed."""
    owner, org = create_owner_manager(permissions=MANAGE)
    other, other_org = create_owner_manager(permissions=MANAGE)
    member = create_user_in(org, permissions=MANAGE)
    reader = create_user_in(org, permissions=("leads.read", "contacts.read"))
    yield SimpleNamespace(owner=owner, org=org, other=other, other_org=other_org, member=member, reader=reader)
    _cleanup_org((org.id, other_org.id))


@pytest.fixture
def agent_world(monkeypatch, keyring) -> Iterator[SimpleNamespace]:  # noqa: F811
    """An organization with AI enabled, a member who can run the CRM agents, and a second organization."""
    owner, org = create_owner_manager(permissions=MANAGE)
    other, other_org = create_owner_manager(permissions=MANAGE)
    member = create_user_in(org, permissions=MANAGE + ("agents.read", "agents.run", "agents.manage", "agents.approve",
                                                       "governance.consent.read"))
    monkeypatch.setenv("PROVIDER_LIVE_ADAPTERS_ENABLED", "true")
    get_settings.cache_clear()
    enable_ai(monkeypatch, org, owner)
    world = SimpleNamespace(owner=owner, org=org, member=member, other=other, other_org=other_org, agent_id=None)
    yield world
    _cleanup_org((org.id, other_org.id))


# --- helpers ----------------------------------------------------------------------------------------


def _contact(organization_id, *, email: str | None = None, phone: str | None = None, first: str = "Asha",
             last: str = "Rao") -> uuid.UUID:
    with SessionLocal() as db:
        contact = Contact(organization_id=organization_id, first_name=first, last_name=last, email=email, phone=phone,
                          is_active=True)
        db.add(contact)
        db.commit()
        return contact.id


def _lead(organization_id, contact_id, *, interest: str | None = "HIGH", status: str = "NEW",
          is_active: bool = True) -> uuid.UUID:
    with SessionLocal() as db:
        lead = Lead(organization_id=organization_id, contact_id=contact_id, status=status, interest=interest,
                    is_active=is_active)
        db.add(lead)
        db.commit()
        return lead.id


def _submit(organization_id, actor_id, *, reference: str | None = None, payload: dict | None = None,
            channel: str = "form"):
    with SessionLocal() as db:
        row, created = submit_intake(
            db, organization_id=organization_id, actor_id=actor_id, source_channel=channel,
            external_reference=reference or f"ref-{uuid.uuid4().hex}",
            payload=payload if payload is not None else {"first_name": "Ravi", "last_name": "Iyer",
                                                          "email": "ravi@example.test", "interest": "HIGH"},
        )
        db.commit()
        return row.id, created


def _process(organization_id, actor_id, submission_id):
    with SessionLocal() as db:
        row = process_submission(db, organization_id=organization_id, actor_id=actor_id, submission_id=submission_id)
        db.commit()
        return row.id, row.status, row.match_outcome, row.contact_id, row.lead_id


def _client(user, organization, routers) -> TestClient:
    app = FastAPI()
    for router in routers:
        app.include_router(router)

    def session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    client = TestClient(app)
    client.headers["X-Organization-ID"] = str(organization.id)
    return client


def _count(model, organization_id) -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(model.id).where(model.organization_id == organization_id)).all())


# --- pure validation and matching ------------------------------------------------------------------


def test_a_complete_submission_is_valid_and_normalized():
    normalized, problems = validate_intake({"first_name": " Ravi ", "last_name": "Iyer", "email": "ravi@example.test",
                                            "phone": "+91 98765-43210", "interest": "high"})
    assert problems == []
    assert normalized == {"first_name": "Ravi", "last_name": "Iyer", "email": "ravi@example.test",
                          "phone": "919876543210", "interest": "HIGH"}


def test_invalid_submissions_name_each_problem_without_echoing_the_value():
    normalized, problems = validate_intake({"first_name": "", "email": "not-an-address-secret", "interest": "VERY"})
    assert normalized is None
    assert "A first name of 1 to 100 characters is required." in problems
    assert "The email address is not valid." in problems
    assert "The interest must be LOW, MEDIUM or HIGH." in problems
    assert not any("secret" in problem or "VERY" in problem for problem in problems)


def test_a_submission_needs_an_email_or_a_phone_number():
    normalized, problems = validate_intake({"first_name": "Ravi"})
    assert normalized is None
    assert problems == ["An email address or a phone number is required to identify the person."]


def test_fields_outside_the_intake_form_are_refused():
    normalized, problems = validate_intake({"first_name": "Ravi", "email": "ravi@example.test", "status": "WON"})
    assert normalized is None
    assert any("not part of the intake form" in problem for problem in problems)


def test_identity_matching_rules_are_conservative():
    base = {"first_name": "Ravi", "last_name": "Iyer", "email": "ravi@example.test", "phone": "919876543210"}
    assert decide_match(base, []) == OUTCOME_NEW_CONTACT
    assert decide_match(base, [IntakeCandidate("a", True, False, False)]) == OUTCOME_MATCHED_CONTACT
    assert decide_match(base, [IntakeCandidate("a", False, True, True)]) == OUTCOME_MATCHED_CONTACT
    # A shared phone with a different name could be a family line, so a person decides.
    assert decide_match(base, [IntakeCandidate("a", False, True, False)]) == OUTCOME_AMBIGUOUS
    assert decide_match(base, [IntakeCandidate("a", True, False, False),
                               IntakeCandidate("b", False, True, True)]) == OUTCOME_AMBIGUOUS


# --- submissions and processing (no AI) ------------------------------------------------------------


def test_a_new_person_becomes_a_contact_and_an_open_lead_through_the_crm_services(orgs):
    submission_id, created = _submit(orgs.org.id, orgs.member.id)
    assert created
    _, status, outcome, contact_id, lead_id = _process(orgs.org.id, orgs.member.id, submission_id)
    assert (status, outcome) == ("processed", OUTCOME_NEW_CONTACT)
    with SessionLocal() as db:
        contact = db.get(Contact, contact_id)
        lead = db.get(Lead, lead_id)
        assert contact.email == "ravi@example.test"
        assert lead.contact_id == contact_id and lead.interest == "HIGH" and lead.status == Lead.STATUS_NEW


def test_a_repeated_reference_with_the_same_content_returns_the_stored_submission(orgs):
    reference = f"web-{uuid.uuid4().hex}"
    first_id, created = _submit(orgs.org.id, orgs.member.id, reference=reference)
    second_id, created_again = _submit(orgs.org.id, orgs.member.id, reference=reference)
    assert created and not created_again
    assert first_id == second_id
    assert _count(LeadIntakeSubmission, orgs.org.id) == 1


def test_a_reused_reference_with_different_content_is_refused(orgs):
    reference = f"web-{uuid.uuid4().hex}"
    _submit(orgs.org.id, orgs.member.id, reference=reference)
    with SessionLocal() as db, pytest.raises(IntakeError) as error:
        submit_intake(db, organization_id=orgs.org.id, actor_id=orgs.member.id, source_channel="form",
                      external_reference=reference, payload={"first_name": "Other", "email": "other@example.test"})
    assert error.value.reason == "idempotency_conflict"


def test_an_invalid_submission_is_stored_and_cannot_be_processed(orgs):
    submission_id, created = _submit(orgs.org.id, orgs.member.id, payload={"first_name": "Ravi"})
    assert created
    with SessionLocal() as db:
        row = db.get(LeadIntakeSubmission, submission_id)
        assert row.status == "invalid" and row.validation_problems
    with SessionLocal() as db, pytest.raises(IntakeError) as error:
        process_submission(db, organization_id=orgs.org.id, actor_id=orgs.member.id, submission_id=submission_id)
    assert error.value.reason == "invalid_submission"
    assert _count(Contact, orgs.org.id) == 0


def test_a_matched_contact_with_an_open_lead_does_not_get_a_second_lead(orgs):
    contact_id = _contact(orgs.org.id, email="ravi@example.test")
    lead_id = _lead(orgs.org.id, contact_id)
    submission_id, _ = _submit(orgs.org.id, orgs.member.id)
    _, status, outcome, matched_contact, matched_lead = _process(orgs.org.id, orgs.member.id, submission_id)
    assert (status, outcome) == ("processed", "matched_open_lead")
    assert matched_contact == contact_id and matched_lead == lead_id
    assert _count(Lead, orgs.org.id) == 1
    assert _count(Contact, orgs.org.id) == 1


def test_a_closed_lead_does_not_block_a_new_lead_for_a_returning_person(orgs):
    contact_id = _contact(orgs.org.id, email="ravi@example.test")
    _lead(orgs.org.id, contact_id, status=Lead.STATUS_LOST)
    submission_id, _ = _submit(orgs.org.id, orgs.member.id)
    _, status, outcome, _, _ = _process(orgs.org.id, orgs.member.id, submission_id)
    assert (status, outcome) == ("processed", OUTCOME_MATCHED_CONTACT)
    assert _count(Lead, orgs.org.id) == 2


def test_an_ambiguous_identity_waits_for_a_human_and_writes_no_crm_record(orgs):
    contact_id = _contact(orgs.org.id, phone="919876543210", first="Someone", last="Else")
    submission_id, _ = _submit(orgs.org.id, orgs.member.id,
                               payload={"first_name": "Ravi", "last_name": "Iyer", "phone": "+91 98765 43210"})
    _, status, outcome, _, _ = _process(orgs.org.id, orgs.member.id, submission_id)
    assert (status, outcome) == ("needs_review", OUTCOME_AMBIGUOUS)
    with SessionLocal() as db:
        row = db.get(LeadIntakeSubmission, submission_id)
        assert row.candidate_contact_ids == [str(contact_id)]
    assert _count(Contact, orgs.org.id) == 1
    assert _count(Lead, orgs.org.id) == 0


def test_a_human_can_attach_an_uncertain_submission_to_a_matched_contact_and_the_decision_is_attributed(orgs):
    contact_id = _contact(orgs.org.id, phone="919876543210", first="Someone", last="Else")
    submission_id, _ = _submit(orgs.org.id, orgs.member.id,
                               payload={"first_name": "Ravi", "last_name": "Iyer", "phone": "+91 98765 43210"})
    _process(orgs.org.id, orgs.member.id, submission_id)
    with SessionLocal() as db:
        row = decide_submission(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, submission_id=submission_id,
                                decision="attach", contact_id=contact_id, reason="Same household, confirmed by phone.")
        db.commit()
        assert row.status == "processed" and row.decision == "attach"
        assert row.decided_by_user_id == orgs.owner.id
        assert row.contact_id == contact_id and row.lead_id is not None
    assert _count(Contact, orgs.org.id) == 1


def test_a_new_contact_is_refused_while_the_identifier_already_belongs_to_a_contact(orgs):
    # The CRM does not allow two contacts with the same email or phone, so "create new" cannot override that. Nothing is written
    # and the decision is not kept: the submission stays open for attach or reject.
    _contact(orgs.org.id, phone="919876543210", first="Someone", last="Else")
    submission_id, _ = _submit(orgs.org.id, orgs.member.id,
                               payload={"first_name": "Ravi", "last_name": "Iyer", "phone": "+91 98765 43210"})
    _process(orgs.org.id, orgs.member.id, submission_id)
    with SessionLocal() as db, pytest.raises(IntakeError) as error:
        decide_submission(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, submission_id=submission_id,
                          decision="create_new")
    assert error.value.reason == "duplicate_contact"
    assert _count(Contact, orgs.org.id) == 1
    with SessionLocal() as db:
        row = db.get(LeadIntakeSubmission, submission_id)
        assert row.status == "needs_review" and row.decision is None


def test_attaching_to_a_contact_that_was_not_matched_is_refused(orgs):
    _contact(orgs.org.id, phone="919876543210", first="Someone", last="Else")
    other_contact = _contact(orgs.org.id, email="unrelated@example.test")
    submission_id, _ = _submit(orgs.org.id, orgs.member.id,
                               payload={"first_name": "Ravi", "last_name": "Iyer", "phone": "+91 98765 43210"})
    _process(orgs.org.id, orgs.member.id, submission_id)
    with SessionLocal() as db, pytest.raises(IntakeError) as error:
        decide_submission(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, submission_id=submission_id,
                          decision="attach", contact_id=other_contact)
    assert error.value.reason == "contact_not_a_candidate"


def test_a_rejected_submission_writes_no_crm_record(orgs):
    _contact(orgs.org.id, phone="919876543210", first="Someone", last="Else")
    submission_id, _ = _submit(orgs.org.id, orgs.member.id,
                               payload={"first_name": "Ravi", "last_name": "Iyer", "phone": "+91 98765 43210"})
    _process(orgs.org.id, orgs.member.id, submission_id)
    with SessionLocal() as db:
        row = decide_submission(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, submission_id=submission_id,
                                decision="reject", reason="Spam.")
        db.commit()
        assert row.status == "rejected"
    assert _count(Lead, orgs.org.id) == 0


def test_a_decided_submission_cannot_be_decided_again(orgs):
    _contact(orgs.org.id, phone="919876543210", first="Someone", last="Else")
    submission_id, _ = _submit(orgs.org.id, orgs.member.id,
                               payload={"first_name": "Ravi", "last_name": "Iyer", "phone": "+91 98765 43210"})
    _process(orgs.org.id, orgs.member.id, submission_id)
    with SessionLocal() as db:
        decide_submission(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, submission_id=submission_id,
                          decision="reject")
        db.commit()
    with SessionLocal() as db, pytest.raises(IntakeError) as error:
        decide_submission(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, submission_id=submission_id,
                          decision="attach", contact_id=None)
    assert error.value.reason == "not_awaiting_review"


def test_concurrent_processing_of_one_submission_creates_one_lead(orgs):
    submission_id, _ = _submit(orgs.org.id, orgs.member.id)
    barrier = threading.Barrier(3)

    def run():
        barrier.wait()
        try:
            return _process(orgs.org.id, orgs.member.id, submission_id)[1]
        except Exception as error:  # noqa: BLE001 - the outcome is asserted below
            return type(error).__name__

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: run(), range(3)))
    assert all(result == "processed" for result in results), results
    assert _count(Lead, orgs.org.id) == 1
    assert _count(Contact, orgs.org.id) == 1


def test_intake_and_manual_processing_work_without_ai(orgs):
    # The orgs fixture never enables AI. Submission and processing are CRM operations, not agent runs.
    submission_id, created = _submit(orgs.org.id, orgs.member.id)
    _, status, _, _, _ = _process(orgs.org.id, orgs.member.id, submission_id)
    assert created and status == "processed"


def test_readers_cannot_submit_process_or_decide(orgs):
    client = _client(orgs.reader, orgs.org, [intake_router])
    response = client.post("/api/v1/lead-intake", json={"source_channel": "form", "external_reference": "r-1",
                                                       "payload": {"first_name": "Ravi", "email": "ravi@example.test"}})
    assert response.status_code == 403
    submission_id, _ = _submit(orgs.org.id, orgs.member.id)
    assert client.post(f"/api/v1/lead-intake/{submission_id}/process").status_code == 403
    assert client.post(f"/api/v1/lead-intake/{submission_id}/decision", json={"decision": "reject"}).status_code == 403


def test_the_api_returns_stable_reasons_and_scopes_every_read_to_the_organization(orgs):
    client = _client(orgs.member, orgs.org, [intake_router])
    created = client.post("/api/v1/lead-intake", json={"source_channel": "api", "external_reference": f"api-{uuid.uuid4().hex}",
                                                      "payload": {"first_name": "Ravi", "email": "ravi@example.test"}})
    assert created.status_code == 201 and created.json()["created"] is True
    submission_id = created.json()["id"]

    other = _client(orgs.other, orgs.other_org, [intake_router])
    assert other.get(f"/api/v1/lead-intake/{submission_id}").status_code == 404
    assert other.post(f"/api/v1/lead-intake/{submission_id}/process").status_code == 404
    assert other.get("/api/v1/lead-intake").json()["items"] == []

    invalid = client.post("/api/v1/lead-intake", json={"source_channel": "api", "external_reference": "bad-1",
                                                      "payload": {"first_name": "Ravi"}})
    assert invalid.status_code == 201
    assert invalid.json()["status"] == "invalid"
    assert invalid.json()["validation_problems"]


def test_intake_is_audited_with_identifiers_and_without_personal_data(orgs):
    submission_id, _ = _submit(orgs.org.id, orgs.member.id, payload={"first_name": "Ravi", "email": "ravi@example.test"})
    _process(orgs.org.id, orgs.member.id, submission_id)
    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == orgs.org.id,
                                                     AuditEvent.event_type == "lead_intake")).all()
        actions = {event.action for event in events}
        assert {"lead_intake.submitted", "lead_intake.processed"} <= actions
        assert all("ravi@example.test" not in (event.event_metadata or "") for event in events)


# --- templates and configuration -------------------------------------------------------------------


def test_every_template_is_a_valid_configuration_for_the_approved_registry():
    registered = frozenset(DEFAULT_REGISTRY.keys())
    assert {RECEPTIONIST, IDENTITY_RESOLVER, LEAD_SCORING, QUALIFICATION} <= set(TEMPLATES)
    for key, template in TEMPLATES.items():
        canonical = normalise_configuration(template["configuration"], registered_tools=registered)
        assert canonical["trigger"] == {"type": "manual"}, key


def test_a_crm_action_must_name_an_approved_action_and_only_earlier_references():
    base = {
        "category": "operations", "purpose": "p", "instructions": "i", "inputs": [{"name": "lead", "type": "uuid"}],
        "limits": {"max_duration_seconds": 60, "max_steps": 5, "max_tool_calls": 1, "max_retries": 0,
                   "max_output_characters": 4000, "max_concurrent_executions": 1, "max_executions_per_hour": 10},
    }
    registered = frozenset(DEFAULT_REGISTRY.keys())
    with pytest.raises(ConfigurationError) as unknown:
        normalise_configuration(dict(base, steps=[{"kind": "crm_action", "action": "contacts.delete",
                                                   "arguments": {"lead_id": "$input.lead"}}]), registered_tools=registered)
    assert any("approved CRM action" in problem for problem in unknown.value.problems)
    with pytest.raises(ConfigurationError) as literal:
        normalise_configuration(dict(base, steps=[{"kind": "crm_action", "action": LEAD_CALCULATE_PRIORITY,
                                                   "arguments": {"lead_id": "00000000-0000-0000-0000-000000000000"}}]),
                                registered_tools=registered)
    assert any("declared input or to an earlier step" in problem for problem in literal.value.problems)
    with pytest.raises(ConfigurationError) as forward:
        normalise_configuration(dict(base, steps=[{"kind": "crm_action", "action": LEAD_CALCULATE_PRIORITY,
                                                   "arguments": {"lead_id": "$step.3.lead_id"}}]),
                                registered_tools=registered)
    assert any("declared input or to an earlier step" in problem for problem in forward.value.problems)
    with pytest.raises(ConfigurationError) as missing:
        normalise_configuration(dict(base, steps=[{"kind": "crm_action", "action": INTAKE_PROCESS, "arguments": {}}]),
                                registered_tools=registered)
    assert any("missing a required argument" in problem for problem in missing.value.problems)


# --- agent runs --------------------------------------------------------------------------------------


def _create_from_template(world, key: str) -> uuid.UUID:
    draft = create_draft(world, cfg=TEMPLATES[key]["configuration"], name=f"{key}-{uuid.uuid4().hex[:8]}")
    publish(world, draft["id"])
    return draft["id"]


def _start(world, agent_id, input_values, *, key: str | None = None, initiator=None):
    with SessionLocal() as db:
        execution, _ = create_execution(
            db,
            organization_id=world.org.id,
            agent_id=agent_id,
            user_context=CurrentUserContext(user=_user(initiator or world.member.id)),
            input_values=input_values,
            idempotency_key=key or f"key-{uuid.uuid4().hex}",
        )
        db.commit()
        return execution.id


def _user(user_id):
    from app.db.models.user import User
    with SessionLocal() as db:
        row = db.get(User, user_id)
        db.expunge(row)
        return row


def _drain(execution_id, organization_id) -> None:
    with SessionLocal() as db:
        event = db.scalar(select(OutboxEvent).where(
            OutboxEvent.organization_id == organization_id,
            OutboxEvent.event_type == runtime.EXECUTION_REQUESTED_EVENT,
            OutboxEvent.aggregate_id == str(execution_id),
        ).order_by(OutboxEvent.created_at.desc()))
        if event is not None:
            handle_execution_requested(db, event)
        db.commit()


def _execution(execution_id) -> AgentExecution:
    with SessionLocal() as db:
        row = db.get(AgentExecution, execution_id)
        db.expunge(row)
        return row


def test_the_receptionist_agent_processes_an_enquiry_through_the_runtime(agent_world):
    submission_id, _ = _submit(agent_world.org.id, agent_world.member.id)
    agent_id = _create_from_template(agent_world, RECEPTIONIST)
    execution_id = _start(agent_world, agent_id, {"submission_id": str(submission_id)})
    _drain(execution_id, agent_world.org.id)
    execution = _execution(execution_id)
    assert execution.status == "succeeded", execution.failure_reason
    with SessionLocal() as db:
        submission = db.get(LeadIntakeSubmission, submission_id)
        assert submission.status == "processed"
        assert submission.lead_id is not None
        assert submission.decided_by_user_id is None


def test_the_qualification_agent_records_findings_with_provenance_and_scores_through_the_existing_engine(agent_world, monkeypatch):
    contact_id = _contact(agent_world.org.id, email="ravi@example.test")
    lead_id = _lead(agent_world.org.id, contact_id, interest="HIGH")
    use_provider(monkeypatch, _ok_text(json.dumps({"next_action": "Call the lead this week."})))
    agent_id = _create_from_template(agent_world, QUALIFICATION)
    execution_id = _start(agent_world, agent_id, {"lead_id": str(lead_id)})
    _drain(execution_id, agent_world.org.id)
    execution = _execution(execution_id)
    assert execution.status == "succeeded", execution.failure_reason
    with SessionLocal() as db:
        result = db.scalar(select(LeadQualificationResult).where(LeadQualificationResult.execution_id == execution_id))
        assert result is not None
        findings = result.findings
        assert findings["verified_crm_facts"]["lead_id"] == str(lead_id)
        assert findings["rule_findings"]["ruleset_version"] == "priority-rules-v1"
        assert findings["rule_findings"]["score_id"] == str(result.score_id)
        assert findings["ai_suggestions"] == [{"text": "Call the lead this week.", "basis": "ai_suggestion", "verified": False}]
        assert {item["field"] for item in findings["missing_information"]} >= {"phone", "budget"}
        assert findings["human_decisions"] == []
        assert db.get(LeadPriorityScore, result.score_id) is not None
        lead = db.get(Lead, lead_id)
        assert lead.status == Lead.STATUS_NEW and lead.interest == "HIGH"


def test_a_baseline_lead_is_flagged_for_human_review(agent_world, monkeypatch):
    contact_id = _contact(agent_world.org.id)
    lead_id = _lead(agent_world.org.id, contact_id, interest=None)
    use_provider(monkeypatch, _ok_text(json.dumps({"next_action": "Find a phone number."})))
    agent_id = _create_from_template(agent_world, QUALIFICATION)
    execution_id = _start(agent_world, agent_id, {"lead_id": str(lead_id)})
    _drain(execution_id, agent_world.org.id)
    with SessionLocal() as db:
        result = db.scalar(select(LeadQualificationResult).where(LeadQualificationResult.execution_id == execution_id))
        assert result.requires_review is True
        assert set(result.findings["escalation"]["reasons"]) >= {"no_contact_route"}


def test_the_same_execution_never_records_findings_twice(agent_world):
    lead_id = _lead(agent_world.org.id, _contact(agent_world.org.id, email="ravi@example.test"))
    with SessionLocal() as db:
        from app.leads.priority_service import calculate_and_store
        score = calculate_and_store(db, organization_id=agent_world.org.id, actor_id=agent_world.member.id, lead_id=lead_id)
        db.commit()
        score_id = score.id
    agent_id = _create_from_template(agent_world, LEAD_SCORING)
    execution_id = _start(agent_world, agent_id, {"lead_id": str(lead_id)})
    with SessionLocal() as db:
        _, created_first = record_qualification(db, organization_id=agent_world.org.id, actor_id=agent_world.member.id,
                                                execution_id=execution_id, lead_id=lead_id, score_id=score_id, suggestion=None)
        db.commit()
    with SessionLocal() as db:
        _, created_second = record_qualification(db, organization_id=agent_world.org.id, actor_id=agent_world.member.id,
                                                 execution_id=execution_id, lead_id=lead_id, score_id=score_id, suggestion=None)
        db.commit()
    assert created_first is True and created_second is False
    assert _count(LeadQualificationResult, agent_world.org.id) == 1


def test_a_score_from_another_lead_cannot_be_recorded(agent_world):
    lead_a = _lead(agent_world.org.id, _contact(agent_world.org.id, email="a@example.test"))
    lead_b = _lead(agent_world.org.id, _contact(agent_world.org.id, email="b@example.test"))
    with SessionLocal() as db:
        from app.leads.priority_service import calculate_and_store
        score = calculate_and_store(db, organization_id=agent_world.org.id, actor_id=agent_world.member.id, lead_id=lead_a)
        db.commit()
        score_id = score.id
    with SessionLocal() as db, pytest.raises(QualificationError) as error:
        record_qualification(db, organization_id=agent_world.org.id, actor_id=agent_world.member.id,
                             execution_id=uuid.uuid4(), lead_id=lead_b, score_id=score_id, suggestion=None)
    assert error.value.reason == "score_not_for_lead"


def _qualification_row(agent_world, lead_id) -> uuid.UUID:
    """A recorded qualification for one lead, created through the real service with a real execution row."""
    with SessionLocal() as db:
        from app.leads.priority_service import calculate_and_store
        score = calculate_and_store(db, organization_id=agent_world.org.id, actor_id=agent_world.member.id, lead_id=lead_id)
        db.commit()
        score_id = score.id
    agent_id = _create_from_template(agent_world, LEAD_SCORING)
    execution_id = _start(agent_world, agent_id, {"lead_id": str(lead_id)})
    with SessionLocal() as db:
        row, _ = record_qualification(db, organization_id=agent_world.org.id, actor_id=agent_world.member.id,
                                      execution_id=execution_id, lead_id=lead_id, score_id=score_id, suggestion=None)
        db.commit()
        return row.id


def test_a_human_review_records_the_member_and_leaves_the_lead_unchanged(agent_world):
    lead_id = _lead(agent_world.org.id, _contact(agent_world.org.id, email="ravi@example.test"), interest="LOW")
    qualification_id = _qualification_row(agent_world, lead_id)
    with SessionLocal() as db:
        row = review_qualification(db, organization_id=agent_world.org.id, actor_id=agent_world.owner.id,
                                   qualification_id=qualification_id, decision="override",
                                   reason="The customer confirmed a larger budget.")
        db.commit()
        assert row.review_status == "overridden" and row.reviewed_by_user_id == agent_world.owner.id
        assert row.findings["human_decisions"][0]["decided_by_user_id"] == str(agent_world.owner.id)
        assert db.get(Lead, lead_id).interest == "LOW"


def test_an_override_needs_a_reason_and_a_result_is_reviewed_once(agent_world):
    lead_id = _lead(agent_world.org.id, _contact(agent_world.org.id, email="ravi@example.test"))
    qualification_id = _qualification_row(agent_world, lead_id)
    with SessionLocal() as db, pytest.raises(QualificationError) as no_reason:
        review_qualification(db, organization_id=agent_world.org.id, actor_id=agent_world.owner.id,
                             qualification_id=qualification_id, decision="override", reason=" ")
    assert no_reason.value.reason == "review_reason_required"
    with SessionLocal() as db:
        review_qualification(db, organization_id=agent_world.org.id, actor_id=agent_world.owner.id,
                             qualification_id=qualification_id, decision="accept", reason=None)
        db.commit()
    with SessionLocal() as db, pytest.raises(QualificationError) as twice:
        review_qualification(db, organization_id=agent_world.org.id, actor_id=agent_world.owner.id,
                             qualification_id=qualification_id, decision="accept", reason=None)
    assert twice.value.reason == "already_reviewed"


def test_a_result_is_marked_stale_when_the_lead_changes_after_it_was_recorded(agent_world):
    lead_id = _lead(agent_world.org.id, _contact(agent_world.org.id, email="ravi@example.test"))
    qualification_id = _qualification_row(agent_world, lead_id)
    with SessionLocal() as db:
        row = db.get(LeadQualificationResult, qualification_id)
        assert is_stale(db, row) is False
    with SessionLocal() as db:
        lead = db.get(Lead, lead_id)
        lead.status = Lead.STATUS_CONTACTED
        lead.updated_at = datetime.now(UTC) + timedelta(minutes=5)
        db.commit()
    with SessionLocal() as db:
        row = db.get(LeadQualificationResult, qualification_id)
        assert is_stale(db, row) is True


def test_an_agent_cannot_start_when_its_initiator_lacks_the_crm_permission(agent_world):
    lead_id = _lead(agent_world.org.id, _contact(agent_world.org.id, email="ravi@example.test"))
    agent_id = _create_from_template(agent_world, LEAD_SCORING)
    limited = create_user_in(agent_world.org, permissions=("agents.run", "governance.consent.read"))
    with SessionLocal() as db, pytest.raises(AgentError) as error:
        create_execution(db, organization_id=agent_world.org.id, agent_id=agent_id,
                         user_context=CurrentUserContext(user=_user(limited.id)),
                         input_values={"lead_id": str(lead_id)}, idempotency_key=f"k-{uuid.uuid4().hex}")
    assert error.value.reason == "not_permitted_now"


def test_an_agent_cannot_start_while_ai_is_switched_off(agent_world):
    lead_id = _lead(agent_world.org.id, _contact(agent_world.org.id, email="ravi@example.test"))
    agent_id = _create_from_template(agent_world, LEAD_SCORING)
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=agent_world.org.id, actor_user_id=agent_world.owner.id,
                               capability_key=AGENT_CAPABILITY, is_enabled=False)
        db.commit()
    with SessionLocal() as db, pytest.raises(AgentError) as error:
        create_execution(db, organization_id=agent_world.org.id, agent_id=agent_id,
                         user_context=CurrentUserContext(user=_user(agent_world.member.id)),
                         input_values={"lead_id": str(lead_id)}, idempotency_key=f"k-{uuid.uuid4().hex}")
    assert error.value.reason == "not_permitted_now"


def test_a_duplicate_outbox_delivery_processes_the_submission_once(agent_world):
    submission_id, _ = _submit(agent_world.org.id, agent_world.member.id)
    agent_id = _create_from_template(agent_world, RECEPTIONIST)
    execution_id = _start(agent_world, agent_id, {"submission_id": str(submission_id)})
    _drain(execution_id, agent_world.org.id)
    _drain(execution_id, agent_world.org.id)
    assert _execution(execution_id).status == "succeeded"
    assert _count(Lead, agent_world.org.id) == 1
    assert _count(Contact, agent_world.org.id) == 1


def test_the_lead_scoring_agent_writes_only_a_score_and_not_the_lead(agent_world):
    lead_id = _lead(agent_world.org.id, _contact(agent_world.org.id, email="ravi@example.test"), interest="MEDIUM")
    agent_id = _create_from_template(agent_world, LEAD_SCORING)
    execution_id = _start(agent_world, agent_id, {"lead_id": str(lead_id)})
    _drain(execution_id, agent_world.org.id)
    assert _execution(execution_id).status == "succeeded"
    with SessionLocal() as db:
        assert len(db.scalars(select(LeadPriorityScore.id).where(LeadPriorityScore.lead_id == lead_id)).all()) == 1
        lead = db.get(Lead, lead_id)
        assert lead.interest == "MEDIUM" and lead.status == Lead.STATUS_NEW


def test_execution_metrics_count_statuses_and_failure_reasons(agent_world):
    agent_id = _create_from_template(agent_world, RECEPTIONIST)
    ok_submission, _ = _submit(agent_world.org.id, agent_world.member.id)
    ok_execution = _start(agent_world, agent_id, {"submission_id": str(ok_submission)})
    _drain(ok_execution, agent_world.org.id)
    bad_submission, _ = _submit(agent_world.org.id, agent_world.member.id, payload={"first_name": "Ravi"})
    bad_execution = _start(agent_world, agent_id, {"submission_id": str(bad_submission)})
    _drain(bad_execution, agent_world.org.id)
    with SessionLocal() as db:
        metrics = execution_metrics(db, organization_id=agent_world.org.id, actor_id=agent_world.member.id, agent_id=agent_id)
    assert metrics["total"] == 2
    assert metrics["by_status"].get("succeeded") == 1
    assert metrics["by_status"].get("failed") == 1
    assert {"reason": "invalid_submission", "count": 1} in metrics["failure_reasons"]


def test_a_template_agent_is_invisible_to_another_organization(agent_world):
    agent_id = _create_from_template(agent_world, RECEPTIONIST)
    with SessionLocal() as db, pytest.raises(AgentError) as error:
        execution_metrics(db, organization_id=agent_world.other_org.id, actor_id=agent_world.other.id, agent_id=agent_id)
    assert error.value.reason == "agent_not_found"


def test_qualification_api_lists_results_with_staleness_and_scopes_them(agent_world):
    lead_id = _lead(agent_world.org.id, _contact(agent_world.org.id, email="ravi@example.test"))
    _qualification_row(agent_world, lead_id)
    client = _client(agent_world.member, agent_world.org, [qualification_router])
    listed = client.get(f"/api/v1/leads/{lead_id}/qualifications")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["stale"] is False
    other = _client(agent_world.other, agent_world.other_org, [qualification_router])
    assert other.get(f"/api/v1/leads/{lead_id}/qualifications").status_code == 404

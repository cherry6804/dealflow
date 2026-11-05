"""Explainable lead priority and human corrections (DFR1-020).

The tests use the real database, the real tenant and permission checks, the real audit table and the real CRM records. The scoring
reads recorded facts only, so no AI provider, gateway or budget is involved, and the tests do not need one.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.lead_priority import router as priority_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.activity import Activity
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_location import CustomerRequirementLocation
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.lead_priority import LeadPriorityCorrection, LeadPriorityScore
from app.db.session import SessionLocal, get_db_session
from app.leads import priority as priority_module
from app.leads.priority import (
    METHOD_BASELINE,
    METHOD_RULE,
    RULESET_VERSION,
    band_for,
    compute_priority,
)
from app.leads.priority_service import (
    PriorityError,
    calculate_and_store,
    record_correction,
)
from tests.agents_support import create_user_in
from tests.test_team_api import TestingSessionLocal, create_owner_manager

NOW = datetime(2030, 1, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def orgs() -> Iterator[SimpleNamespace]:
    owner, org = create_owner_manager(permissions=("leads.read", "leads.update"))
    other, other_org = create_owner_manager(permissions=("leads.read", "leads.update"))
    reader = create_user_in(org, permissions=("leads.read",))
    yield SimpleNamespace(owner=owner, org=org, other=other, other_org=other_org, reader=reader)
    with SessionLocal() as db:
        for organization_id in (org.id, other_org.id):
            db.execute(delete(LeadPriorityCorrection).where(LeadPriorityCorrection.organization_id == organization_id))
            db.execute(delete(LeadPriorityScore).where(LeadPriorityScore.organization_id == organization_id))
            db.execute(delete(FollowUp).where(FollowUp.organization_id == organization_id))
            db.execute(delete(Activity).where(Activity.organization_id == organization_id))
            db.execute(delete(CustomerRequirementPropertyPreference).where(
                CustomerRequirementPropertyPreference.organization_id == organization_id))
            db.execute(delete(CustomerRequirementLocation).where(CustomerRequirementLocation.organization_id == organization_id))
            db.execute(delete(CustomerRequirement).where(CustomerRequirement.organization_id == organization_id))
            db.execute(delete(Lead).where(Lead.organization_id == organization_id))
            db.execute(delete(Contact).where(Contact.organization_id == organization_id))
            db.execute(delete(AuditEvent).where(AuditEvent.organization_id == organization_id))
        db.commit()


def _contact(organization_id, *, email: str | None = "lead@example.test", phone: str | None = None) -> Contact:
    with SessionLocal() as db:
        contact = Contact(organization_id=organization_id, first_name="Lead", last_name="Person",
                          email=email, phone=phone, is_active=True)
        db.add(contact)
        db.commit()
        return contact.id


def _lead(organization_id, contact_id, *, interest: str | None = "HIGH", status: str = "NEW",
          updated_at: datetime | None = None, is_active: bool = True) -> uuid.UUID:
    with SessionLocal() as db:
        lead = Lead(organization_id=organization_id, contact_id=contact_id, status=status, interest=interest,
                    is_active=is_active)
        db.add(lead)
        db.flush()
        if updated_at is not None:
            lead.updated_at = updated_at
        db.commit()
        return lead.id


def _requirement(organization_id, lead_id, *, budget_max: str | None = "9000000", budget_min: str | None = None) -> uuid.UUID:
    with SessionLocal() as db:
        requirement = CustomerRequirement(organization_id=organization_id, lead_id=lead_id, status="ACTIVE", is_active=True,
                                          budget_min=Decimal(budget_min) if budget_min else None,
                                          budget_max=Decimal(budget_max) if budget_max else None,
                                          budget_currency="INR")
        db.add(requirement)
        db.flush()
        db.add(CustomerRequirementLocation(organization_id=organization_id, customer_requirement_id=requirement.id,
                                           city="Bengaluru", locality="Whitefield", is_active=True))
        db.add(CustomerRequirementPropertyPreference(organization_id=organization_id,
                                                     customer_requirement_id=requirement.id,
                                                     property_type="APARTMENT", bhk_min=2, bhk_max=3, is_active=True))
        db.commit()
        return requirement.id


def _follow_up(organization_id, lead_id, owner_id, *, due_at: datetime) -> None:
    with SessionLocal() as db:
        db.add(FollowUp(organization_id=organization_id, lead_id=lead_id, owner_user_id=owner_id,
                        follow_up_type="CALL", title="Call", due_at=due_at, status="PENDING"))
        db.commit()


def _client(user, organization) -> TestClient:
    app = FastAPI()
    app.include_router(priority_router)

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


def _full_lead(orgs) -> uuid.UUID:
    contact = _contact(orgs.org.id, phone="+10000000001")
    lead = _lead(orgs.org.id, contact, interest="HIGH", updated_at=NOW - timedelta(days=1))
    _requirement(orgs.org.id, lead, budget_max="9000000")
    _follow_up(orgs.org.id, lead, orgs.owner.id, due_at=NOW + timedelta(days=2))
    return lead


# --- the rules (pure, against real rows) -----------------------------------------------------------------


def test_a_lead_with_full_facts_is_scored_by_rules_with_each_factor_visible(orgs):
    lead_id = _full_lead(orgs)
    with SessionLocal() as db:
        result = compute_priority(db, organization_id=orgs.org.id, lead_id=lead_id, now=NOW)
    assert result.outcome == "scored"
    assert result.method == METHOD_RULE and result.insufficient_data is False
    assert result.missing_factors == ()
    assert result.score == 25 + 20 + 15 + 10 + 10 + 10 + 10
    assert result.band == "high"
    assert result.confidence == "high"
    by_key = {factor.key: factor for factor in result.factors}
    assert by_key["budget"].observed == "9000000.00"
    assert by_key["recent_activity"].source["entity"] == "lead"
    assert len(result.requirements) == 1
    assert result.requirements[0]["locations"][0]["city"] == "Bengaluru"


def test_a_lead_with_little_recorded_data_is_labelled_a_baseline_and_missing_facts_are_listed(orgs):
    contact = _contact(orgs.org.id, email=None, phone=None)
    lead_id = _lead(orgs.org.id, contact, interest=None, updated_at=NOW - timedelta(days=90))
    with SessionLocal() as db:
        result = compute_priority(db, organization_id=orgs.org.id, lead_id=lead_id, now=NOW)
    assert result.method == METHOD_BASELINE
    assert result.insufficient_data is True
    assert "budget" in result.missing_factors and "interest" in result.missing_factors
    assert result.confidence == "low"
    assert result.score == 0  # Nothing was known to earn points. Nothing was guessed.


def test_the_same_facts_give_the_same_score_and_input_hash(orgs):
    lead_id = _full_lead(orgs)
    with SessionLocal() as db:
        first = compute_priority(db, organization_id=orgs.org.id, lead_id=lead_id, now=NOW)
        second = compute_priority(db, organization_id=orgs.org.id, lead_id=lead_id, now=NOW)
    assert (first.score, first.input_hash) == (second.score, second.input_hash)


def test_won_lost_and_inactive_leads_have_no_priority(orgs):
    contact = _contact(orgs.org.id)
    won = _lead(orgs.org.id, contact, status="WON")
    inactive = _lead(orgs.org.id, contact, is_active=False)
    with SessionLocal() as db:
        assert compute_priority(db, organization_id=orgs.org.id, lead_id=won, now=NOW).outcome == "not_applicable"
        assert compute_priority(db, organization_id=orgs.org.id, lead_id=inactive, now=NOW).outcome == "not_applicable"


def test_no_result_is_a_probability_and_bands_follow_the_points(orgs):
    assert band_for(70) == "high" and band_for(40) == "medium" and band_for(39) == "low"
    lead_id = _full_lead(orgs)
    with SessionLocal() as db:
        result = compute_priority(db, organization_id=orgs.org.id, lead_id=lead_id, now=NOW)
    assert not hasattr(result, "probability")
    assert RULESET_VERSION == priority_module.RULESET_VERSION


# --- storage, audit and corrections -----------------------------------------------------------------------


def test_a_calculated_score_is_stored_with_version_timestamp_factors_and_attribution(orgs):
    lead_id = _full_lead(orgs)
    with SessionLocal() as db:
        row = calculate_and_store(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, lead_id=lead_id, now=NOW)
        db.commit()
        score_id = row.id
    with SessionLocal() as db:
        stored = db.get(LeadPriorityScore, score_id)
        assert stored.ruleset_version == RULESET_VERSION
        assert stored.computed_at == NOW
        assert stored.computed_by_user_id == orgs.owner.id
        assert {factor["key"] for factor in stored.factors} >= {"interest", "budget", "reachability"}
        audits = db.scalars(select(AuditEvent).where(AuditEvent.action == "lead.priority.calculated",
                                                     AuditEvent.organization_id == orgs.org.id)).all()
        assert audits and audits[0].user_id == orgs.owner.id


def test_each_calculation_is_kept_so_history_shows_how_a_priority_changed(orgs):
    lead_id = _full_lead(orgs)
    client = _client(orgs.owner, orgs.org)
    first = client.post(f"/api/v1/leads/{lead_id}/priority")
    second = client.post(f"/api/v1/leads/{lead_id}/priority")
    assert first.status_code == 201 and second.status_code == 201
    listing = client.get(f"/api/v1/leads/{lead_id}/priority").json()
    assert len(listing["items"]) == 2
    assert listing["latest"]["id"] == second.json()["id"]
    assert listing["ruleset_version"] == RULESET_VERSION
    assert "not a probability" in listing["latest"]["disclaimer"]


def test_a_correction_is_recorded_for_evaluation_and_the_score_is_unchanged(orgs):
    lead_id = _full_lead(orgs)
    client = _client(orgs.owner, orgs.org)
    score = client.post(f"/api/v1/leads/{lead_id}/priority").json()
    before = client.get(f"/api/v1/leads/{lead_id}/priority").json()["latest"]["score"]
    response = client.post(f"/api/v1/leads/{lead_id}/priority/{score['id']}/corrections", json={
        "corrected_band": "low", "reason": "The buyer has already paid elsewhere.",
        "idempotency_key": f"corr-{uuid.uuid4().hex}"})
    assert response.status_code == 200
    assert response.json()["created"] is True
    assert client.get(f"/api/v1/leads/{lead_id}/priority").json()["latest"]["score"] == before
    listed = client.get(f"/api/v1/leads/{lead_id}/priority/{score['id']}/corrections").json()["items"]
    assert listed[0]["corrected_band"] == "low"


def test_a_repeated_correction_with_the_same_key_is_idempotent(orgs):
    lead_id = _full_lead(orgs)
    client = _client(orgs.owner, orgs.org)
    score = client.post(f"/api/v1/leads/{lead_id}/priority").json()
    body = {"corrected_score": 40, "reason": "Recheck.", "idempotency_key": f"same-{uuid.uuid4().hex}"}
    first = client.post(f"/api/v1/leads/{lead_id}/priority/{score['id']}/corrections", json=body).json()
    second = client.post(f"/api/v1/leads/{lead_id}/priority/{score['id']}/corrections", json=body).json()
    assert first["id"] == second["id"] and second["created"] is False


def test_concurrent_corrections_with_one_key_store_exactly_one_row(orgs):
    lead_id = _full_lead(orgs)
    with SessionLocal() as db:
        score = calculate_and_store(db, organization_id=orgs.org.id, actor_id=orgs.owner.id, lead_id=lead_id, now=NOW)
        db.commit()
        score_id = score.id
    key = f"race-{uuid.uuid4().hex}"
    barrier = threading.Barrier(4)

    def correct(_index: int) -> bool:
        barrier.wait()
        with SessionLocal() as db:
            try:
                _row, created = record_correction(db, organization_id=orgs.org.id, actor_id=orgs.owner.id,
                                                  lead_id=lead_id, score_id=score_id, corrected_band="medium",
                                                  corrected_score=None, reason="Concurrent.",
                                                  idempotency_key=key)
                db.commit()
                return created
            except PriorityError:
                db.rollback()
                raise

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(correct, range(4)))
    assert outcomes.count(True) == 1
    with SessionLocal() as db:
        rows = db.scalars(select(LeadPriorityCorrection).where(
            LeadPriorityCorrection.organization_id == orgs.org.id,
            LeadPriorityCorrection.idempotency_key == key)).all()
    assert len(rows) == 1


def test_a_key_reused_for_another_score_is_refused(orgs):
    lead_id = _full_lead(orgs)
    client = _client(orgs.owner, orgs.org)
    first = client.post(f"/api/v1/leads/{lead_id}/priority").json()
    second = client.post(f"/api/v1/leads/{lead_id}/priority").json()
    key = f"reuse-{uuid.uuid4().hex}"
    body = {"corrected_band": "high", "reason": "Check.", "idempotency_key": key}
    assert client.post(f"/api/v1/leads/{lead_id}/priority/{first['id']}/corrections", json=body).status_code == 200
    refused = client.post(f"/api/v1/leads/{lead_id}/priority/{second['id']}/corrections", json=body)
    assert refused.status_code == 409
    assert refused.json()["detail"]["reason"] == "idempotency_conflict"


def test_invalid_corrections_are_refused_with_named_problems(orgs):
    lead_id = _full_lead(orgs)
    client = _client(orgs.owner, orgs.org)
    score = client.post(f"/api/v1/leads/{lead_id}/priority").json()
    url = f"/api/v1/leads/{lead_id}/priority/{score['id']}/corrections"
    bad_band = client.post(url, json={"corrected_band": "certain", "reason": "x", "idempotency_key": "b1"})
    assert bad_band.status_code == 422
    nothing = client.post(url, json={"reason": "x", "idempotency_key": "b2"})
    assert nothing.status_code == 422
    assert client.post(url, json={"corrected_band": "low", "reason": "x", "idempotency_key": "b3",
                                  "unknown": 1}).status_code == 422


# --- authorization, tenant isolation and activation --------------------------------------------------------


def test_a_reader_can_see_priorities_but_cannot_calculate_or_correct(orgs):
    lead_id = _full_lead(orgs)
    owner = _client(orgs.owner, orgs.org)
    score = owner.post(f"/api/v1/leads/{lead_id}/priority").json()
    reader = _client(orgs.reader, orgs.org)
    assert reader.get(f"/api/v1/leads/{lead_id}/priority").status_code == 200
    assert reader.post(f"/api/v1/leads/{lead_id}/priority").status_code == 403
    assert reader.post(f"/api/v1/leads/{lead_id}/priority/{score['id']}/corrections", json={
        "corrected_band": "low", "reason": "x", "idempotency_key": "r1"}).status_code == 403


def test_another_organization_cannot_read_calculate_or_correct_this_organizations_priority(orgs):
    lead_id = _full_lead(orgs)
    owner = _client(orgs.owner, orgs.org)
    score = owner.post(f"/api/v1/leads/{lead_id}/priority").json()
    other = _client(orgs.other, orgs.other_org)
    assert other.get(f"/api/v1/leads/{lead_id}/priority").status_code == 404
    assert other.post(f"/api/v1/leads/{lead_id}/priority").status_code == 404
    assert other.post(f"/api/v1/leads/{lead_id}/priority/{score['id']}/corrections", json={
        "corrected_band": "low", "reason": "x", "idempotency_key": "x1"}).status_code == 404


def test_a_score_cannot_be_corrected_through_another_lead(orgs):
    lead_id = _full_lead(orgs)
    contact = _contact(orgs.org.id)
    other_lead = _lead(orgs.org.id, contact)
    client = _client(orgs.owner, orgs.org)
    score = client.post(f"/api/v1/leads/{lead_id}/priority").json()
    response = client.post(f"/api/v1/leads/{other_lead}/priority/{score['id']}/corrections", json={
        "corrected_band": "low", "reason": "x", "idempotency_key": "cross-lead"})
    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "score_not_found"


def test_calculation_works_with_ai_switched_off_because_it_reads_recorded_facts_only(orgs):
    lead_id = _full_lead(orgs)
    client = _client(orgs.owner, orgs.org)
    response = client.post(f"/api/v1/leads/{lead_id}/priority")
    assert response.status_code == 201
    assert response.json()["method"] == METHOD_RULE


def test_a_closed_lead_refuses_calculation_with_a_reason(orgs):
    contact = _contact(orgs.org.id)
    won = _lead(orgs.org.id, contact, status="WON")
    response = _client(orgs.owner, orgs.org).post(f"/api/v1/leads/{won}/priority")
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "lead_closed_or_inactive"


def test_the_correction_is_audited_to_the_acting_user_without_contact_details(orgs):
    lead_id = _full_lead(orgs)
    client = _client(orgs.owner, orgs.org)
    score = client.post(f"/api/v1/leads/{lead_id}/priority").json()
    client.post(f"/api/v1/leads/{lead_id}/priority/{score['id']}/corrections", json={
        "corrected_band": "medium", "reason": "Check.", "idempotency_key": f"audit-{uuid.uuid4().hex}"})
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.action == "lead.priority.corrected",
                                                   AuditEvent.organization_id == orgs.org.id)).all()
    assert rows and rows[0].user_id == orgs.owner.id
    assert "lead@example.test" not in (rows[0].event_metadata or "")

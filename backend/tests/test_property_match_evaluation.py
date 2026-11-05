"""Explainable property matching, ranking, next-best-action recommendations and their safety (DFR1-022).

The tests use the real database, the existing matching engine, the real run history and the real tenant and permission checks.
Matching needs no AI. The agent tests turn AI on through the same helpers the agent tests use, and one test shows the run is refused
while AI is off.
"""

from __future__ import annotations

import json
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

from app.agents import runtime
from app.agents.configuration import normalise_configuration
from app.agents.handlers import handle_execution_requested
from app.agents.runtime import create_execution
from app.agents.templates import PROPERTY_MATCHING, TEMPLATES
from app.ai_tools.registry import DEFAULT_REGISTRY
from app.api.property_matching import router as matching_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.config import get_settings
from app.db.models.activity import Activity
from app.db.models.agent import Agent, AgentExecution, AgentExecutionStep, AgentVersion
from app.db.models.audit_event import AuditEvent
from app.db.models.contact import Contact
from app.db.models.customer_requirement import CustomerRequirement
from app.db.models.customer_requirement_history import CustomerRequirementHistory
from app.db.models.customer_requirement_location import CustomerRequirementLocation
from app.db.models.customer_requirement_property_preference import (
    CustomerRequirementPropertyPreference,
)
from app.db.models.follow_up import FollowUp
from app.db.models.lead import Lead
from app.db.models.next_best_action import NextBestActionRecommendation
from app.db.models.outbox_event import OutboxEvent
from app.db.models.property import Property
from app.db.models.requirement_match_run import RequirementMatchRun
from app.db.models.requirement_match_run_result import RequirementMatchRunResult
from app.db.models.requirement_property_shortlist import RequirementPropertyShortlist
from app.db.session import SessionLocal, get_db_session
from app.governance.service import set_capability_enabled
from app.properties.matching_service import (
    get_matching_properties,
    get_property_match_results,
)
from app.requirements import match_evaluation_service as service
from app.requirements.match_evaluation_service import (
    EvaluationError,
    evaluate_requirement,
    is_run_stale,
    latest_evaluation,
    record_feedback,
)
from app.requirements.match_rules import (
    ELIGIBLE,
    EXCLUDED,
    INSUFFICIENT_DATA,
    classify,
    rank,
)
from tests.agents_support import (  # noqa: F401
    AGENT_CAPABILITY,
    create_draft,
    create_user_in,
    enable_ai,
    keyring,
    publish,
)
from tests.test_team_api import TestingSessionLocal, create_owner_manager

MANAGE = ("requirements.read", "requirements.update", "properties.read", "leads.read", "agents.read", "agents.manage",
          "agents.run", "agents.approve", "governance.consent.read")


def _cleanup_org(organization_ids) -> None:
    with SessionLocal() as db:
        for organization_id in organization_ids:
            for model in (NextBestActionRecommendation, RequirementMatchRunResult, RequirementMatchRun,
                          RequirementPropertyShortlist, CustomerRequirementPropertyPreference,
                          CustomerRequirementLocation, CustomerRequirementHistory, CustomerRequirement, FollowUp,
                          Activity, Lead, Contact, Property, AgentExecutionStep, AgentExecution, AgentVersion, Agent,
                          OutboxEvent, AuditEvent):
                db.execute(delete(model).where(model.organization_id == organization_id))
        db.commit()


@pytest.fixture
def orgs() -> Iterator[SimpleNamespace]:
    owner, org = create_owner_manager(permissions=MANAGE)
    other, other_org = create_owner_manager(permissions=MANAGE)
    member = create_user_in(org, permissions=MANAGE)
    reader = create_user_in(org, permissions=("requirements.read", "properties.read"))
    yield SimpleNamespace(owner=owner, org=org, member=member, reader=reader, other=other, other_org=other_org)
    _cleanup_org((org.id, other_org.id))


# --- helpers ----------------------------------------------------------------------------------------


def _requirement(organization_id, *, transaction_type: str | None = "SALE", budget_max: str | None = "9000000",
                 budget_min: str | None = None, city: str | None = "Chennai", locality: str | None = "Velachery",
                 property_type: str | None = "APARTMENT", bhk_min: int | None = 2, bhk_max: int | None = 3,
                 lead_id: uuid.UUID | None = None) -> uuid.UUID:
    with SessionLocal() as db:
        requirement = CustomerRequirement(organization_id=organization_id, status="ACTIVE", is_active=True,
                                          transaction_type=transaction_type, lead_id=lead_id,
                                          budget_min=Decimal(budget_min) if budget_min else None,
                                          budget_max=Decimal(budget_max) if budget_max else None,
                                          budget_currency="INR" if (budget_min or budget_max) else None)
        db.add(requirement)
        db.flush()
        if city and locality:
            db.add(CustomerRequirementLocation(organization_id=organization_id, customer_requirement_id=requirement.id,
                                               city=city, locality=locality, is_active=True))
        if property_type:
            db.add(CustomerRequirementPropertyPreference(organization_id=organization_id,
                                                         customer_requirement_id=requirement.id,
                                                         property_type=property_type, bhk_min=bhk_min, bhk_max=bhk_max,
                                                         is_active=True))
        db.commit()
        return requirement.id


def _property(organization_id, **fields) -> uuid.UUID:
    values = {"status": Property.STATUS_AVAILABLE, "transaction_type": Property.TRANSACTION_TYPE_SALE,
              "price": Decimal("7000000.00"), "currency": "INR", "city": "Chennai", "locality": "Velachery",
              "property_type": "APARTMENT", "bhk": 2}
    values.update(fields)
    with SessionLocal() as db:
        record = Property(organization_id=organization_id, **values)
        db.add(record)
        db.commit()
        return record.id


def _set_property(property_id, **fields) -> None:
    with SessionLocal() as db:
        record = db.get(Property, property_id)
        for key, value in fields.items():
            setattr(record, key, value)
        db.commit()


def _evaluate(orgs, *, user=None):
    with SessionLocal() as db:
        run, created = evaluate_requirement(db, organization_id=orgs.org.id, actor_id=(user or orgs.member).id,
                                            requirement_id=orgs.requirement_id)
        db.commit()
        return run.id, created


def _latest(orgs, *, user=None):
    with SessionLocal() as db:
        latest = latest_evaluation(db, organization_id=orgs.org.id, actor_id=(user or orgs.member).id,
                                   requirement_id=orgs.requirement_id)
        if latest is None:
            return None
        return {"run": latest["run"].id, "stale": latest["stale"],
                "results": {str(r.property_id): r for r in latest["results"]},
                "recommendations": latest["recommendations"]}


def _client(user, organization) -> TestClient:
    app = FastAPI()
    app.include_router(matching_router)

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


@pytest.fixture
def req(orgs) -> SimpleNamespace:
    """An active SALE requirement for a 2 to 3 BHK apartment in Velachery, Chennai, budget up to 90 lakh."""
    orgs.requirement_id = _requirement(orgs.org.id)
    return orgs


# --- matching engine: hard constraints and missing data ----------------------------------------------


def _criteria(results, property_id) -> dict[str, str]:
    result = next(item for item in results if item.property.id == property_id)
    return {criterion.criterion: criterion.status for criterion in result.criteria}


def test_a_sale_requirement_excludes_a_rent_property_and_says_why(req):
    rent = _property(req.org.id, transaction_type=Property.TRANSACTION_TYPE_RENT, price=None, rent=Decimal("40000.00"))
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=req.org.id, requirement_id=req.requirement_id)
        assert _criteria(results, rent)["TRANSACTION_TYPE"] == "MISMATCH"
        classification = classify(db.get(CustomerRequirement, req.requirement_id), next(r for r in results if r.property.id == rent))
        assert classification.eligibility == EXCLUDED
        assert any("rent" in reason for reason in classification.exclusion_reasons)


def test_a_matching_transaction_type_is_an_explained_match(req):
    sale = _property(req.org.id)
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=req.org.id, requirement_id=req.requirement_id)
        assert _criteria(results, sale)["TRANSACTION_TYPE"] == "MATCH"


def test_a_requirement_without_a_transaction_type_keeps_its_original_criteria(orgs):
    requirement_id = _requirement(orgs.org.id, transaction_type=None)
    _property(orgs.org.id)
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=orgs.org.id, requirement_id=requirement_id)
        assert "TRANSACTION_TYPE" not in _criteria(results, results[0].property.id)
        assert results[0].overall_match is True


def test_a_property_without_a_recorded_transaction_type_is_not_eligible_because_data_is_missing(req):
    unknown = _property(req.org.id, transaction_type=None)
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=req.org.id, requirement_id=req.requirement_id)
        result = next(r for r in results if r.property.id == unknown)
        assert result.overall_match is False
        assert _criteria(results, unknown)["TRANSACTION_TYPE"] == "UNKNOWN"
        assert classify(db.get(CustomerRequirement, req.requirement_id), result).eligibility == INSUFFICIENT_DATA
        assert all(item.property.id != unknown for item in get_matching_properties(
            db, organization_id=req.org.id, requirement_id=req.requirement_id))


def test_a_property_without_a_city_is_unknown_for_location_not_a_mismatch(req):
    no_city = _property(req.org.id, city=None)
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=req.org.id, requirement_id=req.requirement_id)
        assert _criteria(results, no_city)["LOCATION"] == "UNKNOWN"
        assert next(r for r in results if r.property.id == no_city).overall_match is False


def test_a_property_without_bhk_is_unknown_when_the_preference_has_bhk_bounds(req):
    no_bhk = _property(req.org.id, bhk=None)
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=req.org.id, requirement_id=req.requirement_id)
        assert _criteria(results, no_bhk)["PROPERTY_TYPE_AND_BHK"] == "UNKNOWN"


def test_a_property_above_the_budget_is_excluded(req):
    expensive = _property(req.org.id, price=Decimal("12000000.00"))
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=req.org.id, requirement_id=req.requirement_id)
        assert _criteria(results, expensive)["BUDGET"] == "MISMATCH"
        assert next(r for r in results if r.property.id == expensive).overall_match is False


def test_a_lease_property_against_a_budget_is_insufficient_data_not_eligible(orgs):
    requirement_id = _requirement(orgs.org.id, transaction_type=None)
    lease = _property(orgs.org.id, transaction_type=Property.TRANSACTION_TYPE_LEASE, price=None, rent=None)
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=orgs.org.id, requirement_id=requirement_id)
        assert _criteria(results, lease)["BUDGET"] == "UNKNOWN"
        assert next(r for r in results if r.property.id == lease).overall_match is False


def test_unavailable_properties_never_appear(req):
    sold = _property(req.org.id, status=Property.STATUS_SOLD)
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=req.org.id, requirement_id=req.requirement_id)
        assert all(item.property.id != sold for item in results)


def test_every_criterion_carries_a_plain_explanation(req):
    _property(req.org.id)
    _property(req.org.id, city=None)
    with SessionLocal() as db:
        results = get_property_match_results(db, organization_id=req.org.id, requirement_id=req.requirement_id)
        assert results
        assert all(criterion.explanation.strip() for result in results for criterion in result.criteria)


# --- ranking, explanation and reproducibility --------------------------------------------------------


def test_eligible_properties_are_ranked_and_the_others_are_not(req):
    best = _property(req.org.id, price=Decimal("6000000.00"))
    _property(req.org.id, price=Decimal("8000000.00"))
    _property(req.org.id, transaction_type=Property.TRANSACTION_TYPE_RENT, price=None, rent=Decimal("1.00"))
    _property(req.org.id, city=None)
    _evaluate(req)
    latest = _latest(req)
    eligible = [row for row in latest["results"].values() if row.eligibility == ELIGIBLE]
    assert sorted(row.rank for row in eligible) == [1, 2]
    assert latest["results"][str(best)].rank == 1
    assert all(row.rank is None for row in latest["results"].values() if row.eligibility != ELIGIBLE)


def test_the_ranking_basis_names_the_rule_and_the_order_used(req):
    _property(req.org.id)
    _evaluate(req)
    row = next(iter(_latest(req)["results"].values()))
    basis = row.ranking_basis
    assert basis["rule"] == "property-match-v1"
    assert basis["order"] == ["configured_matches", "budget_headroom", "listing_created_at", "property_id"]
    assert basis["eligibility"] == ELIGIBLE
    assert isinstance(basis["matched_factors"], list) and basis["matched_factors"]


def test_explanations_separate_matched_unmatched_missing_and_exclusions(req):
    _property(req.org.id, price=Decimal("20000000.00"))
    missing_city = _property(req.org.id, city=None)
    _evaluate(req)
    rows = _latest(req)["results"]
    expensive = next(row for row in rows.values() if row.eligibility == EXCLUDED)
    assert expensive.ranking_basis["exclusion_reasons"]
    assert expensive.ranking_basis["unmatched_factors"]
    unknown = rows[str(missing_city)]
    assert unknown.eligibility == INSUFFICIENT_DATA
    assert unknown.ranking_basis["missing_information"]
    assert unknown.ranking_basis["exclusion_reasons"] == []


def test_ranking_is_reproducible_for_the_same_inputs(req):
    for price in ("6500000.00", "6500000.00", "7500000.00"):
        _property(req.org.id, price=Decimal(price))
    with SessionLocal() as db:
        requirement = db.get(CustomerRequirement, req.requirement_id)
        first = [(r.property.id, c.eligibility, p) for r, c, p, _ in rank(requirement, get_property_match_results(
            db, organization_id=req.org.id, requirement_id=req.requirement_id))]
        second = [(r.property.id, c.eligibility, p) for r, c, p, _ in rank(requirement, get_property_match_results(
            db, organization_id=req.org.id, requirement_id=req.requirement_id))]
    assert first == second


def test_a_score_is_never_called_a_probability(req):
    _property(req.org.id)
    run_id, _ = _evaluate(req)
    with SessionLocal() as db:
        run = db.get(RequirementMatchRun, run_id)
        rows = db.scalars(select(RequirementMatchRunResult).where(RequirementMatchRunResult.match_run_id == run_id)).all()
        text = json.dumps([run.criteria_snapshot, *[row.ranking_basis for row in rows]]).lower()
    assert "probability" not in text


# --- evaluation: run history, duplicates, staleness and concurrency -----------------------------------


def test_an_evaluation_stores_the_rule_version_fingerprint_and_ranks(req):
    _property(req.org.id)
    run_id, created = _evaluate(req)
    assert created is True
    with SessionLocal() as db:
        run = db.get(RequirementMatchRun, run_id)
        assert run.ruleset_version == "property-match-v1"
        assert run.input_hash and len(run.input_hash) == 64
        assert is_run_stale(db, organization_id=req.org.id, run=run) is False


def test_repeating_an_evaluation_with_unchanged_inputs_returns_the_stored_run(req):
    _property(req.org.id)
    first, created_first = _evaluate(req)
    second, created_second = _evaluate(req)
    assert created_first is True and created_second is False and first == second
    with SessionLocal() as db:
        assert len(db.scalars(select(RequirementMatchRun.id).where(
            RequirementMatchRun.customer_requirement_id == req.requirement_id)).all()) == 1


def test_a_requirement_change_makes_the_old_run_stale_and_a_new_run_is_created(req):
    _property(req.org.id)
    old, _ = _evaluate(req)
    with SessionLocal() as db:
        requirement = db.get(CustomerRequirement, req.requirement_id)
        requirement.budget_max = Decimal("6000000.00")
        db.commit()
    with SessionLocal() as db:
        assert is_run_stale(db, organization_id=req.org.id, run=db.get(RequirementMatchRun, old)) is True
    new, created = _evaluate(req)
    assert created is True and new != old


def test_a_property_status_change_makes_the_run_stale_and_removes_the_property(req):
    prop = _property(req.org.id)
    _evaluate(req)
    _set_property(prop, status=Property.STATUS_SOLD)
    assert _latest(req)["stale"] is True
    _evaluate(req)
    assert str(prop) not in _latest(req)["results"]


def test_a_property_update_changes_the_fingerprint(req):
    prop = _property(req.org.id, price=Decimal("7000000.00"))
    _evaluate(req)
    _set_property(prop, price=Decimal("8500000.00"))
    assert _latest(req)["stale"] is True


def test_concurrent_evaluations_of_one_requirement_store_one_run(req):
    _property(req.org.id)
    barrier = threading.Barrier(3)

    def run_once():
        barrier.wait()
        with SessionLocal() as db:
            _, created = evaluate_requirement(db, organization_id=req.org.id, actor_id=req.member.id,
                                                requirement_id=req.requirement_id)
            db.commit()
            return created

    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = list(pool.map(lambda _: run_once(), range(3)))
    assert outcomes.count(True) == 1
    with SessionLocal() as db:
        assert len(db.scalars(select(RequirementMatchRun.id).where(
            RequirementMatchRun.customer_requirement_id == req.requirement_id)).all()) == 1


def test_a_failure_while_recording_recommendations_leaves_no_partial_run(req, monkeypatch):
    _property(req.org.id)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(service, "generate_recommendations", boom)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError):
            evaluate_requirement(db, organization_id=req.org.id, actor_id=req.member.id, requirement_id=req.requirement_id)
        db.rollback()
    with SessionLocal() as db:
        assert db.scalars(select(RequirementMatchRun.id).where(
            RequirementMatchRun.customer_requirement_id == req.requirement_id)).all() == []


def test_an_inactive_requirement_cannot_be_evaluated(req):
    with SessionLocal() as db:
        requirement = db.get(CustomerRequirement, req.requirement_id)
        requirement.is_active = False
        db.commit()
    with SessionLocal() as db, pytest.raises(EvaluationError) as error:
        evaluate_requirement(db, organization_id=req.org.id, actor_id=req.member.id, requirement_id=req.requirement_id)
    assert error.value.reason == "requirement_not_found"


# --- next-best-action recommendations --------------------------------------------------------------------


def _categories(latest) -> set[str]:
    return {row.category for row in latest["recommendations"]}


def test_missing_requirement_details_are_requested_as_missing_information(orgs):
    requirement_id = _requirement(orgs.org.id, transaction_type=None, budget_max=None, city=None, locality=None,
                                  property_type=None)
    orgs.requirement_id = requirement_id
    _property(orgs.org.id)
    _evaluate(orgs)
    recommendation = next(row for row in _latest(orgs)["recommendations"] if row.category == "request_missing_information")
    assert recommendation.basis == "missing_information"
    assert set(recommendation.facts["missing"]) == {"transaction_type", "budget", "location", "property_preference"}


def test_an_eligible_property_is_recommended_for_review_with_its_rank(req):
    prop = _property(req.org.id)
    _evaluate(req)
    recommendation = next(row for row in _latest(req)["recommendations"] if row.category == "review_property")
    assert recommendation.subject_property_id == prop
    assert recommendation.basis == "deterministic_match"
    assert recommendation.facts["rank"] == 1


def test_a_shortlisted_property_is_recommended_for_a_site_visit_not_a_booking(req):
    prop = _property(req.org.id)
    with SessionLocal() as db:
        db.add(RequirementPropertyShortlist(organization_id=req.org.id, customer_requirement_id=req.requirement_id,
                                            property_id=prop, created_by_user_id=req.member.id))
        db.commit()
    _evaluate(req)
    categories = _categories(_latest(req))
    assert "arrange_site_visit" in categories
    assert "review_property" not in categories
    visit = next(row for row in _latest(req)["recommendations"] if row.category == "arrange_site_visit")
    assert "No visit is booked" in visit.summary


def test_a_lead_without_a_pending_follow_up_is_recommended_a_follow_up(req):
    with SessionLocal() as db:
        contact = Contact(organization_id=req.org.id, first_name="Asha", last_name="Rao", email="asha@example.test",
                          is_active=True)
        db.add(contact)
        db.flush()
        lead = Lead(organization_id=req.org.id, contact_id=contact.id, status="NEW", interest="HIGH", is_active=True)
        db.add(lead)
        db.flush()
        with db.no_autoflush:
            requirement = db.get(CustomerRequirement, req.requirement_id)
            requirement.lead_id = lead.id
        db.commit()
    _property(req.org.id)
    _evaluate(req)
    recommendation = next(row for row in _latest(req)["recommendations"] if row.category == "follow_up_lead")
    assert recommendation.basis == "verified_fact"
    assert recommendation.facts["pending_follow_ups"] == 0


def test_no_follow_up_is_recommended_when_one_is_pending(req):
    with SessionLocal() as db:
        contact = Contact(organization_id=req.org.id, first_name="Asha", last_name="Rao", email="asha2@example.test",
                          is_active=True)
        db.add(contact)
        db.flush()
        lead = Lead(organization_id=req.org.id, contact_id=contact.id, status="NEW", interest="HIGH", is_active=True)
        db.add(lead)
        db.flush()
        db.add(FollowUp(organization_id=req.org.id, lead_id=lead.id, owner_user_id=req.member.id, follow_up_type="CALL",
                        title="Call", due_at=datetime.now(UTC) + timedelta(days=1), status=FollowUp.STATUS_PENDING))
        with db.no_autoflush:
            requirement = db.get(CustomerRequirement, req.requirement_id)
            requirement.lead_id = lead.id
        db.commit()
    _property(req.org.id)
    _evaluate(req)
    assert "follow_up_lead" not in _categories(_latest(req))


def test_when_nothing_is_eligible_a_person_is_asked_to_decide(req):
    _property(req.org.id, price=Decimal("50000000.00"))
    _evaluate(req)
    escalation = next(row for row in _latest(req)["recommendations"] if row.category == "escalate_to_human")
    assert escalation.basis == "deterministic_match"
    assert escalation.facts["eligible_count"] == 0


def test_when_properties_cannot_be_checked_the_escalation_names_missing_data(req):
    _property(req.org.id, transaction_type=None)
    _evaluate(req)
    escalation = next(row for row in _latest(req)["recommendations"] if row.category == "escalate_to_human")
    assert escalation.basis == "missing_information"
    assert escalation.facts["insufficient_data_count"] == 1


def test_a_recommendation_is_decided_once_and_the_history_keeps_both_steps(req):
    _property(req.org.id)
    _evaluate(req)
    row = next(item for item in _latest(req)["recommendations"] if item.category == "review_property")
    with SessionLocal() as db:
        accepted = record_feedback(db, organization_id=req.org.id, actor_id=req.member.id, recommendation_id=row.id,
                                   decision="accepted", reason="Shows the customer this flat.")
        db.commit()
        assert accepted.status == "accepted" and accepted.decided_by_user_id == req.member.id
        assert [item["to"] for item in accepted.history] == ["accepted"]
    with SessionLocal() as db, pytest.raises(EvaluationError) as invalid:
        record_feedback(db, organization_id=req.org.id, actor_id=req.member.id, recommendation_id=row.id,
                        decision="accepted", reason=None)
    assert invalid.value.reason == "invalid_transition"
    with SessionLocal() as db:
        done = record_feedback(db, organization_id=req.org.id, actor_id=req.member.id, recommendation_id=row.id,
                               decision="done", reason=None)
        db.commit()
        assert done.status == "done" and [item["to"] for item in done.history] == ["accepted", "done"]


def test_a_stale_recommendation_cannot_be_decided(req):
    prop = _property(req.org.id)
    _evaluate(req)
    row = next(item for item in _latest(req)["recommendations"] if item.category == "review_property")
    _set_property(prop, status=Property.STATUS_SOLD)
    with SessionLocal() as db, pytest.raises(EvaluationError) as error:
        record_feedback(db, organization_id=req.org.id, actor_id=req.member.id, recommendation_id=row.id,
                        decision="accepted", reason=None)
    assert error.value.reason == "recommendation_stale"
    assert _latest(req)["stale"] is True


def test_re_evaluating_with_the_same_inputs_does_not_duplicate_recommendations(req):
    _property(req.org.id)
    _evaluate(req)
    count = len(_latest(req)["recommendations"])
    _evaluate(req)
    assert len(_latest(req)["recommendations"]) == count


# --- API: permissions, tenancy, transaction type ---------------------------------------------------------


def test_readers_can_view_but_not_evaluate_or_decide(req):
    _property(req.org.id)
    _evaluate(req)
    client = _client(req.reader, req.org)
    base = f"/api/v1/customer-requirements/{req.requirement_id}/match-evaluations"
    assert client.get(f"{base}/latest").status_code == 200
    assert client.post(base).status_code == 403
    row = next(iter(_latest(req)["recommendations"]))
    assert client.post(f"/api/v1/next-best-actions/{row.id}/feedback", json={"decision": "dismissed"}).status_code == 403
    assert client.put(f"/api/v1/customer-requirements/{req.requirement_id}/transaction-type",
                      json={"transaction_type": "RENT"}).status_code == 403


def test_the_api_evaluates_then_reports_the_stored_run_with_its_stale_flag(req):
    _property(req.org.id)
    client = _client(req.member, req.org)
    base = f"/api/v1/customer-requirements/{req.requirement_id}/match-evaluations"
    first = client.post(base)
    assert first.status_code == 201 and first.json()["created"] is True
    second = client.post(base)
    assert second.status_code == 200 and second.json()["run_id"] == first.json()["run_id"]
    latest = client.get(f"{base}/latest").json()
    assert latest["stale"] is False
    assert latest["next_best_action_ruleset_version"] == "next-best-action-v1"
    assert "not a probability" in latest["disclaimer"]


def test_another_organization_cannot_see_evaluate_or_decide_on_this_requirement(req):
    _property(req.org.id)
    _evaluate(req)
    row = next(iter(_latest(req)["recommendations"]))
    other = _client(req.other, req.other_org)
    base = f"/api/v1/customer-requirements/{req.requirement_id}/match-evaluations"
    assert other.get(f"{base}/latest").status_code == 404
    assert other.post(base).status_code == 404
    assert other.post(f"/api/v1/next-best-actions/{row.id}/feedback", json={"decision": "dismissed"}).status_code == 404


def test_the_transaction_type_is_recorded_on_the_requirement_and_refuses_unknown_values(req):
    client = _client(req.member, req.org)
    url = f"/api/v1/customer-requirements/{req.requirement_id}/transaction-type"
    assert client.put(url, json={"transaction_type": "RENT"}).json() == {"id": str(req.requirement_id),
                                                                          "transaction_type": "RENT"}
    assert client.put(url, json={"transaction_type": "BARTER"}).status_code == 422
    with SessionLocal() as db:
        assert db.get(CustomerRequirement, req.requirement_id).transaction_type == "RENT"


def test_a_transaction_type_change_is_used_by_the_next_evaluation(req):
    _property(req.org.id)  # a SALE property
    _evaluate(req)
    client = _client(req.member, req.org)
    client.put(f"/api/v1/customer-requirements/{req.requirement_id}/transaction-type", json={"transaction_type": "RENT"})
    _evaluate(req)
    latest = _latest(req)
    assert all(row.eligibility == EXCLUDED for row in latest["results"].values())


def test_the_deterministic_matching_works_with_ai_disabled(req):
    _property(req.org.id)
    run_id, created = _evaluate(req)
    assert created is True and run_id is not None


def test_recommendation_facts_only_reference_source_records(req):
    _property(req.org.id)
    _evaluate(req)
    for row in _latest(req)["recommendations"]:
        assert "source" in row.facts or row.category == "request_missing_information"


# --- agent integration -------------------------------------------------------------------------------------


@pytest.fixture
def agent_world(monkeypatch, keyring) -> Iterator[SimpleNamespace]:  # noqa: F811
    owner, org = create_owner_manager(permissions=MANAGE)
    other, other_org = create_owner_manager(permissions=MANAGE)
    member = create_user_in(org, permissions=MANAGE)
    monkeypatch.setenv("PROVIDER_LIVE_ADAPTERS_ENABLED", "true")
    get_settings.cache_clear()
    enable_ai(monkeypatch, org, owner)
    world = SimpleNamespace(owner=owner, org=org, member=member, other=other, other_org=other_org)
    yield world
    _cleanup_org((org.id, other_org.id))


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


def test_the_property_matching_template_is_valid_for_the_approved_registry():
    canonical = normalise_configuration(TEMPLATES[PROPERTY_MATCHING]["configuration"],
                                        registered_tools=frozenset(DEFAULT_REGISTRY.keys()))
    assert canonical["steps"][0]["action"] == "matching.evaluate"


def test_the_matching_agent_runs_the_engine_and_records_its_provenance(agent_world):
    requirement_id = _requirement(agent_world.org.id)
    _property(agent_world.org.id)
    draft = create_draft(agent_world, cfg=TEMPLATES[PROPERTY_MATCHING]["configuration"], name=f"match-{uuid.uuid4().hex[:6]}")
    publish(agent_world, draft["id"])
    with SessionLocal() as db:
        execution, _ = create_execution(
            db, organization_id=agent_world.org.id, agent_id=draft["id"],
            user_context=CurrentUserContext(user=_user(agent_world.member.id)),
            input_values={"requirement_id": str(requirement_id)}, idempotency_key=f"k-{uuid.uuid4().hex}",
        )
        db.commit()
        execution_id = execution.id
    _drain(execution_id, agent_world.org.id)
    with SessionLocal() as db:
        finished = db.get(AgentExecution, execution_id)
        assert finished.status == "succeeded", finished.failure_reason
        run = db.scalar(select(RequirementMatchRun).where(RequirementMatchRun.customer_requirement_id == requirement_id))
        assert run is not None and run.actor_id == agent_world.member.id


def test_the_matching_agent_is_refused_while_ai_is_switched_off(agent_world):
    requirement_id = _requirement(agent_world.org.id)
    draft = create_draft(agent_world, cfg=TEMPLATES[PROPERTY_MATCHING]["configuration"], name=f"match-{uuid.uuid4().hex[:6]}")
    publish(agent_world, draft["id"])
    with SessionLocal() as db:
        set_capability_enabled(db, organization_id=agent_world.org.id, actor_user_id=agent_world.owner.id,
                               capability_key=AGENT_CAPABILITY, is_enabled=False)
        db.commit()
    from app.agents.service import AgentError
    with SessionLocal() as db, pytest.raises(AgentError) as error:
        create_execution(db, organization_id=agent_world.org.id, agent_id=draft["id"],
                         user_context=CurrentUserContext(user=_user(agent_world.member.id)),
                         input_values={"requirement_id": str(requirement_id)}, idempotency_key=f"k-{uuid.uuid4().hex}")
    assert error.value.reason == "not_permitted_now"


def _user(user_id):
    from app.db.models.user import User
    with SessionLocal() as db:
        row = db.get(User, user_id)
        db.expunge(row)
        return row

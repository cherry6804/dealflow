"""The real-estate CRM journey through the real API, and the release-blocking rules it depends on (DFR1-008).

The journey runs contact to lead, requirement, property matching, pipeline, follow-ups, site visit, deal, commission and history
through the same routers the application serves. It runs on the test database with real tenant resolution and permissions.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import get_db_session
from app.main import create_app
from tests.test_deals_api import (
    create_authorized_user,
    create_membership,
    create_user,
    grant_permission,
)
from tests.test_team_api import TestingSessionLocal

ALL_CRM_PERMISSIONS = (
    "contacts.create",
    "contacts.read",
    "contacts.update",
    "leads.create",
    "leads.read",
    "leads.update",
    "requirements.create",
    "requirements.read",
    "requirements.update",
    "properties.create",
    "properties.read",
    "properties.update",
    "deals.create",
    "deals.read",
    "deals.update",
    "deals.close",
    "commission.create",
    "commission.read",
    "commission.update",
)


def _session() -> Iterator:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def _client(user_id, organization_id) -> TestClient:
    """A client for one user in one organization. Tenant and permission checks run on every request."""
    app = create_app()
    app.dependency_overrides[get_db_session] = _session

    def current_user() -> CurrentUserContext:
        db = TestingSessionLocal()
        try:
            return CurrentUserContext(user=db.get(User, user_id))
        finally:
            db.close()

    app.dependency_overrides[get_current_user_context] = current_user
    client = TestClient(app)
    client.headers.update({"X-Organization-ID": str(organization_id)})
    return client


@pytest.fixture
def org():
    """Two organizations, each with an owner who holds every CRM permission, and a reader with only leads.read."""
    with TestingSessionLocal() as db:
        owner, org_a = create_authorized_user(db, permission_keys=ALL_CRM_PERMISSIONS)
        other, org_b = create_authorized_user(db, permission_keys=ALL_CRM_PERMISSIONS)
        reader, org_reader = create_authorized_user(db, permission_keys=("leads.read",))
        ids = (owner.id, org_a.id, other.id, org_b.id, reader.id, org_reader.id)
    yield ids


def _ok(response, expected: int = 200) -> dict:
    assert response.status_code == expected, response.text
    return response.json()


def _property(client: TestClient, *, transaction_type: str = "SALE", price: str = "9500000") -> dict:
    prop = _ok(client.post("/api/v1/properties", json={}), 201)
    _ok(client.patch(f"/api/v1/properties/{prop['id']}/commercial",
                     json={"transaction_type": transaction_type, "price": price, "currency": "INR"}))
    _ok(client.patch(f"/api/v1/properties/{prop['id']}/location-attributes",
                     json={"city": "Bengaluru", "locality": "Whitefield", "property_type": "APARTMENT", "bhk": 2}))
    _ok(client.patch(f"/api/v1/properties/{prop['id']}/status", json={"status": "AVAILABLE"}))
    return prop


def _lead(client: TestClient, contact_id: str) -> dict:
    return _ok(client.post("/api/v1/leads", json={
        "contact_id": contact_id,
        "interest": "HIGH",
        "next_action": "Call to qualify",
        "next_action_at": "2030-01-02T10:00:00Z",
    }), 201)


def _deal(client: TestClient, *, customer_profile_id: str, property_id: str, lead_id: str | None = None,
          expected: str = "9500000") -> dict:
    body = {"customer_profile_id": customer_profile_id, "property_id": property_id,
            "expected_value": expected, "currency": "INR"}
    if lead_id is not None:
        body["lead_id"] = lead_id
    return _ok(client.post("/api/v1/deals", json=body), 201)


def _advance(client: TestClient, deal_id: str, stages: list[str]) -> None:
    for stage in stages:
        _ok(client.patch(f"/api/v1/deals/{deal_id}/stage", json={"stage": stage, "reason": "Progressed in the pipeline."}))


def test_the_real_estate_journey_runs_end_to_end(org):
    owner_id, org_a_id, *_ = org
    client = _client(owner_id, org_a_id)

    # 1. Contact.
    contact = _ok(client.post("/api/v1/contacts", json={"first_name": "Asha", "last_name": "Rao",
                                                         "email": "asha@example.com", "phone": "+911234567890"}), 201)

    # 2. Lead, then pipeline status changes.
    lead = _lead(client, contact["id"])
    for status in ("CONTACTED", "QUALIFIED", "MATCHING", "VISIT"):
        _ok(client.patch(f"/api/v1/leads/{lead['id']}", json={"status": status, "next_action": f"Next: {status}"}))

    # 3. Requirement, captured with location and preference, linked to the lead.
    requirement = _ok(client.post("/api/v1/customer-requirements", json={}), 201)
    _ok(client.post(f"/api/v1/customer-requirements/{requirement['id']}/locations",
                    json={"city": "Bengaluru", "locality": "Whitefield"}), 201)
    _ok(client.post(f"/api/v1/customer-requirements/{requirement['id']}/property-preferences",
                    json={"property_type": "APARTMENT", "bhk_min": 2, "bhk_max": 3}), 201)
    _ok(client.patch(f"/api/v1/customer-requirements/{requirement['id']}/association", json={"lead_id": lead["id"]}))

    # 4. Real inventory matches the requirement.
    prop = _property(client)
    matches = _ok(client.get(f"/api/v1/customer-requirements/{requirement['id']}/matches"))
    assert prop["id"] in {item["id"] for item in matches}

    # 5. Pipeline: the lead moves on; the follow-up is scheduled, completed and rescheduled.
    follow_up = _ok(client.post(f"/api/v1/leads/{lead['id']}/follow-ups", json={
        "follow_up_type": "CALL", "title": "Call back", "due_at": "2030-01-05T10:00:00Z"}), 201)
    _ok(client.patch(f"/api/v1/follow-ups/{follow_up['id']}/reschedule", json={"due_at": "2030-01-06T10:00:00Z"}))
    _ok(client.post(f"/api/v1/follow-ups/{follow_up['id']}/complete", json={}))

    # 6. Site visit, recorded with its attendance.
    visit = _ok(client.post("/api/v1/site-visits", json={
        "property_id": prop["id"], "lead_id": lead["id"], "scheduled_at": "2030-01-07T10:00:00Z"}), 201)
    recorded = _ok(client.patch(f"/api/v1/site-visits/{visit['id']}/attendance", json={
        "status": "COMPLETED", "outcome": "INTERESTED", "feedback": "Liked the layout."}))
    assert recorded["status"] == "COMPLETED"

    # 7. Deal, progressed to booking and closed as won with a reason.
    profile = _ok(client.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)
    deal = _deal(client, customer_profile_id=profile["id"], property_id=prop["id"], lead_id=lead["id"])
    _advance(client, deal["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])
    _ok(client.patch(f"/api/v1/deals/{deal['id']}/stage", json={"stage": "CLOSED_WON", "reason": "Sale agreement signed."}))

    # 8. Commission: 2 percent of the deal value, calculated from the recorded terms.
    commission = _ok(client.post(f"/api/v1/deals/{deal['id']}/commissions", json={
        "commission_type": "PERCENTAGE", "rate_percent": "2", "currency": "INR"}), 201)
    assert Decimal(str(commission["calculated_amount"])) == Decimal("190000.00")

    # 9. Inventory: the won property is sold, so it leaves the matches.
    assert _ok(client.get("/api/v1/properties/search"))["items"][0]["status"] == "SOLD"
    assert prop["id"] not in {item["id"] for item in _ok(client.get(f"/api/v1/customer-requirements/{requirement['id']}/matches"))}

    # 10. History: the deal's stage changes, oldest first, and the lead's activity timeline.
    history = _ok(client.get(f"/api/v1/deals/{deal['id']}/stage-history"))["items"]
    assert [(row["from_stage"], row["to_stage"]) for row in history] == [
        ("NEW", "QUALIFICATION"), ("QUALIFICATION", "NEGOTIATION"), ("NEGOTIATION", "BOOKING"), ("BOOKING", "CLOSED_WON"),
    ]
    assert history[-1]["reason"] == "Sale agreement signed."
    activity = _ok(client.get(f"/api/v1/leads/{lead['id']}/activities"))["items"]
    assert any(item["activity_type"] == "STATUS_CHANGE" for item in activity)
    assert _ok(client.get(f"/api/v1/customer-requirements/{requirement['id']}/history"))["items"]


def test_a_sold_property_cannot_take_a_new_deal_or_be_sold_twice(org):
    owner_id, org_a_id, *_ = org
    client = _client(owner_id, org_a_id)
    contact = _ok(client.post("/api/v1/contacts", json={"first_name": "Ravi", "last_name": "Kumar"}), 201)
    profile = _ok(client.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)
    prop = _property(client)

    first = _deal(client, customer_profile_id=profile["id"], property_id=prop["id"])
    second = _deal(client, customer_profile_id=profile["id"], property_id=prop["id"])
    _advance(client, first["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])
    _advance(client, second["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])
    _ok(client.patch(f"/api/v1/deals/{first['id']}/stage", json={"stage": "CLOSED_WON", "reason": "Signed."}))

    # The second open deal cannot close as won once the property is sold.
    refused = client.patch(f"/api/v1/deals/{second['id']}/stage", json={"stage": "CLOSED_WON", "reason": "Also signed."})
    assert refused.status_code == 409
    assert "no longer available" in refused.json()["error"]["message"]

    # A new deal cannot start on the sold property.
    blocked = client.post("/api/v1/deals", json={"customer_profile_id": profile["id"], "property_id": prop["id"],
                                                  "expected_value": "9500000", "currency": "INR"})
    assert blocked.status_code == 409


def test_a_rental_closes_as_rented_and_a_lost_deal_leaves_inventory_available(org):
    owner_id, org_a_id, *_ = org
    client = _client(owner_id, org_a_id)
    contact = _ok(client.post("/api/v1/contacts", json={"first_name": "Meera", "last_name": "Iyer"}), 201)
    profile = _ok(client.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)

    rental = _property(client, transaction_type="RENT", price="45000")
    won = _deal(client, customer_profile_id=profile["id"], property_id=rental["id"], expected="540000")
    _advance(client, won["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])
    _ok(client.patch(f"/api/v1/deals/{won['id']}/stage", json={"stage": "CLOSED_WON", "reason": "Lease signed."}))
    rented = [item for item in _ok(client.get("/api/v1/properties/search"))["items"] if item["id"] == rental["id"]]
    assert rented[0]["status"] == "RENTED"

    other = _property(client)
    lost = _deal(client, customer_profile_id=profile["id"], property_id=other["id"])
    _advance(client, lost["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])
    _ok(client.patch(f"/api/v1/deals/{lost['id']}/stage", json={"stage": "CLOSED_LOST", "reason": "Buyer withdrew."}))
    still = [item for item in _ok(client.get("/api/v1/properties/search"))["items"] if item["id"] == other["id"]]
    assert still[0]["status"] == "AVAILABLE"


def test_cross_tenant_references_are_refused(org):
    owner_id, org_a_id, other_id, org_b_id, *_ = org
    mine = _client(owner_id, org_a_id)
    theirs = _client(other_id, org_b_id)

    contact_a = _ok(mine.post("/api/v1/contacts", json={"first_name": "A", "last_name": "One"}), 201)
    contact_b = _ok(theirs.post("/api/v1/contacts", json={"first_name": "B", "last_name": "Two"}), 201)
    lead_a = _lead(mine, contact_a["id"])
    prop_a = _property(mine)
    profile_a = _ok(mine.post("/api/v1/customer-profiles", json={"contact_id": contact_a["id"]}), 201)
    requirement_a = _ok(mine.post("/api/v1/customer-requirements", json={}), 201)

    assert _lead_status(mine.post("/api/v1/leads", json={"contact_id": contact_b["id"], "interest": "LOW"})) == 404
    assert _lead_status(mine.post("/api/v1/customer-profiles", json={"contact_id": contact_b["id"]})) == 404
    assert _lead_status(mine.post("/api/v1/deals", json={"customer_profile_id": profile_a["id"],
                                                          "property_id": str(uuid4()), "expected_value": "1",
                                                          "currency": "INR"})) == 404
    assert _lead_status(theirs.post("/api/v1/deals", json={"customer_profile_id": profile_a["id"],
                                                            "property_id": prop_a["id"], "expected_value": "1",
                                                            "currency": "INR"})) == 404
    assert _lead_status(theirs.patch(f"/api/v1/customer-requirements/{requirement_a['id']}/association",
                                     json={"lead_id": lead_a["id"]})) == 404
    assert _lead_status(theirs.get(f"/api/v1/leads/{lead_a['id']}")) == 404
    assert _lead_status(theirs.get(f"/api/v1/customer-requirements/{requirement_a['id']}")) == 404
    assert _lead_status(theirs.get("/api/v1/properties/search")) == 200
    assert _lead_status(theirs.post("/api/v1/site-visits", json={"property_id": prop_a["id"], "lead_id": lead_a["id"],
                                                                 "scheduled_at": "2030-01-07T10:00:00Z"})) == 404
    deal_a = _deal(mine, customer_profile_id=profile_a["id"], property_id=prop_a["id"])
    assert _lead_status(theirs.post(f"/api/v1/deals/{deal_a['id']}/commissions",
                                    json={"commission_type": "FIXED", "fixed_amount": "1000", "currency": "INR"})) == 404
    assert _lead_status(theirs.patch(f"/api/v1/deals/{deal_a['id']}/stage", json={"stage": "QUALIFICATION"})) == 404
    assert _ok(theirs.get("/api/v1/properties/search"))["items"] == []


def _lead_status(response) -> int:
    return response.status_code


def test_permissions_are_enforced_on_each_relevant_operation(org):
    owner_id, org_a_id, _other_id, _org_b_id, reader_id, reader_org_id = org
    reader = _client(reader_id, reader_org_id)
    owner = _client(owner_id, org_a_id)

    assert reader.post("/api/v1/leads", json={"contact_id": str(uuid4()), "interest": "LOW"}).status_code == 403
    contact = _ok(owner.post("/api/v1/contacts", json={"first_name": "Perm", "last_name": "Test"}), 201)
    profile = _ok(owner.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)
    prop = _property(owner)
    deal = _deal(owner, customer_profile_id=profile["id"], property_id=prop["id"])
    _advance(owner, deal["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])

    # Reading history needs deals.read. The reader in another organization has none.
    assert reader.get(f"/api/v1/deals/{deal['id']}/stage-history").status_code == 403

    # A member of the same organization without deals.close can move a deal to BOOKING but cannot close it as won.
    with TestingSessionLocal() as db:
        member = create_user(db)
        membership = create_membership(db, user=member, organization=db.get(Organization, org_a_id))
        for key in ("deals.read", "deals.update"):
            grant_permission(db, membership=membership, permission_key=key)
        db.commit()
        member_id = member.id
    member_client = _client(member_id, org_a_id)
    assert member_client.get(f"/api/v1/deals/{deal['id']}/stage-history").status_code == 200
    refused = member_client.patch(f"/api/v1/deals/{deal['id']}/stage", json={"stage": "CLOSED_WON", "reason": "Signed."})
    assert refused.status_code == 403
    assert _ok(owner.get(f"/api/v1/deals/{deal['id']}"))["stage"] == "BOOKING"


def test_invalid_transitions_and_duplicate_operations_are_refused(org):
    owner_id, org_a_id, *_ = org
    client = _client(owner_id, org_a_id)
    contact = _ok(client.post("/api/v1/contacts", json={"first_name": "Dup", "last_name": "Test"}), 201)
    lead = _lead(client, contact["id"])
    assert client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "VISIT", "next_action": "x"}).status_code == 400

    profile = _ok(client.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)
    prop = _property(client)
    deal = _deal(client, customer_profile_id=profile["id"], property_id=prop["id"])
    assert client.patch(f"/api/v1/deals/{deal['id']}/stage", json={"stage": "BOOKING"}).status_code == 409
    assert client.patch(f"/api/v1/deals/{deal['id']}/stage", json={"stage": "CLOSED_WON", "reason": "early"}).status_code == 409

    follow_up = _ok(client.post(f"/api/v1/leads/{lead['id']}/follow-ups", json={
        "follow_up_type": "CALL", "title": "Once", "due_at": "2030-01-05T10:00:00Z"}), 201)
    _ok(client.post(f"/api/v1/follow-ups/{follow_up['id']}/complete", json={}))
    assert client.post(f"/api/v1/follow-ups/{follow_up['id']}/complete", json={}).status_code == 409


def test_stage_history_of_another_organization_is_not_visible(org):
    owner_id, org_a_id, other_id, org_b_id, *_ = org
    mine = _client(owner_id, org_a_id)
    contact = _ok(mine.post("/api/v1/contacts", json={"first_name": "Hist", "last_name": "Test"}), 201)
    profile = _ok(mine.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)
    deal = _deal(mine, customer_profile_id=profile["id"], property_id=_property(mine)["id"])
    theirs = _client(other_id, org_b_id)
    assert theirs.get(f"/api/v1/deals/{deal['id']}/stage-history").status_code == 404


def _property_without_status(client: TestClient) -> dict:
    return _ok(client.post("/api/v1/properties", json={}), 201)


def test_a_property_with_no_status_cannot_take_a_deal(org):
    owner_id, org_a_id, *_ = org
    client = _client(owner_id, org_a_id)
    contact = _ok(client.post("/api/v1/contacts", json={"first_name": "Nul", "last_name": "Status"}), 201)
    profile = _ok(client.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)
    prop = _property_without_status(client)
    refused = client.post("/api/v1/deals", json={"customer_profile_id": profile["id"], "property_id": prop["id"],
                                                  "expected_value": "1", "currency": "INR"})
    assert refused.status_code == 409


def test_closing_as_won_without_a_known_transaction_type_is_refused_and_keeps_the_deal_state(org):
    owner_id, org_a_id, *_ = org
    client = _client(owner_id, org_a_id)
    contact = _ok(client.post("/api/v1/contacts", json={"first_name": "Untyped", "last_name": "Deal"}), 201)
    profile = _ok(client.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)
    prop = _property(client, transaction_type="SALE")
    deal = _deal(client, customer_profile_id=profile["id"], property_id=prop["id"])
    _advance(client, deal["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])
    # Remove the transaction type after the deal exists, as a record that lost its type would be.
    from app.db.models.property import Property as PropertyModel
    with TestingSessionLocal() as db:
        db.get(PropertyModel, prop["id"]).transaction_type = None
        db.commit()

    refused = client.patch(f"/api/v1/deals/{deal['id']}/stage", json={"stage": "CLOSED_WON", "reason": "Signed."})
    assert refused.status_code == 422
    assert "SALE, RENT or LEASE" in refused.json()["error"]["message"]
    assert _ok(client.get(f"/api/v1/deals/{deal['id']}"))["stage"] == "BOOKING"
    assert [row["to_stage"] for row in _ok(client.get(f"/api/v1/deals/{deal['id']}/stage-history"))["items"]][-1] == "BOOKING"
    with TestingSessionLocal() as db:
        assert db.get(PropertyModel, prop["id"]).status == "AVAILABLE"


def test_a_second_deal_cannot_close_as_won_after_a_competing_sale(org):
    owner_id, org_a_id, *_ = org
    client = _client(owner_id, org_a_id)
    contact = _ok(client.post("/api/v1/contacts", json={"first_name": "Second", "last_name": "Buyer"}), 201)
    profile = _ok(client.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)
    prop = _property(client)
    first = _deal(client, customer_profile_id=profile["id"], property_id=prop["id"])
    second = _deal(client, customer_profile_id=profile["id"], property_id=prop["id"])
    _advance(client, first["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])
    _advance(client, second["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])
    _ok(client.patch(f"/api/v1/deals/{first['id']}/stage", json={"stage": "CLOSED_WON", "reason": "Signed."}))

    refused = client.patch(f"/api/v1/deals/{second['id']}/stage", json={"stage": "CLOSED_WON", "reason": "Also."})
    assert refused.status_code == 409
    assert _ok(client.get(f"/api/v1/deals/{second['id']}"))["stage"] == "BOOKING"


def test_concurrent_closures_on_one_property_produce_exactly_one_won_deal(org):
    """Four threads close four different booked deals on one available property at the same moment.

    The property row lock serializes them. Exactly one closure succeeds, and the others are refused with 409 without
    changing their deals. The property ends SOLD, and the database holds exactly one CLOSED_WON deal for it.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    owner_id, org_a_id, *_ = org
    client = _client(owner_id, org_a_id)
    contact = _ok(client.post("/api/v1/contacts", json={"first_name": "Race", "last_name": "Buyer"}), 201)
    profile = _ok(client.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}), 201)
    prop = _property(client)
    deals = [_deal(client, customer_profile_id=profile["id"], property_id=prop["id"]) for _ in range(4)]
    for deal in deals:
        _advance(client, deal["id"], ["QUALIFICATION", "NEGOTIATION", "BOOKING"])

    barrier = threading.Barrier(len(deals))

    def close(deal_id: str) -> int:
        worker = _client(owner_id, org_a_id)
        barrier.wait()
        return worker.patch(f"/api/v1/deals/{deal_id}/stage",
                            json={"stage": "CLOSED_WON", "reason": "Signed."}).status_code

    with ThreadPoolExecutor(max_workers=len(deals)) as pool:
        codes = list(pool.map(close, [deal["id"] for deal in deals]))

    assert sorted(codes) == [200, 409, 409, 409]
    stages = [_ok(client.get(f"/api/v1/deals/{deal['id']}"))["stage"] for deal in deals]
    assert stages.count("CLOSED_WON") == 1
    assert stages.count("BOOKING") == 3
    sold = [item for item in _ok(client.get("/api/v1/properties/search"))["items"] if item["id"] == prop["id"]]
    assert sold[0]["status"] == "SOLD"

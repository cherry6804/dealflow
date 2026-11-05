"""Disabled-by-default capability policy (DFR1-006): manual CRM keeps working, and queued work stops when automation is switched off.

The CRM journey helpers and the workflow runtime helpers are reused from their own test modules. Nothing here adds a second policy
engine. The gates under test are the ones in ``app.governance.policy`` and ``app.governance.execution_gate``.
"""

from __future__ import annotations

from app.db.session import SessionLocal
from app.governance.capabilities import (
    AUTOMATION_MASTER,
    AUTOMATION_WORKFLOWS,
    CAPABILITIES,
)
from app.governance.policy import evaluate_capability
from app.governance.service import set_capability_enabled
from tests.test_crm_vertical_slice import (  # noqa: F401  (org is the fixture)
    _advance,
    _client,
    _deal,
    _lead,
    _ok,
    _property,
    org,
)
from tests.test_team_api import TestingSessionLocal
from tests.test_workflow_runtime import (  # noqa: F401  (orgs is the fixture)
    SCORE_STEP,
    _drain,
    _row,
    _start,
    _steps,
    _workflow,
    config,
    orgs,
)


def test_manual_crm_work_is_unaffected_when_every_optional_capability_is_off(org):  # noqa: F811
    owner_id, org_a_id, *_ = org
    client = _client(owner_id, org_a_id)

    # Every optional AI and automation capability is denied for this organization, with no configuration at all.
    with TestingSessionLocal() as db:
        for definition in CAPABILITIES:
            decision = evaluate_capability(
                db, organization_id=org_a_id, capability_key=definition.key
            )
            assert decision.allowed is False, definition.key

    # The manual CRM path, end to end, with those capabilities off.
    contact = _ok(
        client.post(
            "/api/v1/contacts",
            json={
                "first_name": "Asha",
                "last_name": "Rao",
                "email": "asha@example.com",
                "phone": "+911234567890",
            },
        ),
        201,
    )
    lead = _lead(client, contact["id"])
    _ok(
        client.patch(
            f"/api/v1/leads/{lead['id']}",
            json={"status": "CONTACTED", "next_action": "Call back"},
        )
    )
    follow_up = _ok(
        client.post(
            f"/api/v1/leads/{lead['id']}/follow-ups",
            json={
                "follow_up_type": "CALL",
                "title": "Call back",
                "due_at": "2030-01-05T10:00:00Z",
            },
        ),
        201,
    )
    _ok(client.post(f"/api/v1/follow-ups/{follow_up['id']}/complete", json={}))
    prop = _property(client)
    visit = _ok(
        client.post(
            "/api/v1/site-visits",
            json={
                "property_id": prop["id"],
                "lead_id": lead["id"],
                "scheduled_at": "2030-01-07T10:00:00Z",
            },
        ),
        201,
    )
    _ok(
        client.patch(
            f"/api/v1/site-visits/{visit['id']}/attendance",
            json={
                "status": "COMPLETED",
                "outcome": "INTERESTED",
                "feedback": "Liked the layout.",
            },
        )
    )
    profile = _ok(
        client.post("/api/v1/customer-profiles", json={"contact_id": contact["id"]}),
        201,
    )
    deal = _deal(
        client,
        customer_profile_id=profile["id"],
        property_id=prop["id"],
        lead_id=lead["id"],
    )
    _advance(client, deal["id"], ["QUALIFICATION", "NEGOTIATION"])
    assert client.get(f"/api/v1/deals/{deal['id']}").status_code == 200


def test_a_queued_run_stops_at_start_when_automation_is_switched_off_after_queueing(
    orgs,  # noqa: F811
):
    workflow_id = _workflow(orgs, config([SCORE_STEP]))
    execution_id, _created = _start(orgs, workflow_id)

    # The run is queued and not yet started. The organization switches automation off before the worker runs it.
    with SessionLocal() as db:
        for key in (AUTOMATION_MASTER, AUTOMATION_WORKFLOWS):
            set_capability_enabled(
                db,
                organization_id=orgs.org.id,
                actor_user_id=orgs.owner.id,
                capability_key=key,
                is_enabled=False,
            )
        db.commit()
    _drain(orgs, execution_id)

    row = _row(execution_id)
    # A revalidation denial stops the run (status "stopped"), it does not fail it, and it names the gate reason.
    assert row.status == "stopped"
    assert row.failure_reason == "automation_disabled"
    assert all(step.status != "succeeded" for step in _steps(execution_id).values())

"""Tests for the Today dashboard summary: aggregation, bounds, tenancy and access."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dashboard import router as dashboard_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.dashboard.service import LIST_LIMIT
from app.db.models.deal import Deal
from app.db.models.follow_up import FollowUp
from app.db.session import get_db_session
from tests.test_deals_api import (
    TestingSessionLocal,
    create_authorized_user,
    create_customer_profile,
    create_lead,
    create_property,
)

DAY_START = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
DAY_END = DAY_START + timedelta(days=1)


def _app(user=None) -> FastAPI:
    app = FastAPI()
    app.include_router(dashboard_router)

    def override_get_db_session():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    if user is not None:
        app.dependency_overrides[get_current_user_context] = lambda: CurrentUserContext(user=user)
    return app


def _summary(*, user, organization, day_start=DAY_START, day_end=DAY_END):
    with TestClient(_app(user=user)) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        return client.get(
            "/api/v1/dashboard/summary",
            params={"day_start": day_start.isoformat(), "day_end": day_end.isoformat()},
        )


def _deal(db, *, user, organization, stage="NEW", value=None, currency="INR"):
    customer = create_customer_profile(db, organization=organization)
    property_record = create_property(db, organization=organization)
    deal = Deal(
        organization_id=organization.id,
        customer_profile_id=customer.id,
        property_id=property_record.id,
        owner_user_id=user.id,
        stage=stage,
        expected_value=value,
        currency=currency,
    )
    db.add(deal)
    db.flush()
    return deal


def _lead(db, *, organization, status="NEW", active=True, action=None, action_at=None):
    lead = create_lead(db, organization=organization)
    lead.status = status
    lead.is_active = active
    lead.next_action = action
    lead.next_action_at = action_at
    db.flush()
    return lead


def _follow_up(db, *, user, lead, due_at, status=FollowUp.STATUS_PENDING):
    follow_up = FollowUp(
        organization_id=lead.organization_id,
        lead_id=lead.id,
        owner_user_id=user.id,
        follow_up_type="CALL",
        title=f"Follow up {uuid4().hex[:6]}",
        due_at=due_at,
        status=status,
        completed_at=due_at if status == FollowUp.STATUS_COMPLETED else None,
        completed_by_user_id=user.id if status == FollowUp.STATUS_COMPLETED else None,
    )
    db.add(follow_up)
    db.flush()
    return follow_up


ALL_DASHBOARD_PERMISSIONS = ("deals.read", "leads.read")


def test_deal_summary_counts_stages_and_sums_open_value_by_currency() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        _deal(db, user=user, organization=organization, stage="NEW", value=100)
        _deal(db, user=user, organization=organization, stage="BOOKING", value=50)
        _deal(db, user=user, organization=organization, stage="NEGOTIATION", value=None)
        _deal(db, user=user, organization=organization, stage="CLOSED_WON", value=999)
        _deal(db, user=user, organization=organization, stage="NEW", value=20, currency="USD")
        db.commit()

        response = _summary(user=user, organization=organization)

    assert response.status_code == 200, response.text
    deals = response.json()["deals"]
    assert deals["by_stage"] == {
        "NEW": 2,
        "QUALIFICATION": 0,
        "NEGOTIATION": 1,
        "BOOKING": 1,
        "CLOSED_WON": 1,
        "CLOSED_LOST": 0,
    }
    assert deals["open_value_by_currency"] == [
        {"currency": "INR", "total": "150.00"},
        {"currency": "USD", "total": "20.00"},
    ]


def test_follow_up_buckets_respect_day_boundaries_and_exclude_closed_work() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        open_lead = _lead(db, organization=organization)
        _follow_up(db, user=user, lead=open_lead, due_at=DAY_START - timedelta(hours=1))
        _follow_up(db, user=user, lead=open_lead, due_at=DAY_START)
        _follow_up(db, user=user, lead=open_lead, due_at=DAY_END - timedelta(minutes=1))
        _follow_up(db, user=user, lead=open_lead, due_at=DAY_END)
        _follow_up(
            db,
            user=user,
            lead=open_lead,
            due_at=DAY_START - timedelta(hours=2),
            status=FollowUp.STATUS_COMPLETED,
        )
        won_lead = _lead(db, organization=organization, status="WON")
        _follow_up(db, user=user, lead=won_lead, due_at=DAY_START - timedelta(hours=3))
        inactive_lead = _lead(db, organization=organization, active=False)
        _follow_up(db, user=user, lead=inactive_lead, due_at=DAY_START + timedelta(hours=3))
        db.commit()

        response = _summary(user=user, organization=organization)

    assert response.status_code == 200, response.text
    follow_ups = response.json()["follow_ups"]
    assert follow_ups["overdue_count"] == 1
    assert follow_ups["today_count"] == 2
    assert follow_ups["upcoming_count"] == 1
    assert len(follow_ups["overdue"]) == 1
    assert len(follow_ups["today"]) == 2
    assert len(follow_ups["upcoming"]) == 1


def test_follow_up_lists_are_capped_while_counts_stay_exact() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        lead = _lead(db, organization=organization)
        overdue_total = LIST_LIMIT + 3
        for hours_ago in range(overdue_total, 0, -1):
            _follow_up(db, user=user, lead=lead, due_at=DAY_START - timedelta(hours=hours_ago))
        db.commit()

        response = _summary(user=user, organization=organization)

    follow_ups = response.json()["follow_ups"]
    assert follow_ups["overdue_count"] == overdue_total
    assert len(follow_ups["overdue"]) == LIST_LIMIT
    due_times = [item["due_at"] for item in follow_ups["overdue"]]
    assert due_times == sorted(due_times), "overdue items should be oldest first"


def test_lead_next_actions_bucket_by_due_date_and_skip_blank_or_closed_leads() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        _lead(db, organization=organization, action="Call back", action_at=DAY_START - timedelta(days=1))
        _lead(db, organization=organization, action="Send brochure", action_at=DAY_START + timedelta(hours=5))
        _lead(db, organization=organization, action="Later", action_at=DAY_END + timedelta(days=2))
        _lead(db, organization=organization, action="   ", action_at=DAY_START - timedelta(days=1))
        _lead(db, organization=organization, status="LOST", action="Closed", action_at=DAY_START - timedelta(days=1))
        _lead(db, organization=organization, active=False, action="Archived", action_at=DAY_START - timedelta(days=1))
        db.commit()

        response = _summary(user=user, organization=organization)

    actions = response.json()["lead_actions"]
    assert actions["overdue_count"] == 1
    assert actions["today_count"] == 1
    assert actions["overdue"][0]["action"] == "Call back"
    assert actions["today"][0]["action"] == "Send brochure"


def test_empty_organization_returns_zero_counts_and_empty_lists() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        db.commit()

        response = _summary(user=user, organization=organization)

    assert response.status_code == 200, response.text
    body = response.json()
    assert all(count == 0 for count in body["deals"]["by_stage"].values())
    assert body["deals"]["open_value_by_currency"] == []
    assert body["follow_ups"]["overdue_count"] == 0
    assert body["follow_ups"]["upcoming"] == []
    assert body["lead_actions"]["overdue"] == []


def test_summary_never_counts_another_organizations_records() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        other_user, other_organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        _deal(db, user=other_user, organization=other_organization, stage="NEW", value=500)
        other_lead = _lead(db, organization=other_organization, action="Foreign", action_at=DAY_START - timedelta(days=1))
        _follow_up(db, user=other_user, lead=other_lead, due_at=DAY_START - timedelta(hours=1))
        db.commit()

        response = _summary(user=user, organization=organization)

    body = response.json()
    assert body["deals"]["by_stage"]["NEW"] == 0
    assert body["deals"]["open_value_by_currency"] == []
    assert body["follow_ups"]["overdue_count"] == 0
    assert body["lead_actions"]["overdue"] == []


def test_caller_cannot_request_another_organization_by_header() -> None:
    with TestingSessionLocal() as db:
        user, _ = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        _, other_organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        db.commit()

        response = _summary(user=user, organization=other_organization)

    assert response.status_code == 403
    assert response.json() == {"detail": "Organization access denied."}


def test_role_without_lead_access_gets_only_deal_data() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=("deals.read",))
        _deal(db, user=user, organization=organization, stage="NEW", value=10)
        lead = _lead(db, organization=organization, action="Hidden", action_at=DAY_START - timedelta(days=1))
        _follow_up(db, user=user, lead=lead, due_at=DAY_START - timedelta(hours=1))
        db.commit()

        response = _summary(user=user, organization=organization)

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["access"] == {"deals": True, "follow_ups": False, "lead_actions": False}
    assert body["deals"]["by_stage"]["NEW"] == 1
    assert body["follow_ups"] is None
    assert body["lead_actions"] is None


def test_role_without_dashboard_permissions_gets_no_business_data() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=("contacts.read",))
        _deal(db, user=user, organization=organization, stage="NEW", value=10)
        db.commit()

        response = _summary(user=user, organization=organization)

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["access"] == {"deals": False, "follow_ups": False, "lead_actions": False}
    assert body["deals"] is None
    assert body["follow_ups"] is None
    assert body["lead_actions"] is None


def test_unauthenticated_request_is_rejected() -> None:
    with TestingSessionLocal() as db:
        _, organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        db.commit()

        with TestClient(_app()) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})
            response = client.get(
                "/api/v1/dashboard/summary",
                params={"day_start": DAY_START.isoformat(), "day_end": DAY_END.isoformat()},
            )

    assert response.status_code == 401


def test_invalid_windows_are_rejected() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db, permission_keys=ALL_DASHBOARD_PERMISSIONS)
        db.commit()

        naive = _summary(user=user, organization=organization, day_start=DAY_START.replace(tzinfo=None))
        reversed_window = _summary(user=user, organization=organization, day_start=DAY_END, day_end=DAY_START)
        too_long = _summary(user=user, organization=organization, day_end=DAY_START + timedelta(days=3))

    assert naive.status_code == 422
    assert naive.json()["detail"] == "day_start must include a timezone."
    assert reversed_window.status_code == 422
    assert too_long.status_code == 422

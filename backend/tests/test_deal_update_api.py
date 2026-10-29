"""Integration tests for editing a deal's permitted fields."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.models.deal import Deal

from tests.test_deals_api import (
    TestingSessionLocal,
    _create_test_deal,
    create_authorized_user,
    create_lead,
    create_membership,
    create_test_app,
    create_user,
)


def _patch_deal(*, user, organization, deal_id, body):
    app = create_test_app(user=user)

    with TestClient(app) as client:
        client.headers.update({"X-Organization-ID": str(organization.id)})
        return client.patch(f"/api/v1/deals/{deal_id}", json=body)


def test_update_deal_fields_successfully() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal = _create_test_deal(db, user=user, organization=organization)
        deal_id = deal.id

        response = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={
                "expected_value": 8200000,
                "currency": " usd ",
                "notes": "  Prefers a ground floor unit.  ",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["currency"] == "USD"
        assert payload["notes"] == "Prefers a ground floor unit."
        assert payload["stage"] == "NEW"

        db.expire_all()
        persisted = db.get(Deal, deal_id)
        assert persisted is not None
        assert persisted.currency == "USD"
        assert persisted.notes == "Prefers a ground floor unit."


def test_update_deal_links_a_lead_in_the_same_organization() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal = _create_test_deal(db, user=user, organization=organization)
        lead = create_lead(db, organization=organization)
        db.commit()
        deal_id = deal.id
        lead_id = lead.id

        response = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"lead_id": str(lead_id)},
        )

        assert response.status_code == 200, response.text
        assert response.json()["lead_id"] == str(lead_id)

        db.expire_all()
        assert db.get(Deal, deal_id).lead_id == lead_id


def test_update_deal_rejects_a_lead_from_another_organization() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal = _create_test_deal(db, user=user, organization=organization)
        _, other_organization = create_authorized_user(
            db,
            permission_keys=("deals.read",),
        )
        foreign_lead = create_lead(db, organization=other_organization)
        deal_id = deal.id
        foreign_lead_id = foreign_lead.id

        response = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"lead_id": str(foreign_lead_id)},
        )

        assert response.status_code == 404, response.text
        db.expire_all()
        assert db.get(Deal, deal_id).lead_id is None


def test_update_deal_reassigns_owner_to_an_active_member() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        colleague = create_user(db)
        create_membership(db, user=colleague, organization=organization)
        db.commit()
        deal = _create_test_deal(db, user=user, organization=organization)
        deal_id = deal.id
        colleague_id = colleague.id

        response = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"owner_user_id": str(colleague_id)},
        )

        assert response.status_code == 200, response.text
        db.expire_all()
        assert db.get(Deal, deal_id).owner_user_id == colleague_id


def test_update_deal_rejects_an_owner_outside_the_organization() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal = _create_test_deal(db, user=user, organization=organization)
        outsider = create_user(db)
        db.commit()
        deal_id = deal.id
        original_owner = deal.owner_user_id
        outsider_id = outsider.id

        response = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"owner_user_id": str(outsider_id)},
        )

        assert response.status_code == 422, response.text
        db.expire_all()
        assert db.get(Deal, deal_id).owner_user_id == original_owner


def test_update_deal_requires_update_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read",),
        )
        deal = _create_test_deal(db, user=user, organization=organization)
        deal_id = deal.id

        response = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"notes": "Attempted by a read-only user"},
        )

        assert response.status_code == 403
        assert response.json() == {"detail": "Permission denied."}
        db.expire_all()
        assert db.get(Deal, deal_id).notes == "Stage transition test"


def test_update_deal_rejects_another_tenant() -> None:
    with TestingSessionLocal() as db:
        owner, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal = _create_test_deal(db, user=owner, organization=organization)
        attacker, attacker_organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal_id = deal.id

        response = _patch_deal(
            user=attacker,
            organization=attacker_organization,
            deal_id=deal_id,
            body={"notes": "Cross-tenant edit"},
        )

        assert response.status_code == 404
        db.expire_all()
        assert db.get(Deal, deal_id).notes == "Stage transition test"


def test_update_deal_rejects_closed_deals() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal = _create_test_deal(db, user=user, organization=organization)
        deal.stage = "CLOSED_WON"
        db.commit()
        deal_id = deal.id

        response = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"notes": "Edit after closure"},
        )

        assert response.status_code == 409
        assert response.json() == {"detail": "Closed deals cannot be edited."}
        db.expire_all()
        assert db.get(Deal, deal_id).notes == "Stage transition test"


def test_update_deal_cannot_change_stage_or_unknown_fields() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal = _create_test_deal(db, user=user, organization=organization)
        deal_id = deal.id

        response = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"stage": "CLOSED_WON"},
        )

        assert response.status_code == 422
        db.expire_all()
        assert db.get(Deal, deal_id).stage == "NEW"


def test_update_deal_rejects_invalid_values() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal = _create_test_deal(db, user=user, organization=organization)
        deal_id = deal.id

        bad_currency = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"currency": "RUPEE"},
        )
        null_owner = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"owner_user_id": None},
        )
        negative_value = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={"expected_value": -1},
        )

        assert bad_currency.status_code == 422
        assert null_owner.status_code == 422
        assert negative_value.status_code == 422


def test_update_deal_with_empty_body_changes_nothing() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read", "deals.update"),
        )
        deal = _create_test_deal(db, user=user, organization=organization)
        deal_id = deal.id

        response = _patch_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            body={},
        )

        assert response.status_code == 200, response.text
        db.expire_all()
        persisted = db.get(Deal, deal_id)
        assert persisted.notes == "Stage transition test"
        assert persisted.stage == "NEW"

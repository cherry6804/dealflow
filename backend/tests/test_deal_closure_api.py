
"""Integration tests for explicit deal closure."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from fastapi.testclient import TestClient

from app.db.models.deal import Deal
from app.db.models.deal_stage_history import DealStageHistory

from tests.test_deals_api import (
    TestingSessionLocal,
    _create_test_deal,
    create_authorized_user,
    create_test_app,
)


def _create_booking_deal(db, *, user, organization) -> Deal:
    """Create a deal already at BOOKING for closure tests."""
    deal = _create_test_deal(
        db,
        user=user,
        organization=organization,
    )
    deal.stage = Deal.STAGE_BOOKING
    db.commit()
    db.refresh(deal)
    return deal


def _close_deal(
    *,
    user,
    organization,
    deal_id,
    outcome: str,
    reason: str | None,
):
    app = create_test_app(user=user)

    with TestClient(app) as client:
        client.headers.update(
            {"X-Organization-ID": str(organization.id)}
        )
        return client.patch(
            f"/api/v1/deals/{deal_id}/stage",
            json={"stage": outcome, "reason": reason},
        )


def test_close_deal_won_records_audit_history() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deals.update",
                "deals.close",
            ),
        )
        deal = _create_booking_deal(
            db,
            user=user,
            organization=organization,
        )
        deal_id = deal.id

        response = _close_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            outcome="CLOSED_WON",
            reason="Buyer signed the sale agreement.",
        )

        assert response.status_code == 200, response.text
        assert response.json()["stage"] == "CLOSED_WON"

        db.expire_all()
        persisted = db.get(Deal, deal_id)
        assert persisted is not None
        assert persisted.stage == "CLOSED_WON"

        history = db.scalars(
            select(DealStageHistory).where(
                DealStageHistory.deal_id == deal_id,
                DealStageHistory.organization_id == organization.id,
            )
        ).all()

        assert len(history) == 1
        assert history[0].from_stage == "BOOKING"
        assert history[0].to_stage == "CLOSED_WON"
        assert history[0].actor_user_id == user.id
        assert history[0].reason == "Buyer signed the sale agreement."


def test_close_deal_lost_records_audit_history() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deals.update",
                "deals.close",
            ),
        )
        deal = _create_booking_deal(
            db,
            user=user,
            organization=organization,
        )
        deal_id = deal.id

        response = _close_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            outcome="CLOSED_LOST",
            reason="Buyer selected another property.",
        )

        assert response.status_code == 200, response.text
        assert response.json()["stage"] == "CLOSED_LOST"

        history = db.scalars(
            select(DealStageHistory).where(
                DealStageHistory.deal_id == deal_id,
                DealStageHistory.organization_id == organization.id,
            )
        ).all()

        assert len(history) == 1
        assert history[0].from_stage == "BOOKING"
        assert history[0].to_stage == "CLOSED_LOST"
        assert history[0].actor_user_id == user.id
        assert history[0].reason == "Buyer selected another property."


def test_closure_requires_a_reason() -> None:
    for reason in (None, "", "   "):
        with TestingSessionLocal() as db:
            user, organization = create_authorized_user(
                db,
                permission_keys=(
                    "deals.create",
                    "deals.read",
                    "deals.update",
                    "deals.close",
                ),
            )
            deal = _create_booking_deal(
                db,
                user=user,
                organization=organization,
            )

            response = _close_deal(
                user=user,
                organization=organization,
                deal_id=deal.id,
                outcome="CLOSED_WON",
                reason=reason,
            )

            if reason is None or reason == "":
                # Pydantic accepts an omitted/null reason; the service
                # must reject it as a business-rule violation.
                assert response.status_code == 409, response.text
            else:
                assert response.status_code == 409, response.text

            db.expire_all()
            persisted = db.get(Deal, deal.id)
            assert persisted is not None
            assert persisted.stage == "BOOKING"

            history = db.scalars(
                select(DealStageHistory).where(
                    DealStageHistory.deal_id == deal.id,
                    DealStageHistory.organization_id == organization.id,
                )
            ).all()
            assert history == []


def test_closure_is_rejected_before_booking() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deals.update",
                "deals.close",
            ),
        )
        deal = _create_test_deal(
            db,
            user=user,
            organization=organization,
        )

        response = _close_deal(
            user=user,
            organization=organization,
            deal_id=deal.id,
            outcome="CLOSED_WON",
            reason="Agreement signed.",
        )

        assert response.status_code == 409, response.text

        db.expire_all()
        persisted = db.get(Deal, deal.id)
        assert persisted is not None
        assert persisted.stage == "NEW"

        history = db.scalars(
            select(DealStageHistory).where(
                DealStageHistory.deal_id == deal.id,
                DealStageHistory.organization_id == organization.id,
            )
        ).all()
        assert history == []


def test_closed_deal_cannot_be_closed_again_or_reopened() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deals.update",
                "deals.close",
            ),
        )
        deal = _create_booking_deal(
            db,
            user=user,
            organization=organization,
        )
        deal_id = deal.id

        first_response = _close_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            outcome="CLOSED_WON",
            reason="Sale agreement signed.",
        )
        assert first_response.status_code == 200, first_response.text

        second_response = _close_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            outcome="CLOSED_LOST",
            reason="Attempt to change outcome.",
        )
        assert second_response.status_code == 409, second_response.text

        reopen_response = _close_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            outcome="BOOKING",
            reason="Attempt to reopen.",
        )
        assert reopen_response.status_code == 409, reopen_response.text

        db.expire_all()
        persisted = db.get(Deal, deal_id)
        assert persisted is not None
        assert persisted.stage == "CLOSED_WON"

        history = db.scalars(
            select(DealStageHistory).where(
                DealStageHistory.deal_id == deal_id,
                DealStageHistory.organization_id == organization.id,
            )
        ).all()
        assert len(history) == 1
        assert history[0].to_stage == "CLOSED_WON"


def test_closing_requires_deals_close_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deals.update",
            ),
        )
        deal = _create_booking_deal(
            db,
            user=user,
            organization=organization,
        )
        deal_id = deal.id

        response = _close_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            outcome="CLOSED_WON",
            reason="Buyer signed the sale agreement.",
        )

        assert response.status_code == 403
        assert response.json() == {"detail": "Permission denied."}

        db.expire_all()
        persisted = db.get(Deal, deal_id)
        assert persisted is not None
        assert persisted.stage == "BOOKING"
        assert (
            db.scalars(
                select(DealStageHistory).where(
                    DealStageHistory.deal_id == deal_id,
                )
            ).all()
            == []
        )


def test_update_only_role_can_still_move_a_deal_before_closure() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deals.update",
            ),
        )
        deal = _create_test_deal(
            db,
            user=user,
            organization=organization,
        )
        deal_id = deal.id

        response = _close_deal(
            user=user,
            organization=organization,
            deal_id=deal_id,
            outcome="QUALIFICATION",
            reason=None,
        )

        assert response.status_code == 200, response.text
        assert response.json()["stage"] == "QUALIFICATION"


def test_member_of_another_organization_cannot_close_a_deal() -> None:
    all_permissions = (
        "deals.create",
        "deals.read",
        "deals.update",
        "deals.close",
    )
    with TestingSessionLocal() as db:
        owner, owner_organization = create_authorized_user(
            db,
            permission_keys=all_permissions,
        )
        deal = _create_booking_deal(
            db,
            user=owner,
            organization=owner_organization,
        )
        deal_id = deal.id

        other, other_organization = create_authorized_user(
            db,
            permission_keys=all_permissions,
        )

        response = _close_deal(
            user=other,
            organization=other_organization,
            deal_id=deal_id,
            outcome="CLOSED_WON",
            reason="Attempt from another workspace.",
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Deal not found."}

        db.expire_all()
        persisted = db.get(Deal, deal_id)
        assert persisted is not None
        assert persisted.stage == "BOOKING"


def test_create_rejects_a_closed_stage_and_persists_nothing() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=(
                "deals.create",
                "deals.read",
                "deals.update",
                "deals.close",
            ),
        )
        organization_id = organization.id

        with TestClient(create_test_app(user=user)) as client:
            client.headers.update({"X-Organization-ID": str(organization_id)})
            response = client.post(
                "/api/v1/deals",
                json={
                    "customer_profile_id": str(uuid4()),
                    "property_id": str(uuid4()),
                    "stage": "CLOSED_WON",
                },
            )

        assert response.status_code == 422
        db.expire_all()
        assert (
            db.scalars(
                select(Deal).where(Deal.organization_id == organization_id)
            ).all()
            == []
        )

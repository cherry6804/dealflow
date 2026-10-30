"""Integration tests for the tenant-scoped Deals API."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models.deal_stage_history import DealStageHistory
from app.api.deals import router as deals_router
from app.auth.dependencies import CurrentUserContext, get_current_user_context
from app.db.models.contact import Contact
from app.db.models.customer_profile import CustomerProfile
from app.db.models.deal import Deal
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization import Organization
from app.db.models.permission import Permission
from app.db.models.property import Property
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session
from app.db.models.notification import Notification
from app.db.models.notification_preference import NotificationPreference

TestingSessionLocal = SessionLocal


def create_user(db: Session) -> User:
    user = User(
        email=f"deals-{uuid4()}@example.com",
        display_name="Deals Test User",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_organization(db: Session) -> Organization:
    organization = Organization(
        name=f"Deals Test Organization {uuid4()}",
        is_active=True,
    )
    db.add(organization)
    db.flush()
    return organization


def create_membership(
    db: Session,
    *,
    user: User,
    organization: Organization,
    is_active: bool = True,
) -> Membership:
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=is_active,
    )
    db.add(membership)
    db.flush()
    return membership



def grant_permission(
    db: Session,
    *,
    membership: Membership,
    permission_key: str,
) -> None:
    permission = db.scalar(
        select(Permission).where(Permission.key == permission_key)
    )
    if permission is None:
        permission = Permission(key=permission_key, is_active=True)
        db.add(permission)
        db.flush()
    elif not permission.is_active:
        permission.is_active = True
        db.flush()

    role = Role(
        name=f"Deals Test Role {uuid4()}",
        organization_id=membership.organization_id,
        is_active=True,
    )
    db.add(role)
    db.flush()

    db.add(
        MembershipRole(
            membership_id=membership.id,
            role_id=role.id,
        )
    )
    db.add(
        RolePermission(
            role_id=role.id,
            permission_id=permission.id,
        )
    )
    db.flush()



def create_authorized_user(
    db: Session,
    *,
    permission_keys: tuple[str, ...] = ("deals.create", "deals.read"),
) -> tuple[User, Organization]:
    user = create_user(db)
    organization = create_organization(db)
    membership = create_membership(
        db,
        user=user,
        organization=organization,
    )
    for permission_key in permission_keys:
        grant_permission(
            db,
            membership=membership,
            permission_key=permission_key,
        )
    db.commit()
    return user, organization


def create_property(
    db: Session,
    *,
    organization: Organization,
) -> Property:
    property_record = Property(
        organization_id=organization.id,
        city="Chennai",
        state="Tamil Nadu",
        property_type="APARTMENT",
    )
    db.add(property_record)
    db.flush()
    return property_record


def create_customer_profile(
    db: Session,
    *,
    organization: Organization,
    is_active: bool = True,
) -> CustomerProfile:
    contact = Contact(
        organization_id=organization.id,
        first_name="Deals",
        last_name="Customer",
        is_active=True,
    )
    db.add(contact)
    db.flush()

    profile = CustomerProfile(
        organization_id=organization.id,
        contact_id=contact.id,
        is_active=is_active,
        customer_notes="Deals API test customer",
    )
    db.add(profile)
    db.flush()
    return profile


def create_lead(
    db: Session,
    *,
    organization: Organization,
) -> Lead:
    contact = Contact(
        organization_id=organization.id,
        first_name="Deals",
        last_name="Lead",
        is_active=True,
    )
    db.add(contact)
    db.flush()

    lead = Lead(
        organization_id=organization.id,
        contact_id=contact.id,
        status=Lead.STATUS_NEW,
        is_active=True,
    )
    db.add(lead)
    db.flush()
    return lead


def create_test_app(*, user: User) -> FastAPI:
    app = FastAPI()
    app.include_router(deals_router)

    def override_get_db_session() -> Iterator[Session]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_current_user_context] = (
        lambda: CurrentUserContext(user=user)
    )
    return app


def valid_payload(
    *,
    customer_profile_id: UUID,
    property_id: UUID,
    lead_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "customer_profile_id": str(customer_profile_id),
        "property_id": str(property_id),
        "lead_id": str(lead_id) if lead_id else None,
        "stage": "NEW",
        "expected_value": "7500000.00",
        "currency": "INR",
        "notes": "Discuss booking terms.",
    }


def test_create_deal_successfully() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        lead = create_lead(db, organization=organization)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer.id,
            property_id=property_record.id,
            lead_id=lead.id,
        )

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 201, response.text
        result = response.json()
        assert result["organization_id"] == str(organization.id)
        assert result["customer_profile_id"] == str(customer.id)
        assert result["property_id"] == str(property_record.id)
        assert result["lead_id"] == str(lead.id)
        assert result["owner_user_id"] == str(user.id)
        assert result["stage"] == "NEW"
        assert result["currency"] == "INR"
        assert result["notes"] == payload["notes"]

        persisted = db.scalar(
            select(Deal).where(Deal.id == UUID(result["id"]))
        )
        assert persisted is not None
        assert persisted.organization_id == organization.id
        assert persisted.expected_value is not None
        assert str(persisted.expected_value) == "7500000.00"


def test_create_deal_rejects_cross_tenant_customer() -> None:
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(db)
        organization_b = create_organization(db)
        customer_b = create_customer_profile(db, organization=organization_b)
        property_a = create_property(db, organization=organization_a)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer_b.id,
            property_id=property_a.id,
        )
        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization_a.id)})
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 404, response.text
        assert db.scalars(
            select(Deal).where(Deal.organization_id == organization_a.id)
        ).all() == []


def test_create_deal_rejects_cross_tenant_property() -> None:
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(db)
        organization_b = create_organization(db)
        customer_a = create_customer_profile(db, organization=organization_a)
        property_b = create_property(db, organization=organization_b)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer_a.id,
            property_id=property_b.id,
        )
        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization_a.id)})
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 404, response.text


def test_create_deal_rejects_cross_tenant_lead() -> None:
    with TestingSessionLocal() as db:
        user, organization_a = create_authorized_user(db)
        organization_b = create_organization(db)
        customer_a = create_customer_profile(db, organization=organization_a)
        property_a = create_property(db, organization=organization_a)
        lead_b = create_lead(db, organization=organization_b)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer_a.id,
            property_id=property_a.id,
            lead_id=lead_b.id,
        )
        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization_a.id)})
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 404, response.text


def test_create_deal_rejects_inactive_customer() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        customer = create_customer_profile(
            db,
            organization=organization,
            is_active=False,
        )
        property_record = create_property(db, organization=organization)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer.id,
            property_id=property_record.id,
        )
        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 404, response.text


def test_create_deal_rejects_inactive_owner_membership() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        inactive_owner = create_user(db)
        create_membership(
            db,
            user=inactive_owner,
            organization=organization,
            is_active=False,
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer.id,
            property_id=property_record.id,
        )
        payload["owner_user_id"] = str(inactive_owner.id)

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 422, response.text


def test_create_deal_requires_create_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.read",),
        )
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer.id,
            property_id=property_record.id,
        )
        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 403, response.text


def test_list_deals_filters_and_paginates() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})

            for stage in ("NEW", "NEGOTIATION", "NEW"):
                payload = valid_payload(
                    customer_profile_id=customer.id,
                    property_id=property_record.id,
                )
                payload["stage"] = stage
                response = client.post("/api/v1/deals", json=payload)
                assert response.status_code == 201, response.text

            page_response = client.get(
                "/api/v1/deals",
                params={"page": 1, "page_size": 2},
            )
            filtered_response = client.get(
                "/api/v1/deals",
                params={"stage": "NEW", "page": 1, "page_size": 1},
            )

        assert page_response.status_code == 200, page_response.text
        page_result = page_response.json()
        assert page_result["total"] == 3
        assert len(page_result["items"]) == 2
        assert page_result["page"] == 1
        assert page_result["page_size"] == 2
        assert page_result["total_pages"] == 2

        assert filtered_response.status_code == 200, filtered_response.text
        filtered_result = filtered_response.json()
        assert filtered_result["total"] == 2
        assert len(filtered_result["items"]) == 1
        assert filtered_result["items"][0]["stage"] == "NEW"


def test_get_deal_rejects_another_tenant() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(db)
        user_b, organization_b = create_authorized_user(db)
        customer_b = create_customer_profile(db, organization=organization_b)
        property_b = create_property(db, organization=organization_b)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer_b.id,
            property_id=property_b.id,
        )
        app_b = create_test_app(user=user_b)
        with TestClient(app_b) as client_b:
            client_b.headers.update({"X-Organization-ID": str(organization_b.id)})
            create_response = client_b.post("/api/v1/deals", json=payload)

        assert create_response.status_code == 201, create_response.text
        deal_id = create_response.json()["id"]

        app_a = create_test_app(user=user_a)
        with TestClient(app_a) as client_a:
            client_a.headers.update({"X-Organization-ID": str(organization_a.id)})
            response = client_a.get(f"/api/v1/deals/{deal_id}")

        assert response.status_code == 404, response.text


def test_list_deals_requires_read_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.create",),
        )
        db.commit()

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update({"X-Organization-ID": str(organization.id)})
            response = client.get("/api/v1/deals")

        assert response.status_code == 403, response.text


def _create_test_deal(
    db: Session,
    *,
    user: User,
    organization: Organization,
) -> Deal:
    """Create and persist a deal for stage-transition tests."""
    customer = create_customer_profile(db, organization=organization)
    property_record = create_property(db, organization=organization)
    db.flush()

    deal = Deal(
        organization_id=organization.id,
        customer_profile_id=customer.id,
        property_id=property_record.id,
        owner_user_id=user.id,
        stage=Deal.STAGE_NEW,
        expected_value=7500000,
        currency="INR",
        notes="Stage transition test",
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


def test_transition_deal_stage_successfully_records_history() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.create", "deals.read", "deals.update"),
        )
        deal = _create_test_deal(
            db,
            user=user,
            organization=organization,
        )
        deal_id = deal.id

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.patch(
                f"/api/v1/deals/{deal_id}/stage",
                json={
                    "stage": "QUALIFICATION",
                    "reason": "Customer requirements qualified",
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["stage"] == "QUALIFICATION"

        db.expire_all()
        persisted_deal = db.get(Deal, deal_id)
        assert persisted_deal is not None
        assert persisted_deal.stage == "QUALIFICATION"

        history = db.scalars(
            select(DealStageHistory).where(
                DealStageHistory.deal_id == deal_id,
                DealStageHistory.organization_id == organization.id,
            )
        ).all()

        assert len(history) == 1
        assert history[0].from_stage == "NEW"
        assert history[0].to_stage == "QUALIFICATION"
        assert history[0].actor_user_id == user.id
        assert history[0].reason == "Customer requirements qualified"


def test_transition_deal_stage_through_booking() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.create", "deals.read", "deals.update"),
        )
        deal = _create_test_deal(
            db,
            user=user,
            organization=organization,
        )
        deal_id = deal.id

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )

            for stage in ("QUALIFICATION", "NEGOTIATION", "BOOKING"):
                response = client.patch(
                    f"/api/v1/deals/{deal_id}/stage",
                    json={"stage": stage},
                )
                assert response.status_code == 200, response.text
                assert response.json()["stage"] == stage

        history = db.scalars(
            select(DealStageHistory)
            .where(DealStageHistory.deal_id == deal_id)
            .order_by(DealStageHistory.created_at, DealStageHistory.id)
        ).all()

        assert len(history) == 3
        assert [(item.from_stage, item.to_stage) for item in history] == [
            ("NEW", "QUALIFICATION"),
            ("QUALIFICATION", "NEGOTIATION"),
            ("NEGOTIATION", "BOOKING"),
        ]


def test_transition_deal_stage_rejects_skipping_a_stage() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.create", "deals.read", "deals.update"),
        )
        deal = _create_test_deal(
            db,
            user=user,
            organization=organization,
        )

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.patch(
                f"/api/v1/deals/{deal.id}/stage",
                json={"stage": "BOOKING"},
            )

        assert response.status_code == 409, response.text

        db.expire_all()
        persisted_deal = db.get(Deal, deal.id)
        assert persisted_deal is not None
        assert persisted_deal.stage == "NEW"

        history = db.scalars(
            select(DealStageHistory).where(
                DealStageHistory.deal_id == deal.id
            )
        ).all()
        assert history == []


def test_transition_deal_stage_rejects_repeating_current_stage() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.create", "deals.read", "deals.update"),
        )
        deal = _create_test_deal(
            db,
            user=user,
            organization=organization,
        )

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.patch(
                f"/api/v1/deals/{deal.id}/stage",
                json={"stage": "NEW"},
            )

        assert response.status_code == 409, response.text


def test_transition_deal_stage_requires_update_permission() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.create", "deals.read"),
        )
        deal = _create_test_deal(
            db,
            user=user,
            organization=organization,
        )

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.patch(
                f"/api/v1/deals/{deal.id}/stage",
                json={"stage": "QUALIFICATION"},
            )

        assert response.status_code == 403, response.text

        db.expire_all()
        persisted_deal = db.get(Deal, deal.id)
        assert persisted_deal is not None
        assert persisted_deal.stage == "NEW"


def test_transition_deal_stage_rejects_another_tenant() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=("deals.create", "deals.read", "deals.update"),
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=("deals.create", "deals.read", "deals.update"),
        )
        deal_b = _create_test_deal(
            db,
            user=user_b,
            organization=organization_b,
        )

        app = create_test_app(user=user_a)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization_a.id)}
            )
            response = client.patch(
                f"/api/v1/deals/{deal_b.id}/stage",
                json={"stage": "QUALIFICATION"},
            )

        assert response.status_code == 404, response.text

        db.expire_all()
        persisted_deal = db.get(Deal, deal_b.id)
        assert persisted_deal is not None
        assert persisted_deal.stage == "NEW"

        history = db.scalars(
            select(DealStageHistory).where(
                DealStageHistory.deal_id == deal_b.id
            )
        ).all()
        assert history == []


def test_create_deal_persists_notification_for_owner() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer.id,
            property_id=property_record.id,
        )

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 201, response.text
        deal_id = response.json()["id"]

        db.expire_all()
        notification = db.scalar(
            select(Notification).where(
                Notification.organization_id == organization.id,
                Notification.recipient_user_id == user.id,
                Notification.event_key == f"deal:{deal_id}:created",
            )
        )

        assert notification is not None
        assert notification.event_type == "DEAL_CREATED"
        assert notification.title == "New deal created"
        assert notification.resource_type == "deal"
        assert notification.resource_id == deal_id


def test_create_deal_respects_disabled_deal_notifications() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        customer = create_customer_profile(db, organization=organization)
        property_record = create_property(db, organization=organization)

        db.add(
            NotificationPreference(
                organization_id=organization.id,
                user_id=user.id,
                enabled=True,
                deals_enabled=False,
                follow_ups_enabled=True,
                site_visits_enabled=True,
                leads_enabled=True,
                automation_enabled=True,
            )
        )
        db.commit()

        payload = valid_payload(
            customer_profile_id=customer.id,
            property_id=property_record.id,
        )

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.post("/api/v1/deals", json=payload)

        assert response.status_code == 201, response.text
        deal_id = response.json()["id"]

        db.expire_all()
        notification = db.scalar(
            select(Notification).where(
                Notification.organization_id == organization.id,
                Notification.recipient_user_id == user.id,
                Notification.event_key == f"deal:{deal_id}:created",
            )
        )

        assert notification is None


def test_transition_deal_stage_persists_notification() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("deals.create", "deals.read", "deals.update"),
        )
        deal = _create_test_deal(
            db,
            user=user,
            organization=organization,
        )
        deal_id = deal.id

        app = create_test_app(user=user)
        with TestClient(app) as client:
            client.headers.update(
                {"X-Organization-ID": str(organization.id)}
            )
            response = client.patch(
                f"/api/v1/deals/{deal_id}/stage",
                json={
                    "stage": "QUALIFICATION",
                    "reason": "Customer requirements qualified",
                },
            )

        assert response.status_code == 200, response.text

        db.expire_all()
        notification = db.scalar(
            select(Notification).where(
                Notification.organization_id == organization.id,
                Notification.recipient_user_id == user.id,
                Notification.event_key
                == f"deal:{deal_id}:stage:QUALIFICATION",
            )
        )

        assert notification is not None
        assert notification.event_type == "DEAL_STAGE_CHANGED"
        assert notification.resource_id == str(deal_id)

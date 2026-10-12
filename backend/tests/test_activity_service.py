"""Tests for Activity service-layer operations."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activities.schemas import ActivityCreateRequest
from app.activities.service import create_activity, list_lead_activities
from app.db.models.activity import Activity
from app.db.models.contact import Contact
from app.db.models.lead import Lead
from app.db.models.membership import Membership
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import SessionLocal


def create_test_user(db: Session) -> User:
    user = User(
        email=f"activity-test-{uuid4()}@example.com",
        display_name="Activity Test User",
        password_hash="test-password-hash",
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_test_organization(db: Session) -> Organization:
    organization = Organization(
        name=f"Activity Test Organization {uuid4()}",
        is_active=True,
    )
    db.add(organization)
    db.flush()
    return organization


def create_test_membership(
    db: Session,
    *,
    user: User,
    organization: Organization,
) -> Membership:
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=True,
    )
    db.add(membership)
    db.flush()
    return membership


def create_test_lead(
    db: Session,
    *,
    organization: Organization,
) -> Lead:
    contact = Contact(
        organization_id=organization.id,
        first_name="Activity",
        last_name="Test",
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


def test_create_activity_successfully() -> None:
    with SessionLocal() as db:
        user = create_test_user(db)
        organization = create_test_organization(db)
        create_test_membership(
            db,
            user=user,
            organization=organization,
        )
        lead = create_test_lead(db, organization=organization)
        db.commit()

        payload = ActivityCreateRequest(
            activity_type="NOTE",
            title="Customer discussion",
            description="Discussed property requirements",
            details={"source": "phone"},
        )

        activity = create_activity(
            db,
            organization_id=organization.id,
            actor_id=user.id,
            lead_id=lead.id,
            payload=payload,
        )

        assert activity is not None
        assert activity.id is not None
        assert activity.organization_id == organization.id
        assert activity.lead_id == lead.id
        assert activity.actor_id == user.id
        assert activity.activity_type == "NOTE"
        assert activity.title == "Customer discussion"
        assert activity.description == "Discussed property requirements"
        assert activity.details == {"source": "phone"}

        db.commit()

        persisted = db.scalar(
            select(Activity).where(Activity.id == activity.id)
        )
        assert persisted is not None


def test_create_activity_returns_none_for_missing_lead() -> None:
    with SessionLocal() as db:
        user = create_test_user(db)
        organization = create_test_organization(db)
        create_test_membership(
            db,
            user=user,
            organization=organization,
        )
        db.commit()

        payload = ActivityCreateRequest(
            activity_type="NOTE",
            title="Missing lead",
        )

        activity = create_activity(
            db,
            organization_id=organization.id,
            actor_id=user.id,
            lead_id=uuid4(),
            payload=payload,
        )

        assert activity is None


def test_create_activity_rejects_cross_tenant_lead() -> None:
    with SessionLocal() as db:
        user = create_test_user(db)
        organization_a = create_test_organization(db)
        organization_b = create_test_organization(db)

        create_test_membership(
            db,
            user=user,
            organization=organization_a,
        )
        lead_b = create_test_lead(db, organization=organization_b)
        db.commit()

        payload = ActivityCreateRequest(
            activity_type="NOTE",
            title="Cross-tenant attempt",
        )

        activity = create_activity(
            db,
            organization_id=organization_a.id,
            actor_id=user.id,
            lead_id=lead_b.id,
            payload=payload,
        )

        assert activity is None

        persisted = db.scalars(
            select(Activity).where(
                Activity.organization_id == organization_a.id,
                Activity.lead_id == lead_b.id,
            )
        ).all()
        assert persisted == []


def test_list_lead_activities_returns_timeline_in_order() -> None:
    with SessionLocal() as db:
        user = create_test_user(db)
        organization = create_test_organization(db)
        create_test_membership(
            db,
            user=user,
            organization=organization,
        )
        lead = create_test_lead(db, organization=organization)
        db.commit()

        base_time = datetime.now(timezone.utc)

        later_payload = ActivityCreateRequest(
            activity_type="CALL",
            title="Later call",
            occurred_at=base_time + timedelta(minutes=10),
        )
        earlier_payload = ActivityCreateRequest(
            activity_type="NOTE",
            title="Earlier note",
            occurred_at=base_time,
        )

        later_activity = create_activity(
            db,
            organization_id=organization.id,
            actor_id=user.id,
            lead_id=lead.id,
            payload=later_payload,
        )
        earlier_activity = create_activity(
            db,
            organization_id=organization.id,
            actor_id=user.id,
            lead_id=lead.id,
            payload=earlier_payload,
        )
        assert later_activity is not None
        assert earlier_activity is not None
        db.commit()

        activities = list_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=lead.id,
        )

        assert activities is not None
        assert [item.title for item in activities] == [
            "Earlier note",
            "Later call",
        ]


def test_list_lead_activities_returns_none_for_missing_lead() -> None:
    with SessionLocal() as db:
        organization = create_test_organization(db)
        db.commit()

        activities = list_lead_activities(
            db,
            organization_id=organization.id,
            lead_id=uuid4(),
        )

        assert activities is None


def test_list_lead_activities_rejects_cross_tenant_lead() -> None:
    with SessionLocal() as db:
        organization_a = create_test_organization(db)
        organization_b = create_test_organization(db)
        lead_b = create_test_lead(db, organization=organization_b)
        db.commit()

        activities = list_lead_activities(
            db,
            organization_id=organization_a.id,
            lead_id=lead_b.id,
        )

        assert activities is None
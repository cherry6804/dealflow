
"""Integration tests for tenant-scoped in-app notifications."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.notifications import router as notifications_router
from app.auth.dependencies import (
    CurrentUserContext,
    get_current_user_context,
)
from app.db.models.membership import Membership
from app.db.models.notification import Notification
from app.db.models.organization import Organization
from app.db.models.user import User
from app.db.session import SessionLocal, get_db_session
from app.notifications.service import create_notification
from tests.test_deals_api import create_authorized_user, create_user


TestingSessionLocal = SessionLocal


def create_test_app(*, user: User) -> FastAPI:
    """Create a test application with the notification router."""
    app = FastAPI()
    app.include_router(notifications_router)

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


def request_as(*, user: User, organization: Organization) -> TestClient:
    """Create a client with the authenticated user and tenant header."""
    app = create_test_app(user=user)
    client = TestClient(app)
    client.headers.update({"X-Organization-ID": str(organization.id)})
    return client


def create_test_notification(
    db: Session,
    *,
    user: User,
    organization: Organization,
    event_key: str | None = None,
) -> Notification:
    """Create and persist a notification through the service."""
    notification = create_notification(
        db,
        organization_id=organization.id,
        recipient_user_id=user.id,
        event_type="DEAL_UPDATED",
        title="Deal updated",
        message="A deal was updated.",
        resource_type="deal",
        resource_id=str(uuid4()),
        event_key=event_key,
    )
    db.commit()
    db.refresh(notification)
    return notification


def add_member_to_organization(
    db: Session,
    *,
    user: User,
    organization: Organization,
    active: bool = True,
) -> Membership:
    """Add a test user to an existing organization."""
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        is_active=active,
    )
    db.add(membership)
    db.flush()
    return membership


def test_list_notifications_returns_only_current_users_notifications() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        other_user = create_user(db)
        add_member_to_organization(
            db,
            user=other_user,
            organization=organization,
        )
        own_notification = create_test_notification(
            db,
            user=user,
            organization=organization,
        )
        create_test_notification(
            db,
            user=other_user,
            organization=organization,
        )

        with request_as(user=user, organization=organization) as client:
            response = client.get("/api/v1/notifications")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["unread_count"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["id"] == str(own_notification.id)
        assert body["items"][0]["recipient_user_id"] == str(user.id)


def test_unread_count_and_mark_one_read() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        notification = create_test_notification(
            db,
            user=user,
            organization=organization,
        )

        with request_as(user=user, organization=organization) as client:
            count_before = client.get(
                "/api/v1/notifications/unread-count"
            )
            marked = client.patch(
                f"/api/v1/notifications/{notification.id}/read"
            )
            count_after = client.get(
                "/api/v1/notifications/unread-count"
            )

        assert count_before.status_code == 200, count_before.text
        assert count_before.json()["unread_count"] == 1
        assert marked.status_code == 200, marked.text
        assert marked.json()["read_at"] is not None
        assert count_after.status_code == 200, count_after.text
        assert count_after.json()["unread_count"] == 0


def test_mark_all_read_updates_only_current_users_notifications() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        other_user = create_user(db)
        add_member_to_organization(
            db,
            user=other_user,
            organization=organization,
        )
        own_notification = create_test_notification(
            db,
            user=user,
            organization=organization,
        )
        other_notification = create_test_notification(
            db,
            user=other_user,
            organization=organization,
        )

        with request_as(user=user, organization=organization) as client:
            response = client.post(
                "/api/v1/notifications/mark-all-read"
            )

        assert response.status_code == 200, response.text
        assert response.json()["updated_count"] == 1

        db.expire_all()
        own_persisted = db.get(Notification, own_notification.id)
        other_persisted = db.get(Notification, other_notification.id)

        assert own_persisted is not None
        assert own_persisted.read_at is not None
        assert other_persisted is not None
        assert other_persisted.read_at is None


def test_cannot_mark_another_users_notification_as_read() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        other_user = create_user(db)
        add_member_to_organization(
            db,
            user=other_user,
            organization=organization,
        )
        notification = create_test_notification(
            db,
            user=other_user,
            organization=organization,
        )

        with request_as(user=user, organization=organization) as client:
            response = client.patch(
                f"/api/v1/notifications/{notification.id}/read"
            )

        assert response.status_code == 404, response.text

        db.expire_all()
        persisted = db.get(Notification, notification.id)
        assert persisted is not None
        assert persisted.read_at is None


def test_cannot_access_notification_from_another_tenant() -> None:
    with TestingSessionLocal() as db:
        user_a, organization_a = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        user_b, organization_b = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )
        notification = create_test_notification(
            db,
            user=user_b,
            organization=organization_b,
        )

        with request_as(user=user_a, organization=organization_a) as client:
            response = client.patch(
                f"/api/v1/notifications/{notification.id}/read"
            )

        assert response.status_code == 404, response.text


def test_duplicate_event_key_returns_existing_notification() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )

        first = create_notification(
            db,
            organization_id=organization.id,
            recipient_user_id=user.id,
            event_type="DEAL_UPDATED",
            title="First title",
            message="First message",
            event_key="deal-updated-123",
        )
        db.commit()

        second = create_notification(
            db,
            organization_id=organization.id,
            recipient_user_id=user.id,
            event_type="DEAL_UPDATED",
            title="Duplicate title",
            message="Duplicate message",
            event_key="deal-updated-123",
        )
        db.commit()

        assert second.id == first.id

        persisted = db.scalars(
            select(Notification).where(
                Notification.organization_id == organization.id,
                Notification.recipient_user_id == user.id,
                Notification.event_key == "deal-updated-123",
            )
        ).all()
        assert len(persisted) == 1
        assert persisted[0].title == "First title"


def test_create_notification_rejects_inactive_membership() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.organization_id == organization.id,
            )
        )
        assert membership is not None
        membership.is_active = False
        db.commit()

        with pytest.raises(ValueError, match="active member"):
            create_notification(
                db,
                organization_id=organization.id,
                recipient_user_id=user.id,
                event_type="DEAL_UPDATED",
                title="Deal updated",
                message="A deal was updated.",
            )


def test_create_notification_rejects_inactive_organization() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(db)
        organization.is_active = False
        db.commit()

        with pytest.raises(ValueError, match="active organization"):
            create_notification(
                db,
                organization_id=organization.id,
                recipient_user_id=user.id,
                event_type="DEAL_UPDATED",
                title="Deal updated",
                message="A deal was updated.",
            )


def test_list_notifications_supports_pagination() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )

        for index in range(3):
            create_test_notification(
                db,
                user=user,
                organization=organization,
                event_key=f"pagination-event-{index}",
            )

        with request_as(user=user, organization=organization) as client:
            response = client.get(
                "/api/v1/notifications",
                params={"limit": 2, "offset": 0},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0


def test_list_notifications_rejects_invalid_pagination() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )

        with request_as(user=user, organization=organization) as client:
            response = client.get(
                "/api/v1/notifications",
                params={"limit": 101},
            )

        assert response.status_code == 422, response.text


def test_mark_unknown_notification_returns_404() -> None:
    with TestingSessionLocal() as db:
        user, organization = create_authorized_user(
            db,
            permission_keys=("leads.read",),
        )

        with request_as(user=user, organization=organization) as client:
            response = client.patch(
                f"/api/v1/notifications/{uuid4()}/read"
            )

        assert response.status_code == 404, response.text

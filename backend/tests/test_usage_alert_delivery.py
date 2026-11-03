"""Usage threshold alerts: in-app delivery to administrators through the real outbox (DFR1-017).

The events are produced by the usage ledger and dispatched by the outbox with the governance
handler registered, exactly as the worker does. An alert is reported as delivered only when a
notification was created for an administrator and the outbox marked the event delivered.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, select

from app.db.models.ai_usage_event import AiUsageEvent
from app.db.models.notification import Notification
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.outbox_event import OutboxEvent
from app.db.session import SessionLocal
from app.governance.alert_delivery import (
    ALERT_NOTIFICATION_EVENT_TYPE,
    register_governance_handlers,
)
from app.governance.usage_ledger import (
    THRESHOLD_EVENT_TYPE,
    UsageUnit,
    configure_budget,
    reserve,
)
from app.outbox.service import dispatch_due_events, unregister_handler
from tests.test_team_api import create_manager, create_owner_manager

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def handlers() -> Iterator[None]:
    register_governance_handlers()
    yield
    unregister_handler(THRESHOLD_EVENT_TYPE)


@pytest.fixture
def org_with_admin() -> Iterator[tuple[UUID, UUID, UUID]]:
    admin, organization = create_owner_manager(permissions=("governance.budgets.manage",))
    reader, _ = create_manager(permissions=("governance.usage.read",))
    # The reader is in another organization; it must never receive this organization's alerts.
    yield organization.id, admin.id, reader.id
    with SessionLocal() as db:
        db.execute(delete(Notification).where(Notification.organization_id == organization.id))
        db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization.id))
        db.execute(delete(AiUsageEvent).where(AiUsageEvent.organization_id == organization.id))
        db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization.id))
        db.commit()


def _cross_threshold(organization_id: UUID, *, max_attempts: int | None = None) -> None:
    with SessionLocal() as db:
        db.expire_on_commit = False
        configure_budget(db, organization_id=organization_id, unit=UsageUnit.TOKENS_OUTPUT,
                         limit_quantity=100, moment=NOW)
        reserve(db, organization_id=organization_id, unit=UsageUnit.TOKENS_OUTPUT, quantity=70,
                idempotency_key="alert-trigger", occurred_at=NOW)
        db.commit()


def _dispatch():
    # Threshold events are stamped with the wall clock, as in production, so dispatch uses it too.
    with SessionLocal() as db:
        result = dispatch_due_events(
            db, worker_id="alert-test", now=datetime.now(UTC) + timedelta(minutes=5), batch_size=50
        )
        db.commit()
        return result


def _events(organization_id: UUID) -> list[OutboxEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(OutboxEvent).where(OutboxEvent.organization_id == organization_id,
                                                          OutboxEvent.event_type == THRESHOLD_EVENT_TYPE)).all())


def _alert_notifications(organization_id: UUID) -> list[Notification]:
    with SessionLocal() as db:
        return list(db.scalars(select(Notification).where(
            Notification.organization_id == organization_id,
            Notification.event_type == ALERT_NOTIFICATION_EVENT_TYPE,
        )).all())


def test_threshold_alert_reaches_the_administrator_and_is_marked_delivered(handlers, org_with_admin) -> None:
    organization_id, admin_id, _ = org_with_admin
    _cross_threshold(organization_id)
    assert [event.status for event in _events(organization_id)] == ["pending"], "enqueued is not delivered"

    _dispatch()

    events = _events(organization_id)
    assert [event.status for event in events] == [OutboxEvent.STATUS_DELIVERED]
    notifications = _alert_notifications(organization_id)
    assert [(item.recipient_user_id, item.resource_type) for item in notifications] == [
        (admin_id, "organization_usage_budget")
    ]


def test_users_without_budget_permission_do_not_receive_the_alert(handlers, org_with_admin) -> None:
    organization_id, admin_id, reader_id = org_with_admin
    _cross_threshold(organization_id)

    _dispatch()

    recipients = {item.recipient_user_id for item in _alert_notifications(organization_id)}
    assert reader_id not in recipients
    assert admin_id in recipients


def test_redelivery_of_the_same_alert_creates_no_duplicate_notification(handlers, org_with_admin) -> None:
    organization_id, _, _ = org_with_admin
    _cross_threshold(organization_id)
    _dispatch()

    # Run the handler again for the same event, as a retry after a crash would.
    from app.governance.alert_delivery import deliver_usage_threshold_alert

    with SessionLocal() as db:
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.organization_id == organization_id,
                                                    OutboxEvent.event_type == THRESHOLD_EVENT_TYPE))
        deliver_usage_threshold_alert(db, event)
        db.commit()

    assert len(_alert_notifications(organization_id)) == 1


def test_alert_with_no_administrator_is_dead_lettered_not_reported_delivered(handlers) -> None:
    # An organization whose only member has no budget permission cannot receive the alert.
    _, organization = create_manager(permissions=("governance.usage.read",))
    try:
        _cross_threshold(organization.id)
        _dispatch()

        events = _events(organization.id)
        assert [event.status for event in events] != [OutboxEvent.STATUS_DELIVERED]
        assert _alert_notifications(organization.id) == []
    finally:
        with SessionLocal() as db:
            db.execute(delete(OutboxEvent).where(OutboxEvent.organization_id == organization.id))
            db.execute(delete(AiUsageEvent).where(AiUsageEvent.organization_id == organization.id))
            db.execute(delete(OrganizationUsageBudget).where(OrganizationUsageBudget.organization_id == organization.id))
            db.commit()

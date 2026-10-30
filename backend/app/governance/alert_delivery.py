"""Deliver AI usage threshold alerts to organization administrators (DFR1-017).

The usage ledger enqueues ``ai.usage.threshold_reached`` when a budget crosses 70, 85 or 100
percent. This handler turns the event into in-app notifications for the people who can change the
budget (holders of ``governance.budgets.manage``). No email, SMS or external message is sent.

Delivery rules:
- Each eligible administrator gets one notification, keyed by event, unit, period, threshold
  and recipient, so retries do not duplicate it.
- An administrator who has turned off notifications for this type is skipped. That is their
  preference, not a failure.
- If no notification can be created at all (no administrator, or every administrator has
  notifications off), the handler raises. The outbox then retries and, when the attempt budget is
  spent, dead-letters the event. An alert is never reported as delivered when nothing was created.
- An event is marked delivered only after this handler returns without error.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.permissions import OWNER_ROLE_NAME
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.governance.usage_ledger import THRESHOLD_EVENT_TYPE
from app.notifications.service import create_notification
from app.outbox.service import register_handler

ALERT_NOTIFICATION_EVENT_TYPE = "AI_USAGE_THRESHOLD"
BUDGET_MANAGE_PERMISSION = "governance.budgets.manage"


class AlertDeliveryError(Exception):
    """Raised when an alert could not be delivered to any administrator."""


def administrator_user_ids(db: Session, *, organization_id: UUID) -> list[UUID]:
    """Users with an active membership in the organization whose role grants budget management."""
    rows = db.scalars(
        select(Membership.user_id)
        .join(MembershipRole, MembershipRole.membership_id == Membership.id)
        .join(Role, Role.id == MembershipRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.organization_id == organization_id,
            Membership.is_active.is_(True),
            Role.organization_id == organization_id,
            Role.is_active.is_(True),
            # Owner-only keys count only through the system Owner role, as in the permission check.
            Role.is_system.is_(True),
            Role.name == OWNER_ROLE_NAME,
            Permission.key == BUDGET_MANAGE_PERMISSION,
            Permission.is_active.is_(True),
            User.is_active.is_(True),
        )
        .distinct()
    ).all()
    return sorted(set(rows), key=str)


def deliver_usage_threshold_alert(db: Session, event) -> None:
    """Outbox handler: create in-app notifications for the organization's administrators."""
    payload = event.payload
    unit = payload.get("unit")
    threshold = payload.get("threshold_percent")
    period_start = payload.get("period_start")
    if not isinstance(unit, str) or not isinstance(threshold, int) or not isinstance(period_start, str):
        raise AlertDeliveryError("Usage alert payload is incomplete.")

    recipients = administrator_user_ids(db, organization_id=event.organization_id)
    if not recipients:
        raise AlertDeliveryError("No administrator can receive this usage alert.")

    created = 0
    for user_id in recipients:
        notification = create_notification(
            db,
            organization_id=event.organization_id,
            recipient_user_id=user_id,
            event_type=ALERT_NOTIFICATION_EVENT_TYPE,
            title=f"AI usage reached {threshold}% of its budget",
            message=(
                f"{unit} usage for the period starting {period_start} has reached {threshold}% "
                "of the organization limit. New billable AI work is refused at 100%."
            ),
            resource_type="organization_usage_budget",
            resource_id=event.aggregate_id,
            event_key=f"{event.idempotency_key}:{user_id}",
        )
        if notification is not None:
            created += 1

    if created == 0:
        raise AlertDeliveryError("No administrator notification could be created.")


def register_governance_handlers() -> None:
    """Register every governance outbox handler. Safe to call more than once."""
    register_handler(THRESHOLD_EVENT_TYPE, deliver_usage_threshold_alert)

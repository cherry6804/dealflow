"""Deliver AI usage threshold alerts to organization administrators (DFR1-017, WS3).

The usage ledger enqueues ``ai.usage.threshold_reached`` when a budget crosses 70, 85 or 100
percent. This handler turns the event into in-app notifications for the people who can change the
budget (holders of ``governance.budgets.manage``). No email, SMS or external message is sent.

Delivery rules:
- Each eligible administrator gets one notification, keyed by event, unit, period, threshold
  and recipient, so retries and replays do not duplicate it.
- An administrator who has turned off notifications for this type is skipped. That is their
  preference, not a failure.
- The budget's ``last_alert_percent`` advances to the threshold only in the transaction that
  records a successful delivery (WS3, decision D-5). An alert that failed or was dead-lettered
  does not advance it, so an operator replay re-announces it.
- If no administrator can receive the alert, or none accepts notifications, the handler raises a
  permanent error. The event is dead-lettered at once with a reason code instead of being retried.
  An operator replays it after the configuration is corrected.
- An event is marked delivered only after this handler returns without error.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.permissions import OWNER_ROLE_NAME
from app.db.models.membership import Membership
from app.db.models.membership_role import MembershipRole
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User
from app.governance.alert_thresholds import (
    MAX_THRESHOLD,
    MIN_THRESHOLD,
    read_alert_thresholds,
)
from app.governance.usage_ledger import THRESHOLD_EVENT_TYPE
from app.notifications.service import create_notification
from app.outbox.service import PermanentHandlerError, register_handler

ALERT_NOTIFICATION_EVENT_TYPE = "AI_USAGE_THRESHOLD"
BUDGET_MANAGE_PERMISSION = "governance.budgets.manage"

REASON_INVALID_PAYLOAD = "invalid_alert_payload"
REASON_BUDGET_NOT_FOUND = "budget_not_found"
REASON_NO_ADMINISTRATOR = "no_administrator"
REASON_NO_RECIPIENT_ACCEPTS_ALERTS = "no_recipient_accepts_alerts"


class AlertDeliveryError(PermanentHandlerError):
    """An alert cannot be delivered and another attempt cannot fix it."""


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
    """Outbox handler: notify administrators, then advance the budget's alert state."""
    payload = event.payload
    unit = payload.get("unit")
    threshold = payload.get("threshold_percent")
    period_start = payload.get("period_start")
    if (
        not isinstance(unit, str)
        or not isinstance(threshold, int)
        or isinstance(threshold, bool)
        or not MIN_THRESHOLD <= threshold <= MAX_THRESHOLD
        or not isinstance(period_start, str)
    ):
        raise AlertDeliveryError("Usage alert payload is incomplete.", reason_code=REASON_INVALID_PAYLOAD)

    try:
        budget_id = UUID(event.aggregate_id)
    except ValueError as exc:
        raise AlertDeliveryError("Usage alert aggregate is not a budget identifier.", reason_code=REASON_INVALID_PAYLOAD) from exc
    budget = db.scalar(
        select(OrganizationUsageBudget)
        .where(
            OrganizationUsageBudget.id == budget_id,
            OrganizationUsageBudget.organization_id == event.organization_id,
        )
        .with_for_update()
    )
    if budget is None:
        raise AlertDeliveryError("The usage budget for this alert no longer exists.", reason_code=REASON_BUDGET_NOT_FOUND)

    recipients = administrator_user_ids(db, organization_id=event.organization_id)
    if not recipients:
        raise AlertDeliveryError(
            "No administrator can receive this usage alert.", reason_code=REASON_NO_ADMINISTRATOR
        )

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
        raise AlertDeliveryError(
            "No administrator accepts notifications for this alert.",
            reason_code=REASON_NO_RECIPIENT_ACCEPTS_ALERTS,
        )

    # Delivery covers this threshold and every configured threshold below it. Those lower alerts are
    # superseded by this one, as they were before configurable thresholds. A lower threshold that is
    # configured later is still announced on its own, because it is not in this list.
    settings = read_alert_thresholds(db, organization_id=event.organization_id)
    covered = {t for t in settings.values if t <= threshold} | {threshold}
    budget.alerted_thresholds = sorted(set(budget.alerted_thresholds or []) | covered)
    budget.last_alert_percent = max(budget.last_alert_percent, threshold)


def register_governance_handlers() -> None:
    """Register every governance outbox handler. Safe to call more than once."""
    register_handler(THRESHOLD_EVENT_TYPE, deliver_usage_threshold_alert)

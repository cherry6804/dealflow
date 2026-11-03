"""Change an organization's AI usage alert thresholds, with an audit record (WS6 WP2).

The caller is an owner, enforced at the route by ``governance.budgets.manage``. This service also
validates the values, so no other entry point can store an invalid set.

Ordering, for concurrency: the current-period budgets are locked first, in id order, and the
threshold row is written second. Usage changes lock a budget before they read the thresholds. So a
usage change either sees the old thresholds, or waits and then sees the new ones. Both paths queue
the same idempotent alert keys, so a concurrent change never queues a duplicate.

A change that does not alter the effective thresholds writes nothing and creates no audit record.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.attribution import user_attribution
from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_REQUESTED,
    persist_independent_audit_event,
)
from app.db.models.audit_event import AuditEvent
from app.db.models.organization_usage_budget import OrganizationUsageBudget
from app.governance.alert_thresholds import (
    AlertThresholds,
    read_alert_thresholds,
    store_alert_thresholds,
    validate_alert_thresholds,
)
from app.governance.usage_ledger import announce_pending_threshold, budget_period_for

THRESHOLD_SETTINGS_EVENT_TYPE = "governance"
THRESHOLD_SETTINGS_ACTION = "governance.alert_thresholds.updated"
THRESHOLD_SETTINGS_PERMISSION = "governance.budgets.manage"


def update_alert_thresholds(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: UUID,
    values: list[int] | tuple[int, ...],
    moment: datetime | None = None,
) -> AlertThresholds:
    """Validate and store new thresholds, audit the change, and evaluate current budgets.

    The caller owns the transaction and must commit. Raises ``InvalidAlertThresholdsError`` before
    any write when the values break a rule.
    """
    new_values = validate_alert_thresholds(values)
    current = moment if moment is not None else datetime.now(UTC)
    period = budget_period_for(current)

    budgets = list(
        db.scalars(
            select(OrganizationUsageBudget)
            .where(
                OrganizationUsageBudget.organization_id == organization_id,
                OrganizationUsageBudget.period_start == period.start,
            )
            .order_by(OrganizationUsageBudget.id)
            .with_for_update()
        ).all()
    )

    previous = read_alert_thresholds(db, organization_id=organization_id)
    if previous.values == new_values:
        return previous

    # Requested record first, committed independently. If it cannot be written, nothing changes (WP3).
    requested = persist_independent_audit_event(
        db,
        attribution=user_attribution(
            organization_id=organization_id, actor_user_id=actor_user_id
        ),
        event_type=THRESHOLD_SETTINGS_EVENT_TYPE,
        action=THRESHOLD_SETTINGS_ACTION,
        decision="allowed",
        outcome=OUTCOME_REQUESTED,
        permission_key=THRESHOLD_SETTINGS_PERMISSION,
        resource_type="organization_usage_alert_settings",
        resource_id=str(organization_id),
        metadata={
            "before": list(previous.values),
            "requested_after": list(new_values),
            "previous_version": previous.version,
            "period_start": period.start.isoformat(),
        },
    )

    store_alert_thresholds(
        db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        values=new_values,
    )
    stored = read_alert_thresholds(db, organization_id=organization_id)

    db.add(
        AuditEvent(
            user_id=actor_user_id,
            organization_id=organization_id,
            event_type=THRESHOLD_SETTINGS_EVENT_TYPE,
            action=THRESHOLD_SETTINGS_ACTION,
            decision="allowed",
            outcome=OUTCOME_COMPLETED,
            causation_id=str(requested.id),
            correlation_id=requested.correlation_id,
            permission_key=THRESHOLD_SETTINGS_PERMISSION,
            resource_type="organization_usage_alert_settings",
            resource_id=str(organization_id),
            event_metadata=json.dumps(
                {
                    "before": list(previous.values),
                    "after": list(stored.values),
                    "previous_version": previous.version,
                    "new_version": stored.version,
                    "period_start": period.start.isoformat(),
                },
                sort_keys=True,
            ),
        )
    )
    db.flush()

    # Thresholds that current usage already reaches are announced now, not on some later usage change.
    for budget in budgets:
        announce_pending_threshold(db, budget=budget)
    db.flush()
    return stored

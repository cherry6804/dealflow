
"""Event-driven execution of tenant-scoped automation rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserContext
from app.db.models.automation_execution import AutomationExecution
from app.db.models.automation_rule import AutomationRule
from app.db.models.deal import Deal
from app.follow_ups.schemas import FollowUpCreateRequest
from app.follow_ups.service import create_follow_up
from app.governance.capabilities import AUTOMATION_DEAL_CREATED_RULES
from app.governance.execution_gate import ExecutionRequest, authorize_execution
from app.notifications.service import create_notification


SUPPORTED_CONDITION_FIELDS = {
    "stage",
    "expected_value",
    "currency",
    "owner_user_id",
    "lead_id",
    "customer_profile_id",
    "property_id",
    "notes",
}

SUPPORTED_OPERATORS = {
    "equals",
    "not_equals",
    "in",
    "not_in",
    "exists",
}


class AutomationConditionError(ValueError):
    """Raised when a rule contains an unsupported or invalid condition."""


def _evaluate_conditions(
    conditions: list[dict[str, Any]],
    deal: Deal,
) -> bool:
    """Evaluate all configured conditions using AND semantics."""

    for condition in conditions:
        if not isinstance(condition, dict):
            raise AutomationConditionError(
                "Each automation condition must be an object."
            )

        field = condition.get("field")
        operator = condition.get("operator")

        if not isinstance(field, str) or field not in SUPPORTED_CONDITION_FIELDS:
            raise AutomationConditionError(
                f"Unsupported condition field: {field!r}."
            )

        if (
            not isinstance(operator, str)
            or operator not in SUPPORTED_OPERATORS
        ):
            raise AutomationConditionError(
                f"Unsupported condition operator: {operator!r}."
            )

        # All supported operators require an explicit value.
        if "value" not in condition:
            raise AutomationConditionError(
                f"Condition {field!r} requires a value."
            )

        actual = getattr(deal, field)
        expected = condition["value"]

        if operator == "equals":
            matched = actual == expected

        elif operator == "not_equals":
            matched = actual != expected

        elif operator == "in":
            if not isinstance(expected, list):
                raise AutomationConditionError(
                    "The 'in' operator requires a list value."
                )
            matched = actual in expected

        elif operator == "not_in":
            if not isinstance(expected, list):
                raise AutomationConditionError(
                    "The 'not_in' operator requires a list value."
                )
            matched = actual not in expected

        else:  # exists
            if not isinstance(expected, bool):
                raise AutomationConditionError(
                    "The 'exists' operator requires a boolean value."
                )
            matched = (actual is not None) == expected

        if not matched:
            return False

    return True


def _execute_create_follow_up(
    db: Session,
    *,
    organization_id: UUID,
    deal: Deal,
    action: dict[str, Any],
) -> dict[str, Any]:
    """Create a follow-up from a supported automation action."""

    config = action.get("config", {})
    if not isinstance(config, dict):
        raise ValueError("CREATE_FOLLOW_UP config must be an object.")

    if deal.lead_id is None:
        return {
            "action_type": "CREATE_FOLLOW_UP",
            "status": "SKIPPED",
            "reason": "The deal has no linked lead; follow-ups require a lead.",
        }

    days_after = config.get("days_after", 1)
    if (
        isinstance(days_after, bool)
        or not isinstance(days_after, int)
        or days_after < 0
        or days_after > 3650
    ):
        raise ValueError(
            "days_after must be an integer between 0 and 3650."
        )

    title = config.get("title", f"Follow up on deal {deal.id}")
    follow_up_type = config.get("follow_up_type", "TASK")
    description = config.get(
        "description",
        f"Automatically created for deal {deal.id}.",
    )

    payload = FollowUpCreateRequest(
        follow_up_type=follow_up_type,
        title=title,
        description=description,
        due_at=datetime.now(timezone.utc) + timedelta(days=days_after),
        owner_user_id=deal.owner_user_id,
    )

    follow_up = create_follow_up(
        db,
        organization_id=organization_id,
        current_user_id=deal.owner_user_id,
        lead_id=deal.lead_id,
        payload=payload,
    )

    if follow_up is None:
        return {
            "action_type": "CREATE_FOLLOW_UP",
            "status": "SKIPPED",
            "reason": "The linked lead was not found in the organization.",
        }

    return {
        "action_type": "CREATE_FOLLOW_UP",
        "status": "SUCCEEDED",
        "follow_up_id": str(follow_up.id),
        "due_at": follow_up.due_at.isoformat(),
    }


def _execute_action(
    db: Session,
    *,
    organization_id: UUID,
    deal: Deal,
    action: dict[str, Any],
) -> dict[str, Any]:
    """Execute one explicitly supported automation action."""

    if not isinstance(action, dict):
        raise ValueError("Each automation action must be an object.")

    action_type = action.get("type")

    if action_type == "CREATE_FOLLOW_UP":
        return _execute_create_follow_up(
            db,
            organization_id=organization_id,
            deal=deal,
            action=action,
        )

    raise ValueError(f"Unsupported automation action: {action_type!r}.")


def _notify_automation_execution(
    db: Session,
    *,
    organization_id: UUID,
    rule: AutomationRule,
    execution: AutomationExecution,
    deal: Deal,
) -> None:
    """Notify the rule creator about a recorded execution outcome.

    The notification is written in the same transaction as the execution.
    Notification preferences and recipient membership are enforced by
    create_notification. The caller remains responsible for committing.
    """

    status_details = {
        AutomationExecution.STATUS_SUCCEEDED: (
            "Automation completed",
            "completed successfully",
        ),
        AutomationExecution.STATUS_PARTIAL: (
            "Automation partially completed",
            "completed with some actions skipped or failed",
        ),
        AutomationExecution.STATUS_FAILED: (
            "Automation failed",
            "failed",
        ),
        AutomationExecution.STATUS_SKIPPED: (
            "Automation skipped",
            "was skipped",
        ),
    }

    details = status_details.get(execution.status)
    if details is None:
        # Do not send notifications for intermediate or unknown states.
        return

    title, outcome = details

    create_notification(
        db,
        organization_id=organization_id,
        recipient_user_id=rule.created_by_user_id,
        event_type=f"AUTOMATION_EXECUTION_{execution.status}",
        title=title,
        message=(
            f"Automation rule '{rule.name}' {outcome} "
            f"for deal {deal.id}."
        ),
        resource_type="automation_execution",
        resource_id=str(execution.id),
        event_key=f"automation-execution:{execution.id}:completed",
    )


def _gate_step(
    db: Session,
    *,
    organization_id: UUID,
    user_context: CurrentUserContext | None,
    deal: Deal,
    stage: str,
    resource_type: str,
    resource_id: str,
    resource_active: bool,
) -> bool:
    """Run one centralized execution decision for a deal-created automation step."""
    decision = authorize_execution(
        db,
        ExecutionRequest(
            organization_id=organization_id,
            capability_key=AUTOMATION_DEAL_CREATED_RULES,
            actor=user_context,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_organization_id=deal.organization_id,
            resource_active=resource_active,
            required_permission="deals.create",
            stage=stage,
        ),
    )
    return decision.allowed


def _action_allowed(
    db: Session,
    *,
    organization_id: UUID,
    user_context: CurrentUserContext | None,
    deal: Deal,
    rule: AutomationRule,
    position: int,
) -> bool:
    """Revalidate the governance gate, and the rule's status, before one action."""
    db.refresh(rule)
    return _gate_step(
        db,
        organization_id=organization_id,
        user_context=user_context,
        deal=deal,
        stage="action",
        resource_type="automation_action",
        resource_id=f"{rule.id}:{position}",
        resource_active=rule.status == AutomationRule.STATUS_ACTIVE,
    )


def execute_deal_created_automations(
    db: Session,
    *,
    organization_id: UUID,
    deal: Deal,
    user_context: CurrentUserContext | None,
) -> list[AutomationExecution]:
    """Execute active DEAL_CREATED rules for a deal in its organization.

    The caller owns the transaction. This function never commits.

    The unique event/rule constraint provides duplicate protection.
    Each rule runs inside a savepoint so an expected action/configuration
    failure can be recorded without discarding the deal or other rules.
    Unexpected database errors propagate to the caller for rollback.
    """

    if deal.organization_id != organization_id:
        raise ValueError(
            "The deal does not belong to the requested organization."
        )

    # Governance gate (DFR1-006): deal-created automations are disabled by default. A denial
    # creates no executions and leaves the deal untouched, so manual CRM work continues.
    # The gate is audited whether it allows or denies.
    if not _gate_step(
        db,
        organization_id=organization_id,
        user_context=user_context,
        deal=deal,
        stage="initial",
        resource_type="deal",
        resource_id=str(deal.id),
        resource_active=True,
    ):
        return []

    rules = list(
        db.scalars(
            select(AutomationRule)
            .where(
                AutomationRule.organization_id == organization_id,
                AutomationRule.trigger_type == "DEAL_CREATED",
                AutomationRule.status == AutomationRule.STATUS_ACTIVE,
            )
            .order_by(AutomationRule.created_at, AutomationRule.id)
        ).all()
    )

    executions: list[AutomationExecution] = []

    for index, rule in enumerate(rules):
        if index > 0:
            # In-flight revalidation: a switch turned off, a lost entitlement or a paused rule
            # during this run stops the remaining rules. Rules already run are kept.
            db.refresh(rule)
            if not _gate_step(
                db,
                organization_id=organization_id,
                user_context=user_context,
                deal=deal,
                stage="revalidation",
                resource_type="automation_rule",
                resource_id=str(rule.id),
                resource_active=rule.status == AutomationRule.STATUS_ACTIVE,
            ):
                break
        try:
            # A savepoint isolates a duplicate insert or a failure in this
            # rule from the surrounding deal-creation transaction.
            with db.begin_nested():
                execution = AutomationExecution(
                    organization_id=organization_id,
                    rule_id=rule.id,
                    event_type="DEAL_CREATED",
                    event_id=deal.id,
                    status=AutomationExecution.STATUS_RUNNING,
                    action_results=[],
                    started_at=datetime.now(timezone.utc),
                )
                db.add(execution)
                db.flush()

                try:
                    matches = _evaluate_conditions(
                        rule.conditions or [],
                        deal,
                    )
                except AutomationConditionError as exc:
                    execution.status = AutomationExecution.STATUS_FAILED
                    execution.error_message = str(exc)
                    execution.action_results = [
                        {
                            "status": "FAILED",
                            "reason": str(exc),
                        }
                    ]
                else:
                    if not matches:
                        execution.status = AutomationExecution.STATUS_SKIPPED
                        execution.action_results = [
                            {
                                "status": "SKIPPED",
                                "reason": "Rule conditions did not match.",
                            }
                        ]
                    else:
                        results: list[dict[str, Any]] = []

                        stopped_by_governance = False
                        for position, action in enumerate(rule.actions or []):
                            # Revalidation before every action (DFR1-006). A switch turned off, a
                            # lost entitlement or a paused rule stops this and the remaining actions.
                            if stopped_by_governance or not _action_allowed(
                                db,
                                organization_id=organization_id,
                                user_context=user_context,
                                deal=deal,
                                rule=rule,
                                position=position,
                            ):
                                stopped_by_governance = True
                                results.append(
                                    {
                                        "action_type": (
                                            action.get("type")
                                            if isinstance(action, dict)
                                            else None
                                        ),
                                        "status": "SKIPPED",
                                        "reason": "Stopped by a governance check.",
                                    }
                                )
                                continue
                            try:
                                result = _execute_action(
                                    db,
                                    organization_id=organization_id,
                                    deal=deal,
                                    action=action,
                                )
                            except ValueError as exc:
                                action_type = (
                                    action.get("type")
                                    if isinstance(action, dict)
                                    else None
                                )
                                result = {
                                    "action_type": action_type,
                                    "status": "FAILED",
                                    "reason": str(exc),
                                }

                            results.append(result)

                        execution.action_results = results

                        action_statuses = [
                            item["status"] for item in results
                        ]

                        succeeded = action_statuses.count("SUCCEEDED")
                        failed = action_statuses.count("FAILED")

                        if not action_statuses or (
                            stopped_by_governance and not succeeded
                        ):
                            execution.status = (
                                AutomationExecution.STATUS_SKIPPED
                            )
                        elif succeeded and (
                            failed or "SKIPPED" in action_statuses
                        ):
                            execution.status = (
                                AutomationExecution.STATUS_PARTIAL
                            )
                        elif failed:
                            execution.status = (
                                AutomationExecution.STATUS_FAILED
                            )
                        elif succeeded:
                            execution.status = (
                                AutomationExecution.STATUS_SUCCEEDED
                            )
                        else:
                            execution.status = (
                                AutomationExecution.STATUS_SKIPPED
                            )

                        if failed:
                            execution.error_message = (
                                "One or more automation actions failed."
                            )

                execution.completed_at = datetime.now(timezone.utc)
                db.flush()

                # This uses the persisted execution ID as a stable
                # notification key, so retries cannot create a second
                # execution or a second notification for the same event.
                _notify_automation_execution(
                    db,
                    organization_id=organization_id,
                    rule=rule,
                    execution=execution,
                    deal=deal,
                )

                db.flush()
                executions.append(execution)

        except IntegrityError as exc:
            # A duplicate event/rule pair is expected during retries or
            # concurrent processing. Only suppress this specific conflict.
            constraint_name = getattr(
                getattr(exc.orig, "diag", None),
                "constraint_name",
                None,
            )
            if constraint_name != "uq_automation_execution_event_rule":
                raise

            # The existing execution already represents this rule/event.
            continue

    return executions

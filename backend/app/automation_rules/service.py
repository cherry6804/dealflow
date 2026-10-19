
"""Business logic for tenant-scoped automation rules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.automation_rules.execution_service import (
    SUPPORTED_CONDITION_FIELDS,
    SUPPORTED_OPERATORS,
)
from app.automation_rules.schemas import (
    AutomationRuleCreateRequest,
    AutomationRuleUpdateRequest,
)
from app.db.models.automation_rule import AutomationRule
from app.follow_ups.schemas import FollowUpCreateRequest


SUPPORTED_TRIGGER_TYPE = "DEAL_CREATED"
SUPPORTED_ACTION_TYPE = "CREATE_FOLLOW_UP"

SUPPORTED_TRIGGER_CONFIG_KEYS = {"source"}
SUPPORTED_TRIGGER_SOURCES = {"deals"}

SUPPORTED_ACTION_CONFIG_KEYS = {
    "days_after",
    "title",
    "description",
    "follow_up_type",
}


def _validate_conditions(conditions: Any) -> None:
    """Validate conditions against the operators supported by execution."""
    if not isinstance(conditions, list):
        raise ValueError("Automation conditions must be a list.")

    for index, condition in enumerate(conditions):
        if not isinstance(condition, dict):
            raise ValueError(
                f"Condition {index + 1} must be an object."
            )

        field = condition.get("field")
        operator = condition.get("operator")

        if (
            not isinstance(field, str)
            or field not in SUPPORTED_CONDITION_FIELDS
        ):
            raise ValueError(
                f"Condition {index + 1} has an unsupported field: "
                f"{field!r}."
            )

        if (
            not isinstance(operator, str)
            or operator not in SUPPORTED_OPERATORS
        ):
            raise ValueError(
                f"Condition {index + 1} has an unsupported operator: "
                f"{operator!r}."
            )

        if "value" not in condition:
            raise ValueError(
                f"Condition {index + 1} must include a value."
            )

        value = condition["value"]

        if operator in {"in", "not_in"} and not isinstance(value, list):
            raise ValueError(
                f"Condition {index + 1} must use a list value for "
                f"operator '{operator}'."
            )

        if operator == "exists" and not isinstance(value, bool):
            raise ValueError(
                f"Condition {index + 1} must use a boolean value "
                "for operator 'exists'."
            )


def _validate_trigger_config(trigger_config: Any) -> None:
    """Validate trigger settings understood by the current engine."""
    if not isinstance(trigger_config, dict):
        raise ValueError("Trigger configuration must be an object.")

    unknown_keys = set(trigger_config) - SUPPORTED_TRIGGER_CONFIG_KEYS
    if unknown_keys:
        raise ValueError(
            "Unsupported trigger configuration key(s): "
            f"{', '.join(sorted(unknown_keys))}."
        )

    source = trigger_config.get("source")
    if source is not None and (
        not isinstance(source, str)
        or source not in SUPPORTED_TRIGGER_SOURCES
    ):
        raise ValueError(
            f"Unsupported DEAL_CREATED trigger source: {source!r}."
        )


def _validate_follow_up_action(action: Any, index: int) -> None:
    """Validate one CREATE_FOLLOW_UP action before rule activation."""
    if not isinstance(action, dict):
        raise ValueError(
            f"Action {index + 1} must be an object."
        )

    action_type = action.get("type")
    if action_type != SUPPORTED_ACTION_TYPE:
        raise ValueError(
            f"Action {index + 1} has an unsupported type: "
            f"{action_type!r}."
        )

    config = action.get("config", {})
    if not isinstance(config, dict):
        raise ValueError(
            f"Action {index + 1} configuration must be an object."
        )

    unknown_keys = set(config) - SUPPORTED_ACTION_CONFIG_KEYS
    if unknown_keys:
        raise ValueError(
            f"Action {index + 1} has unsupported configuration key(s): "
            f"{', '.join(sorted(unknown_keys))}."
        )

    days_after = config.get("days_after", 1)
    if (
        isinstance(days_after, bool)
        or not isinstance(days_after, int)
        or not 0 <= days_after <= 3650
    ):
        raise ValueError(
            f"Action {index + 1} days_after must be an integer "
            "between 0 and 3650."
        )

    title = config.get("title", "Automation follow-up")
    description = config.get("description")
    follow_up_type = config.get("follow_up_type", "TASK")

    try:
        FollowUpCreateRequest(
            follow_up_type=follow_up_type,
            title=title,
            description=description,
            due_at=(
                datetime.now(timezone.utc)
                + timedelta(days=days_after)
            ),
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise ValueError(
            f"Action {index + 1} has invalid follow-up configuration: "
            f"{exc}"
        ) from exc


def _validate_rule_for_activation(rule: AutomationRule) -> None:
    """Reject unsupported or malformed rules before activating them."""
    trigger_type = rule.trigger_type
    if not isinstance(trigger_type, str) or not trigger_type.strip():
        raise ValueError(
            "A trigger type is required before activation."
        )

    if trigger_type != SUPPORTED_TRIGGER_TYPE:
        raise ValueError(
            f"Unsupported trigger type: {trigger_type!r}. "
            f"The supported trigger is {SUPPORTED_TRIGGER_TYPE}."
        )

    _validate_trigger_config(rule.trigger_config)
    _validate_conditions(rule.conditions)

    if not isinstance(rule.actions, list) or not rule.actions:
        raise ValueError(
            "At least one action is required before activation."
        )

    for index, action in enumerate(rule.actions):
        _validate_follow_up_action(action, index)


def create_automation_rule(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    payload: AutomationRuleCreateRequest,
) -> AutomationRule:
    """Create a draft rule for the verified organization."""
    rule = AutomationRule(
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        trigger_type=payload.trigger_type,
        trigger_config=payload.trigger_config,
        conditions=payload.conditions,
        actions=payload.actions,
        status=AutomationRule.STATUS_DRAFT,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )
    db.add(rule)
    db.flush()
    return rule


def get_automation_rule(
    db: Session,
    *,
    organization_id: UUID,
    rule_id: UUID,
) -> AutomationRule | None:
    """Get a rule only when it belongs to the verified organization."""
    return db.scalar(
        select(AutomationRule).where(
            AutomationRule.id == rule_id,
            AutomationRule.organization_id == organization_id,
        )
    )


def list_automation_rules(
    db: Session,
    *,
    organization_id: UUID,
    page: int,
    page_size: int,
    status_filter: str | None = None,
) -> tuple[list[AutomationRule], int]:
    """Return a paginated list of rules for one organization."""
    filters = [AutomationRule.organization_id == organization_id]

    if status_filter is not None:
        filters.append(AutomationRule.status == status_filter)

    total = (
        db.scalar(
            select(func.count())
            .select_from(AutomationRule)
            .where(*filters)
        )
        or 0
    )

    items = db.scalars(
        select(AutomationRule)
        .where(*filters)
        .order_by(
            AutomationRule.created_at.desc(),
            AutomationRule.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return list(items), total


def update_automation_rule(
    db: Session,
    *,
    organization_id: UUID,
    rule_id: UUID,
    user_id: UUID,
    payload: AutomationRuleUpdateRequest,
) -> AutomationRule | None:
    """Update configuration without silently changing the rule's status."""
    rule = get_automation_rule(
        db,
        organization_id=organization_id,
        rule_id=rule_id,
    )
    if rule is None:
        return None

    if rule.status == AutomationRule.STATUS_ACTIVE:
        raise ValueError(
            "Disable an active rule before updating its configuration."
        )

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(rule, field, value)

    rule.updated_by_user_id = user_id
    db.flush()
    return rule


def activate_automation_rule(
    db: Session,
    *,
    organization_id: UUID,
    rule_id: UUID,
    user_id: UUID,
) -> AutomationRule | None:
    """Validate and activate a rule supported by the execution engine."""
    rule = get_automation_rule(
        db,
        organization_id=organization_id,
        rule_id=rule_id,
    )
    if rule is None:
        return None

    if rule.status == AutomationRule.STATUS_ACTIVE:
        raise ValueError("The automation rule is already active.")

    _validate_rule_for_activation(rule)

    rule.status = AutomationRule.STATUS_ACTIVE
    rule.updated_by_user_id = user_id
    db.flush()
    return rule


def disable_automation_rule(
    db: Session,
    *,
    organization_id: UUID,
    rule_id: UUID,
    user_id: UUID,
) -> AutomationRule | None:
    """Disable a rule without deleting its configuration."""
    rule = get_automation_rule(
        db,
        organization_id=organization_id,
        rule_id=rule_id,
    )
    if rule is None:
        return None

    if rule.status == AutomationRule.STATUS_DISABLED:
        raise ValueError("The automation rule is already disabled.")

    rule.status = AutomationRule.STATUS_DISABLED
    rule.updated_by_user_id = user_id
    db.flush()
    return rule

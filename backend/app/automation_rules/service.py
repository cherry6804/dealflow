
"""Business logic for tenant-scoped automation rules."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.automation_rule import AutomationRule
from app.automation_rules.schemas import (
    AutomationRuleCreateRequest,
    AutomationRuleUpdateRequest,
)


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

    total = db.scalar(
        select(func.count())
        .select_from(AutomationRule)
        .where(*filters)
    ) or 0

    items = db.scalars(
        select(AutomationRule)
        .where(*filters)
        .order_by(AutomationRule.created_at.desc(), AutomationRule.id.desc())
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
        raise ValueError("Disable an active rule before updating its configuration.")

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
    """Activate a configured rule; execution is handled by a future component."""
    rule = get_automation_rule(
        db,
        organization_id=organization_id,
        rule_id=rule_id,
    )
    if rule is None:
        return None

    if rule.status == AutomationRule.STATUS_ACTIVE:
        raise ValueError("The automation rule is already active.")

    if not rule.trigger_type.strip():
        raise ValueError("A trigger type is required before activation.")

    if not rule.actions:
        raise ValueError("At least one action is required before activation.")

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

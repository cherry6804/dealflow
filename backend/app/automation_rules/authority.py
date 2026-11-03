"""Authority for automation rules and their actions (WS6 WP5).

An automation rule runs with the authority of people, not of the event that triggered it. This module
decides, on the server, who is allowed to activate a rule and whether each action may run.

Rules of authority:

- **Activation.** Activating a rule needs ``automation.update`` and, for every action in the rule, the
  permission that action maps to. A user cannot activate a rule that does more than they could do
  themselves, so configuring a rule never escalates privilege.
- **Execution.** An action runs only if all of these hold at execution time, checked against the database
  and not against anything stored on the rule:
  1. the rule belongs to the organization, and is active;
  2. the action type is supported (``ACTION_PERMISSIONS``);
  3. the activator, the user who last activated the rule, still has an active membership and still holds
     ``automation.update`` and the action's permission;
  4. the target owner, the deal owner the action is performed for, holds the action's permission.
  The effective privilege is the intersection of these, plus the gate check on the initiating user. The
  user who created the deal does not authorize the action.
- **System actors.** A system actor never reaches this module. The execution gate refuses it first, and no
  service identity exists to authorize background automation.
- **Audit.** A decision is recorded independently (WP3) before the action runs, so a denial survives a
  rollback. A result row is written in the business transaction, so it is rolled back with the work and
  never claims success for work that did not commit.

The activator is the rule's ``updated_by_user_id`` while the rule is active. An active rule cannot be edited,
and activation is the last write that sets it, so no separate column is needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.audit.attribution import user_attribution
from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_DENIED,
    OUTCOME_REQUESTED,
    persist_independent_audit_event,
)
from app.db.models.audit_event import AuditEvent
from app.db.models.automation_rule import AutomationRule
from app.db.models.deal import Deal
from app.governance.execution_gate import actor_permission_granted

AUTOMATION_AUTHORITY_EVENT_TYPE = "automation_authority"
ACTIVATION_PERMISSION = "automation.update"

# The permission each supported action needs. An action type missing here is unsupported and is refused.
ACTION_PERMISSIONS: dict[str, str] = {
    "CREATE_FOLLOW_UP": "leads.update",
}

REASON_ORGANIZATION_MISMATCH = "organization_mismatch"
REASON_RULE_NOT_ACTIVE = "rule_not_active"
REASON_UNSUPPORTED_ACTION = "unsupported_action"
REASON_ACTIVATOR_MISSING = "activator_missing"
REASON_ACTIVATOR_NOT_AUTHORIZED = "activator_not_authorized"
REASON_OWNER_NOT_AUTHORIZED = "target_owner_not_authorized"
REASON_ACTIVATION_NOT_AUTHORIZED = "activation_not_authorized"
REASON_ALLOWED = "allowed"


class AutomationAuthorityError(PermissionError):
    """The user may not activate this rule. ``reason_code`` is stable and safe to show."""

    def __init__(self, reason_code: str, permission_key: str | None = None) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.permission_key = permission_key


class PermissionChecker:
    """Permission lookups for one organization, remembered for the life of one call.

    Each answer is read from the database, so a permission removed after activation is seen at the next
    execution. Nothing is cached across calls.
    """

    def __init__(self, db: Session, organization_id: UUID) -> None:
        self.db = db
        self.organization_id = organization_id
        self._answers: dict[tuple[UUID, str], bool] = {}

    def holds(self, user_id: UUID | None, permission_key: str) -> bool:
        if user_id is None:
            return False
        key = (user_id, permission_key)
        if key not in self._answers:
            self._answers[key] = actor_permission_granted(
                self.db,
                organization_id=self.organization_id,
                user_id=user_id,
                permission_key=permission_key,
            )
        return self._answers[key]


@dataclass(frozen=True)
class ActionAuthorization:
    allowed: bool
    reason_code: str
    permission_key: str | None
    activator_user_id: UUID | None
    owner_user_id: UUID | None


def _action_type(action: Any) -> str | None:
    if isinstance(action, dict) and isinstance(action.get("type"), str):
        return action["type"]
    return None


# --- Activation ---------------------------------------------------------------------------------


def authorize_activation(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    rule: AutomationRule,
) -> None:
    """Raise ``AutomationAuthorityError`` unless ``user_id`` may activate ``rule``.

    A denial is recorded independently first, so it survives the caller rolling back.
    """
    checker = PermissionChecker(db, organization_id)
    denial = _activation_denial(checker, organization_id=organization_id, user_id=user_id, rule=rule)
    if denial is None:
        return
    reason_code, permission_key = denial
    persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=user_id),
        event_type=AUTOMATION_AUTHORITY_EVENT_TYPE,
        action="automation.rule.activate",
        decision="denied",
        outcome=OUTCOME_DENIED,
        permission_key=permission_key,
        resource_type="automation_rule",
        resource_id=str(rule.id),
        metadata={"reason_code": reason_code, "rule_id": str(rule.id)},
    )
    raise AutomationAuthorityError(reason_code, permission_key)


def _activation_denial(
    checker: PermissionChecker,
    *,
    organization_id: UUID,
    user_id: UUID,
    rule: AutomationRule,
) -> tuple[str, str | None] | None:
    if rule.organization_id != organization_id:
        return REASON_ORGANIZATION_MISMATCH, None
    if not checker.holds(user_id, ACTIVATION_PERMISSION):
        return REASON_ACTIVATION_NOT_AUTHORIZED, ACTIVATION_PERMISSION
    for action in rule.actions or []:
        permission_key = ACTION_PERMISSIONS.get(_action_type(action) or "")
        if permission_key is None:
            return REASON_UNSUPPORTED_ACTION, None
        if not checker.holds(user_id, permission_key):
            return REASON_ACTIVATION_NOT_AUTHORIZED, permission_key
    return None


def begin_activation_audit(
    db: Session, *, organization_id: UUID, user_id: UUID, rule: AutomationRule
) -> AuditEvent:
    """Record that activation is about to happen, independently. Raises if it cannot be written."""
    return persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=user_id),
        event_type=AUTOMATION_AUTHORITY_EVENT_TYPE,
        action="automation.rule.activate",
        decision="allowed",
        outcome=OUTCOME_REQUESTED,
        permission_key=ACTIVATION_PERMISSION,
        resource_type="automation_rule",
        resource_id=str(rule.id),
        metadata={"rule_id": str(rule.id), "action_count": len(rule.actions or [])},
    )


def complete_activation_audit(
    db: Session,
    *,
    requested: AuditEvent,
    organization_id: UUID,
    user_id: UUID,
    rule: AutomationRule,
) -> None:
    """Record the completed activation in the business transaction, so a rollback leaves no completion."""
    db.add(
        AuditEvent(
            user_id=user_id,
            organization_id=organization_id,
            event_type=AUTOMATION_AUTHORITY_EVENT_TYPE,
            action="automation.rule.activate",
            decision="allowed",
            outcome=OUTCOME_COMPLETED,
            causation_id=str(requested.id),
            permission_key=ACTIVATION_PERMISSION,
            resource_type="automation_rule",
            resource_id=str(rule.id),
            event_metadata=json.dumps({"rule_id": str(rule.id)}, sort_keys=True),
        )
    )
    db.flush()


# --- Execution ----------------------------------------------------------------------------------


def authorize_action(
    checker: PermissionChecker,
    *,
    rule: AutomationRule,
    deal: Deal,
    action_type: str | None,
) -> ActionAuthorization:
    """Decide whether one action of an active rule may run for this deal now. First failure decides."""
    activator = rule.updated_by_user_id
    owner = deal.owner_user_id
    permission_key = ACTION_PERMISSIONS.get(action_type or "")

    def decide(allowed: bool, reason: str) -> ActionAuthorization:
        return ActionAuthorization(
            allowed=allowed,
            reason_code=reason,
            permission_key=permission_key,
            activator_user_id=activator,
            owner_user_id=owner,
        )

    if not (rule.organization_id == deal.organization_id == checker.organization_id):
        return decide(False, REASON_ORGANIZATION_MISMATCH)
    if rule.status != AutomationRule.STATUS_ACTIVE:
        return decide(False, REASON_RULE_NOT_ACTIVE)
    if permission_key is None:
        return decide(False, REASON_UNSUPPORTED_ACTION)
    if activator is None:
        return decide(False, REASON_ACTIVATOR_MISSING)
    if not (checker.holds(activator, ACTIVATION_PERMISSION) and checker.holds(activator, permission_key)):
        return decide(False, REASON_ACTIVATOR_NOT_AUTHORIZED)
    if not checker.holds(owner, permission_key):
        return decide(False, REASON_OWNER_NOT_AUTHORIZED)
    return decide(True, REASON_ALLOWED)


def audit_action_decision(
    db: Session,
    *,
    initiator_user_id: UUID,
    rule: AutomationRule,
    deal: Deal,
    index: int,
    action_type: str | None,
    authorization: ActionAuthorization,
) -> AuditEvent:
    """Record the decision independently, before the action runs. A repeat for the same action is a no-op.

    Raises ``AuditPersistenceError`` when it cannot be written. The caller must then not run the action.
    """
    return persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=rule.organization_id, actor_user_id=initiator_user_id),
        event_type=AUTOMATION_AUTHORITY_EVENT_TYPE,
        action="automation.action.authorize",
        decision="allowed" if authorization.allowed else "denied",
        outcome=OUTCOME_REQUESTED if authorization.allowed else OUTCOME_DENIED,
        permission_key=authorization.permission_key,
        resource_type="automation_rule",
        resource_id=str(rule.id),
        idempotency_key=f"automation-action:{rule.id}:{deal.id}:{index}:decision",
        metadata={
            "reason_code": authorization.reason_code,
            "rule_id": str(rule.id),
            "deal_id": str(deal.id),
            "action_type": action_type,
            "action_index": index,
            "activator_user_id": str(authorization.activator_user_id) if authorization.activator_user_id else None,
            "owner_user_id": str(authorization.owner_user_id) if authorization.owner_user_id else None,
        },
    )


def audit_action_result(
    db: Session,
    *,
    requested: AuditEvent,
    initiator_user_id: UUID,
    rule: AutomationRule,
    deal: Deal,
    index: int,
    action_type: str | None,
    result_status: str,
) -> None:
    """Record the outcome in the business transaction. It rolls back with the work it describes."""
    db.add(
        AuditEvent(
            user_id=initiator_user_id,
            organization_id=rule.organization_id,
            event_type=AUTOMATION_AUTHORITY_EVENT_TYPE,
            action="automation.action.result",
            decision="allowed",
            outcome=OUTCOME_COMPLETED,
            causation_id=str(requested.id),
            permission_key=ACTION_PERMISSIONS.get(action_type or ""),
            resource_type="automation_rule",
            resource_id=str(rule.id),
            event_metadata=json.dumps(
                {
                    "rule_id": str(rule.id),
                    "deal_id": str(deal.id),
                    "action_type": action_type,
                    "action_index": index,
                    "execution_status": result_status,
                },
                sort_keys=True,
            ),
        )
    )
    db.flush()

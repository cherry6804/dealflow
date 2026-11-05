"""Invocation of approved AI tools (DFR1-018).

Every call is checked on the server, in this order, and each refusal stops the call before the tool runs:

1. The tool is registered. An unknown name and a name the caller may not know are answered the same way.
2. The arguments match the schema (strict types, no unknown keys).
3. The initiating user holds the tool's permission in this organization (membership and role, checked in the database).
4. The shared execution gate allows the tool's AI capability (entitlement, switches, provider readiness, actor, resource,
   consent, rate, budget). A tool call is an AI execution, so the gate applies to it in full.
5. The handler runs in a savepoint with a statement timeout. A timeout or database error rolls back only the tool's work.

Each call writes a requested audit record before it runs, and a completed or denied record after it. Records hold the tool
key, the argument names and the outcome. They never hold argument values or results.

Retries: none. A read-only tool is cheap to repeat, and an automatic retry would write duplicate audit records. Idempotency:
every tool in this release is read-only, so repeating a call changes nothing. A write tool needs its own design.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai_tools.definitions import MAX_RESULT_CHARACTERS, ToolDefinition
from app.ai_tools.registry import DEFAULT_REGISTRY, ToolRegistry
from app.ai_tools.validation import (
    InvalidArgumentsError,
    OutputContractError,
    validate_arguments,
    validate_output,
)
from app.audit.attribution import (
    register_system_actor,
    system_attribution,
    user_attribution,
)
from app.audit.independent import (
    OUTCOME_COMPLETED,
    OUTCOME_DENIED,
    OUTCOME_REQUESTED,
    persist_independent_audit_event,
)
from app.auth.dependencies import CurrentUserContext
from app.db.models.audit_event import AuditEvent
from app.db.models.membership import Membership
from app.governance.execution_gate import (
    ExecutionRequest,
    actor_permission_granted,
    evaluate_execution,
    settle_ticket,
)

logger = logging.getLogger("dealflow.ai_tools")

TOOL_AUDIT_EVENT = "ai_tool"
TOOL_INVOKE_ACTION = "ai_tool.invoke"
POSTGRES_QUERY_CANCELED = "57014"
AI_TOOL_SYSTEM_ACTOR = register_system_actor("ai_tools")

REASON_OK = "ok"
REASON_NOT_REGISTERED = "tool_not_registered"
REASON_INVALID_ARGUMENTS = "invalid_arguments"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_TIMEOUT = "tool_timeout"
REASON_FAILED = "tool_failed"
REASON_RESULT_TOO_LARGE = "result_too_large"
REASON_TOOL_UNAVAILABLE = "tool_unavailable"
REASON_UNSUPPORTED_VERSION = "unsupported_tool_version"
REASON_OUTPUT_INVALID = "output_contract_violation"


class ToolExecutionError(RuntimeError):
    """A handler reports a controlled failure. Its message is not returned to the caller."""


@dataclass(frozen=True)
class ToolResult:
    outcome: str
    reason_code: str
    tool_key: str
    data: dict[str, Any] | None = field(default=None)

    @property
    def succeeded(self) -> bool:
        return self.outcome == "succeeded"


def _refused(tool_key: str, reason: str) -> ToolResult:
    return ToolResult(outcome="denied", reason_code=reason, tool_key=tool_key)


def invoke_tool(
    db: Session,
    *,
    organization_id: UUID,
    tool_key: str,
    arguments: dict[str, object],
    user_context: CurrentUserContext,
    registry: ToolRegistry = DEFAULT_REGISTRY,
    tool_version: int | None = None,
    agent_execution_id: UUID | None = None,
) -> ToolResult:
    """Run one approved tool for one user in one organization. The caller commits or rolls back the session.

    ``tool_version`` pins the contract a caller was built against; None means the current version. ``agent_execution_id``
    links the call to the agent run that asked for it, so the audit trail can follow the call back to that run.
    """
    definition = registry.get(tool_key)
    if definition is None:
        return _refused(tool_key, REASON_NOT_REGISTERED)
    if not definition.available:
        return _refused(tool_key, REASON_TOOL_UNAVAILABLE)
    if tool_version is not None and tool_version != definition.version:
        return _refused(tool_key, REASON_UNSUPPORTED_VERSION)

    try:
        typed = validate_arguments(definition, arguments)
    except InvalidArgumentsError:
        return _refused(tool_key, REASON_INVALID_ARGUMENTS)

    user_id = user_context.user.id
    if not actor_permission_granted(
        db,
        organization_id=organization_id,
        user_id=user_id,
        permission_key=definition.required_permission,
    ):
        _record_denial(
            db,
            organization_id=organization_id,
            user_id=user_id,
            definition=definition,
            typed=typed,
            agent_execution_id=agent_execution_id,
        )
        return _refused(tool_key, REASON_PERMISSION_DENIED)

    attribution = user_attribution(organization_id=organization_id, actor_user_id=user_id)
    correlation_id = str(uuid.uuid4())
    requested = persist_independent_audit_event(
        db,
        attribution=attribution,
        event_type=TOOL_AUDIT_EVENT,
        action=TOOL_INVOKE_ACTION,
        decision="allowed",
        outcome=OUTCOME_REQUESTED,
        permission_key=definition.required_permission,
        resource_type="ai_tool",
        resource_id=tool_key,
        correlation_id=correlation_id,
        metadata=_metadata(definition, typed, agent_execution_id=agent_execution_id),
    )

    decision = evaluate_execution(
        db,
        ExecutionRequest(
            organization_id=organization_id,
            capability_key=definition.capability_key,
            user_context=user_context,
            resource_id=f"tool:{tool_key}",
            correlation_id=correlation_id,
        ),
    )
    if not decision.allowed or decision.ticket is None:
        _complete(db, organization_id, user_id, requested, definition, "denied", decision.reason_code, agent_execution_id=agent_execution_id)
        return _refused(tool_key, decision.reason_code)
    ticket = decision.ticket

    try:
        with db.begin_nested():
            db.execute(text(f"SET LOCAL statement_timeout = {int(definition.timeout_ms)}"))
            data = definition.handler(db, organization_id, typed)
    except SQLAlchemyError as exc:
        settle_ticket(db, ticket, actual={})
        reason = REASON_TIMEOUT if getattr(exc.orig, "sqlstate", None) == POSTGRES_QUERY_CANCELED else REASON_FAILED
        logger.error("AI tool database work failed", extra={"tool": tool_key, "error_type": type(exc).__name__})
        _complete(db, organization_id, user_id, requested, definition, "failed", reason, agent_execution_id=agent_execution_id)
        return ToolResult(outcome="failed", reason_code=reason, tool_key=tool_key)
    except ToolExecutionError:
        settle_ticket(db, ticket, actual={})
        _complete(db, organization_id, user_id, requested, definition, "failed", REASON_FAILED, agent_execution_id=agent_execution_id)
        return ToolResult(outcome="failed", reason_code=REASON_FAILED, tool_key=tool_key)

    settle_ticket(db, ticket, actual={})
    try:
        checked = validate_output(definition, data)
    except OutputContractError:
        logger.error("AI tool result broke its output contract", extra={"tool": tool_key})
        _complete(db, organization_id, user_id, requested, definition, "failed", REASON_OUTPUT_INVALID, agent_execution_id=agent_execution_id)
        return ToolResult(outcome="failed", reason_code=REASON_OUTPUT_INVALID, tool_key=tool_key)
    serialized = json.dumps(checked, sort_keys=True)
    if len(serialized) > MAX_RESULT_CHARACTERS:
        _complete(db, organization_id, user_id, requested, definition, "failed", REASON_RESULT_TOO_LARGE, agent_execution_id=agent_execution_id)
        return ToolResult(outcome="failed", reason_code=REASON_RESULT_TOO_LARGE, tool_key=tool_key)

    _complete(db, organization_id, user_id, requested, definition, "succeeded", REASON_OK, agent_execution_id=agent_execution_id)
    return ToolResult(outcome="succeeded", reason_code=REASON_OK, tool_key=tool_key, data=json.loads(serialized))


def _is_active_member(db: Session, *, organization_id: UUID, user_id: UUID) -> bool:
    return (
        db.scalar(
            select(Membership.id).where(
                Membership.organization_id == organization_id,
                Membership.user_id == user_id,
                Membership.is_active.is_(True),
            )
        )
        is not None
    )


def _record_denial(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    definition: ToolDefinition,
    typed: dict[str, Any],
    agent_execution_id: UUID | None,
) -> None:
    metadata = _metadata(definition, typed, reason=REASON_PERMISSION_DENIED, agent_execution_id=agent_execution_id)
    if _is_active_member(db, organization_id=organization_id, user_id=user_id):
        attribution = user_attribution(organization_id=organization_id, actor_user_id=user_id)
    else:
        # The user is not an active member of this organization. Record the attempt under the system actor, with the
        # attempted user identifier, so the cross-tenant attempt is visible rather than silently dropped.
        attribution = system_attribution(organization_id=organization_id, capability=AI_TOOL_SYSTEM_ACTOR)
        metadata["attempted_user_id"] = str(user_id)
    persist_independent_audit_event(
        db,
        attribution=attribution,
        event_type=TOOL_AUDIT_EVENT,
        action=TOOL_INVOKE_ACTION,
        decision="denied",
        outcome=OUTCOME_DENIED,
        permission_key=definition.required_permission,
        resource_type="ai_tool",
        resource_id=definition.key,
        metadata=metadata,
    )


def _metadata(
    definition: ToolDefinition,
    typed: dict[str, Any],
    *,
    reason: str | None = None,
    agent_execution_id: UUID | None = None,
) -> dict[str, object]:
    # Argument names only. Values are personal and operational data, and they stay out of the audit trail.
    metadata: dict[str, object] = {
        "tool": definition.key,
        "tool_version": definition.version,
        "argument_names": sorted(typed) if typed else [],
    }
    if agent_execution_id is not None:
        metadata["agent_execution_id"] = str(agent_execution_id)
    if reason is not None:
        metadata["reason"] = reason
    return metadata


def _complete(
    db: Session,
    organization_id: UUID,
    user_id: UUID,
    requested: AuditEvent,
    definition: ToolDefinition,
    outcome: str,
    reason: str,
    *,
    agent_execution_id: UUID | None = None,
) -> None:
    """The completed record follows the requested record in the caller's transaction (WP3 pattern)."""
    db.add(
        AuditEvent(
            user_id=user_id,
            organization_id=organization_id,
            event_type=TOOL_AUDIT_EVENT,
            action=TOOL_INVOKE_ACTION,
            decision="allowed" if outcome == "succeeded" else "denied",
            outcome=OUTCOME_COMPLETED,
            causation_id=str(requested.id),
            correlation_id=requested.correlation_id,
            permission_key=definition.required_permission,
            resource_type="ai_tool",
            resource_id=definition.key,
            event_metadata=json.dumps(
                {
                    "tool": definition.key,
                    "tool_version": definition.version,
                    "outcome": outcome,
                    "reason": reason,
                    "agent_execution_id": None if agent_execution_id is None else str(agent_execution_id),
                },
                sort_keys=True,
            ),
        )
    )
    db.flush()

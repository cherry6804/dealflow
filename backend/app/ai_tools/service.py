"""Invocation of approved AI tools (DFR1-018).

Every call is checked on the server, in this order, and each refusal stops the call before the tool runs or reads data:

1. The tool is registered and available, and the caller's pinned version (if any) is the current one. An unknown name, an
   unavailable tool and a name the caller may not know are answered the same way, except for the reason code.
2. The arguments match the schema (strict types, no unknown keys). An organization or user identifier supplied as an argument
   is an unknown argument, so a model cannot choose the tenant or the actor.
3. The initiating user is active and holds the tool's permission in this organization (membership and role, checked in the
   database). A user outside the organization is refused and the attempt is audited under the system actor.
4. The shared execution gate allows the tool's AI capability (entitlement, switches, provider readiness, actor, resource,
   consent, rate, budget). A tool call is an AI execution, so the gate applies to it in full.
5. The handler runs in a savepoint with a statement timeout. A timeout or database error rolls back only the tool's work.
6. The handler's result is checked against the tool's exact output contract before anything is returned. A result that does
   not match is refused, never returned in part.

Attribution. Each accepted call writes a requested record before it runs and a completed record after it. A refused call writes
a denied record. Every record holds the initiating user, the organization, the tool key and version, the operation, the target
record identifier, the status, the correlation identifier and, when an agent run asked for the call, the agent and agent
execution identifiers and the idempotency key. Records hold argument names and identifiers only, never argument values or
results.

Retries. Nothing retries a tool call. A read-only call may be repeated safely. A repeated agent step reuses the same
idempotency key, so its records can be linked, but each attempt is audited separately and runs again.
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
MAX_IDEMPOTENCY_KEY = 200

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
class AgentInvocation:
    """The server-side context of an agent run that asks for a tool. The agent runtime sets it; a model never does."""

    agent_id: UUID
    agent_execution_id: UUID
    correlation_id: str


@dataclass(frozen=True)
class ToolResult:
    outcome: str
    reason_code: str
    tool_key: str
    data: dict[str, Any] | None = field(default=None)

    @property
    def succeeded(self) -> bool:
        return self.outcome == "succeeded"


@dataclass(frozen=True)
class _Call:
    """Everything the audit trail needs for one call. Built only after the arguments have been validated."""

    organization_id: UUID
    user_id: UUID
    definition: ToolDefinition
    arguments: dict[str, Any]
    correlation_id: str
    idempotency_key: str | None
    agent: AgentInvocation | None

    def metadata(self, **extra: object) -> dict[str, object]:
        definition = self.definition
        metadata: dict[str, object] = {
            "tool": definition.key,
            "tool_version": definition.version,
            "operation": "read" if definition.read_only else "write",
            "initiated_by_user_id": str(self.user_id),
            "argument_names": sorted(self.arguments),
            "correlation_id": self.correlation_id,
        }
        if definition.target_parameter is not None and definition.target_parameter in self.arguments:
            metadata["target_type"] = definition.target_type
            metadata["target_id"] = str(self.arguments[definition.target_parameter])
        if self.idempotency_key is not None:
            metadata["idempotency_key"] = self.idempotency_key
        if self.agent is not None:
            metadata["agent_id"] = str(self.agent.agent_id)
            metadata["agent_execution_id"] = str(self.agent.agent_execution_id)
        metadata.update(extra)
        return metadata


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
    agent: AgentInvocation | None = None,
    idempotency_key: str | None = None,
) -> ToolResult:
    """Run one approved tool for one user in one organization. The caller commits or rolls back the session.

    ``organization_id`` and ``user_context`` come from the server: the verified tenant and the authenticated initiating user,
    which for an agent run is the user who started it. ``tool_version`` pins the contract a caller was built against. ``agent``
    and ``idempotency_key`` are set by the agent runtime and are recorded in the audit trail.
    """
    definition = registry.get(tool_key)
    if definition is None:
        return _refused(tool_key, REASON_NOT_REGISTERED)
    if not definition.available:
        return _refused(tool_key, REASON_TOOL_UNAVAILABLE)
    if tool_version is not None and tool_version != definition.version:
        return _refused(tool_key, REASON_UNSUPPORTED_VERSION)
    if idempotency_key is not None and not 1 <= len(idempotency_key) <= MAX_IDEMPOTENCY_KEY:
        return _refused(tool_key, REASON_INVALID_ARGUMENTS)

    try:
        typed = validate_arguments(definition, arguments)
    except InvalidArgumentsError:
        return _refused(tool_key, REASON_INVALID_ARGUMENTS)

    call = _Call(
        organization_id=organization_id,
        user_id=user_context.user.id,
        definition=definition,
        arguments=typed,
        correlation_id=agent.correlation_id if agent is not None else str(uuid.uuid4()),
        idempotency_key=idempotency_key,
        agent=agent,
    )
    if not _may_invoke(db, call, user_context):
        _record_denial(db, call)
        return _refused(tool_key, REASON_PERMISSION_DENIED)

    requested = persist_independent_audit_event(
        db,
        attribution=user_attribution(organization_id=organization_id, actor_user_id=call.user_id),
        event_type=TOOL_AUDIT_EVENT,
        action=TOOL_INVOKE_ACTION,
        decision="allowed",
        outcome=OUTCOME_REQUESTED,
        permission_key=definition.required_permission,
        resource_type="ai_tool",
        resource_id=tool_key,
        correlation_id=call.correlation_id,
        metadata=call.metadata(),
    )

    decision = evaluate_execution(
        db,
        ExecutionRequest(
            organization_id=organization_id,
            capability_key=definition.capability_key,
            user_context=user_context,
            resource_id=f"tool:{tool_key}",
            correlation_id=call.correlation_id,
        ),
    )
    if not decision.allowed or decision.ticket is None:
        _complete(db, call, requested, outcome="denied", reason=decision.reason_code)
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
        _complete(db, call, requested, outcome="failed", reason=reason)
        return ToolResult(outcome="failed", reason_code=reason, tool_key=tool_key)
    except ToolExecutionError:
        settle_ticket(db, ticket, actual={})
        _complete(db, call, requested, outcome="failed", reason=REASON_FAILED)
        return ToolResult(outcome="failed", reason_code=REASON_FAILED, tool_key=tool_key)

    settle_ticket(db, ticket, actual={})
    try:
        checked = validate_output(definition, data)
    except OutputContractError:
        logger.error("AI tool result broke its output contract", extra={"tool": tool_key})
        _complete(db, call, requested, outcome="failed", reason=REASON_OUTPUT_INVALID)
        return ToolResult(outcome="failed", reason_code=REASON_OUTPUT_INVALID, tool_key=tool_key)
    serialized = json.dumps(checked, sort_keys=True)
    if len(serialized) > MAX_RESULT_CHARACTERS:
        _complete(db, call, requested, outcome="failed", reason=REASON_RESULT_TOO_LARGE)
        return ToolResult(outcome="failed", reason_code=REASON_RESULT_TOO_LARGE, tool_key=tool_key)

    _complete(db, call, requested, outcome="succeeded", reason=REASON_OK)
    return ToolResult(outcome="succeeded", reason_code=REASON_OK, tool_key=tool_key, data=json.loads(serialized))


def _may_invoke(db: Session, call: _Call, user_context: CurrentUserContext) -> bool:
    """The initiating user must be active and hold the permission through an active membership in this organization."""
    if not user_context.user.is_active:
        return False
    return actor_permission_granted(
        db,
        organization_id=call.organization_id,
        user_id=call.user_id,
        permission_key=call.definition.required_permission,
    )


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


def _record_denial(db: Session, call: _Call) -> None:
    metadata = call.metadata(reason=REASON_PERMISSION_DENIED)
    if _is_active_member(db, organization_id=call.organization_id, user_id=call.user_id):
        attribution = user_attribution(organization_id=call.organization_id, actor_user_id=call.user_id)
    else:
        # The user is not an active member of this organization. Record the attempt under the system actor, with the
        # attempted user identifier, so the cross-tenant attempt is visible rather than silently dropped.
        attribution = system_attribution(organization_id=call.organization_id, capability=AI_TOOL_SYSTEM_ACTOR)
        metadata["attempted_user_id"] = str(call.user_id)
    persist_independent_audit_event(
        db,
        attribution=attribution,
        event_type=TOOL_AUDIT_EVENT,
        action=TOOL_INVOKE_ACTION,
        decision="denied",
        outcome=OUTCOME_DENIED,
        permission_key=call.definition.required_permission,
        resource_type="ai_tool",
        resource_id=call.definition.key,
        correlation_id=call.correlation_id,
        metadata=metadata,
    )


def _complete(db: Session, call: _Call, requested: AuditEvent, *, outcome: str, reason: str) -> None:
    """The completed record follows the requested record in the caller's transaction (WP3 pattern).

    The gate allowed a call that reached the handler, so a ``failed`` call is recorded as allowed, with its failure status.
    Only a call the gate refused is recorded as denied.
    """
    definition = call.definition
    db.add(
        AuditEvent(
            user_id=call.user_id,
            organization_id=call.organization_id,
            event_type=TOOL_AUDIT_EVENT,
            action=TOOL_INVOKE_ACTION,
            decision="denied" if outcome == "denied" else "allowed",
            outcome=OUTCOME_COMPLETED,
            causation_id=str(requested.id),
            correlation_id=call.correlation_id,
            permission_key=definition.required_permission,
            resource_type="ai_tool",
            resource_id=definition.key,
            event_metadata=json.dumps(call.metadata(status=outcome, reason=reason), sort_keys=True),
        )
    )
    db.flush()

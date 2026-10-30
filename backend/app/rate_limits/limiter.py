"""Atomic fixed-window rate limiting per organization and per actor (E13 hardening).

Each consumption increments one counter row per scope with a single INSERT ... ON CONFLICT DO
UPDATE. PostgreSQL locks the row for the update, so concurrent requests serialize on it and the
count stays exact. A request that exceeds a limit is denied, and its attempt still counts, so
repeated attempts cannot slip past the window.

The limiter records no usage and no cost. It never writes to the usage ledger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.execution_rate_limit_window import ExecutionRateLimitWindow
from app.rate_limits.policy import RETENTION, RateLimitRule, get_rule

logger = logging.getLogger(__name__)

SCOPE_ORGANIZATION = "organization"
SCOPE_ACTOR = "actor"

REASON_ALLOWED = "allowed"
REASON_RATE_LIMITED = "rate_limited"
REASON_UNAVAILABLE = "rate_limit_unavailable"


class RateLimitUnavailableError(RuntimeError):
    """The rate-limit store cannot be used. Callers must fail closed."""


@dataclass(frozen=True)
class RateLimitDecision:
    """Structured result. ``retry_after_seconds`` is 0 when the execution is allowed."""

    allowed: bool
    reason_code: str
    execution_type: str
    scope: str | None
    limit: int | None
    remaining: int | None
    retry_after_seconds: int


def _increment(
    db: Session,
    *,
    organization_id: UUID,
    scope_type: str,
    scope_id: str,
    rule: RateLimitRule,
    now: datetime,
) -> tuple[int, datetime]:
    """Atomically add one attempt to a scope's current window and return (count, window start)."""
    if db.get_bind().dialect.name != "postgresql":
        raise RateLimitUnavailableError("Rate limiting requires PostgreSQL.")

    table = ExecutionRateLimitWindow.__table__
    expired_window = table.c.window_started_at <= now - rule.window
    statement = pg_insert(table).values(
        id=uuid4(),
        organization_id=organization_id,
        scope_type=scope_type,
        scope_id=scope_id,
        execution_type=rule.execution_type,
        window_started_at=now,
        count=1,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[
            table.c.organization_id,
            table.c.scope_type,
            table.c.scope_id,
            table.c.execution_type,
        ],
        set_={
            "window_started_at": case((expired_window, now), else_=table.c.window_started_at),
            "count": case((expired_window, 1), else_=table.c.count + 1),
        },
    ).returning(table.c.count, table.c.window_started_at)

    count, window_started_at = db.execute(statement).one()
    if window_started_at.tzinfo is None:
        window_started_at = window_started_at.replace(tzinfo=UTC)
    return int(count), window_started_at


def consume(
    db: Session,
    *,
    organization_id: UUID,
    execution_type: str,
    actor_user_id: UUID | None = None,
    now: datetime | None = None,
) -> RateLimitDecision:
    """Consume one attempt for the organization and, when known, the acting user.

    The caller owns the transaction. The function does not commit. Both scopes are updated even
    when one is exceeded, so the two counters stay consistent with the attempts made.

    Window times come from the database clock (``now()``), not from the application server. Every
    backend instance therefore agrees on the window, whatever its own clock says. A caller may
    inject ``now`` for deterministic tests only.
    """
    rule = get_rule(execution_type)
    moment = now if now is not None else _database_now(db)

    _prune_expired(db, organization_id=organization_id, moment=moment)

    scopes: list[tuple[str, str, int]] = [
        (SCOPE_ORGANIZATION, str(organization_id), rule.organization_limit),
    ]
    if actor_user_id is not None:
        scopes.append((SCOPE_ACTOR, str(actor_user_id), rule.actor_limit))

    results: list[tuple[str, int, int, datetime]] = []
    for scope_type, scope_id, limit in scopes:
        count, window_started_at = _increment(
            db,
            organization_id=organization_id,
            scope_type=scope_type,
            scope_id=scope_id,
            rule=rule,
            now=moment,
        )
        results.append((scope_type, limit, count, window_started_at))

    for scope_type, limit, count, window_started_at in results:
        if count > limit:
            retry_after = max(1, int((window_started_at + rule.window - moment).total_seconds()))
            return RateLimitDecision(
                allowed=False,
                reason_code=REASON_RATE_LIMITED,
                execution_type=execution_type,
                scope=scope_type,
                limit=limit,
                remaining=0,
                retry_after_seconds=retry_after,
            )

    remaining = min(limit - count for _, limit, count, _ in results)
    return RateLimitDecision(
        allowed=True,
        reason_code=REASON_ALLOWED,
        execution_type=execution_type,
        scope=None,
        limit=None,
        remaining=remaining,
        retry_after_seconds=0,
    )


def consume_or_deny(
    db: Session,
    *,
    organization_id: UUID,
    execution_type: str,
    actor_user_id: UUID | None = None,
    now: datetime | None = None,
) -> RateLimitDecision:
    """Consume an attempt, or deny when the store or configuration fails.

    The attempt runs in a savepoint, so a failure rolls back only the limiter's own write and
    leaves the surrounding transaction usable. Denial on failure keeps the protected execution off.
    """
    try:
        with db.begin_nested():
            return consume(
                db,
                organization_id=organization_id,
                execution_type=execution_type,
                actor_user_id=actor_user_id,
                now=now,
            )
    except (SQLAlchemyError, RateLimitUnavailableError, KeyError) as exc:
        # The protected execution stays off. The log line is the operational signal. It records
        # the exception class only, never the SQL text or parameters.
        logger.error(
            "rate_limit_unavailable execution_type=%s organization_id=%s error_type=%s",
            execution_type,
            organization_id,
            type(exc).__name__,
        )
        return RateLimitDecision(
            allowed=False,
            reason_code=REASON_UNAVAILABLE,
            execution_type=execution_type,
            scope=None,
            limit=None,
            remaining=0,
            retry_after_seconds=0,
        )


def _database_now(db: Session) -> datetime:
    """Return the database server's current time as an aware datetime."""
    moment = db.scalar(select(func.now()))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def _prune_expired(db: Session, *, organization_id: UUID, moment: datetime) -> None:
    """Remove this organization's counters that are past the retention period."""
    db.execute(
        delete(ExecutionRateLimitWindow).where(
            ExecutionRateLimitWindow.organization_id == organization_id,
            ExecutionRateLimitWindow.window_started_at < moment - RETENTION,
        )
    )

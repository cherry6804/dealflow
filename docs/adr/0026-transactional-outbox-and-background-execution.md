# ADR-0026: Transactional Outbox and Background Execution

- **Status:** Proposed
- **Date:** 2026-10-30
- **Decision Owners:** DealFlow Engineering (approval pending)
- **Jira:** DFR1-013

## Context

Release 1 depends on reliable side effects: webhook processing, message delivery, workflow steps and agent actions. A business change and the event describing it must not diverge. The codebase already has an email outbox for encrypted transactional mail (`email_outbox_messages`), but it is specific to email and has no general dispatch contract, dead-letter state or handler registry.

## Decision

Dealsflo has a general transactional outbox in `backend/app/outbox/`, backed by the `outbox_events` table (migration `e5a7c1d9b2f0`).

- **Enqueue in the same transaction.** `enqueue_event(db, ...)` adds the row to the caller's session. The event exists if and only if the business change commits.
- **Idempotency.** `idempotency_key` is unique across the table. Re-enqueueing the same event returns the stored row. Reusing a key for another tenant, event type or aggregate raises `OutboxConflictError`.
- **Leased claims.** Workers claim due rows with `FOR UPDATE SKIP LOCKED`. A lease (`outbox_lease_seconds`) lets another worker recover a crashed claim.
- **Handler isolation.** Each handler runs inside a savepoint. If it raises, its writes roll back and the event is recorded as failed.
- **Bounded retries.** Failures back off exponentially from `outbox_base_backoff_seconds`, capped at `outbox_max_backoff_seconds`. After `max_attempts` the event becomes `dead_letter`.
- **Operator inspection.** `python -m app.outbox.reporting` lists events with sanitized errors and never prints payloads.
- **Worker.** `python -m app.outbox.worker --once`, or `--poll-interval N` to run continuously.

Delivery is at-least-once. Handlers must be idempotent and must bound their own I/O with timeouts. In-process timeouts are not enforced; a stalled handler is recovered when its lease expires.

Payloads must be JSON, at most 64 KB, and must not contain secrets.

## Alternatives Considered

- **Publish directly to a broker after commit:** rejected for now. It adds infrastructure and does not close the commit-versus-publish gap without its own outbox.
- **Reuse the email outbox table for all events:** rejected. Its encryption and email-specific fields would leak into unrelated events.
- **Fire events from application code after commit:** rejected. A crash between commit and publish loses the event.

## Consequences

- Producers adopt the outbox by calling `enqueue_event` inside their own transaction. No producers exist yet in E01; the first producers arrive with later epics.
- The email outbox remains separate. Migrating it onto this foundation is a later decision.

## Security Considerations

- Payloads are not logged. Log lines carry only the event id, type and error class.
- Stored errors are truncated to 500 characters and are single-line.
- Handlers receive a session for one event. Tenant isolation inside a handler is the handler's responsibility and must be tested for that handler.

## Operational Considerations

- Run one worker per process with `--poll-interval`. Scale by adding processes; row locks make this safe.
- The reporting command is an operator tool, not an HTTP endpoint.
- Dead letters need an operator decision. An admin API and alerting belong to E13 and E15.

## Compatibility Considerations

Additive table and migration. The downgrade drops the table; this was verified with `alembic downgrade -1` followed by `upgrade head`.

## Related Decisions

ADR-0025 (module boundaries), ADR-0028 (the channel gateway uses this outbox), ADR-0029 (AI execution events use this outbox).

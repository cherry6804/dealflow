# ADR-0026: Transactional Outbox and Background Execution

- **Status:** Accepted
- **Date:** 2026-11-02
- **Decision Owners:** DealFlow Engineering
- **Jira:** DFR1-013

## Context

Release 1 depends on reliable side effects: webhook processing, message delivery, workflow steps and agent actions. A business change and the event describing it must not diverge.

Before WS3 the codebase had a transactional outbox (`outbox_events`) with leases and dead letters, but no deployed worker. Its only consumer was the usage-alert handler, so threshold alerts were not delivered in any environment. The encrypted email outbox (`email_outbox_messages`) ran as a thread inside every API process. Its ownership checks were stronger than the event outbox's, and its retry code was duplicated.

## Decision

Dealsflo has a general transactional outbox in `backend/app/outbox/`, backed by `outbox_events` (migration `e5a7c1d9b2f0`, extended by `a1f7c3e9d2b6`).

- **Enqueue in the same transaction.** `enqueue_event(db, ...)` adds the row to the caller's session. The event exists if and only if the business change commits. A concurrent insert with the same idempotency key returns the stored row rather than failing the caller.
- **Idempotency.** `idempotency_key` is unique across the table. Reusing a key for another tenant, event type or aggregate raises `OutboxConflictError`, which does not say which field differed.
- **Leased, fenced claims.** Workers claim due rows with `FOR UPDATE SKIP LOCKED`, a lease (`outbox_lease_seconds`) and a fresh `claim_token`. Before a handler's first write the worker locks the row while the claim is still its own. Its outcome (delivered, retried, dead-lettered, released) is written only if the same `claim_token` still holds. A worker whose claim was taken over records nothing, and its handler writes are discarded.
- **Handler isolation.** Each handler runs inside a savepoint. If it raises, its writes roll back and the failure is recorded.
- **Retries.** Retryable failures back off exponentially from `outbox_base_backoff_seconds`, capped at `outbox_max_backoff_seconds`, with full jitter between 50% and 100% of the capped delay (`outbox_jitter_enabled`).
- **Permanent errors are not retried (D-4).** A handler that raises `PermanentHandlerError` with a reason code, such as a missing administrator, is dead-lettered at once. So is an event whose type has no handler in the running worker. Each dead letter records `dead_letter_reason`. Events that exhaust `max_attempts` record `max_attempts_exhausted`.
- **Replay (D-6).** `python -m app.outbox.replay` re-queues one dead letter. It requires an operator name on `OUTBOX_OPERATOR_ALLOWLIST`, a tenant match, a written reason, and a handler in the running process. It writes an `outbox_replay_records` row in the same transaction, and a second replay changes nothing. It is not exposed over HTTP.
- **Usage alerts (D-5).** The budget's `last_alert_percent` advances only in the transaction that records a successful alert delivery. A failed or dead-lettered alert therefore stays re-announceable, and a replay re-announces it. Notifications are keyed per recipient, so a replay does not duplicate them.
- **Dedicated worker process (D-1).** `python -m app.outbox.worker --serve` runs the outbox dispatcher and the encrypted email worker as supervised threads in a process separate from the API. The API process runs no background workers.
- **Email moved out of the API (D-3).** The email worker's send, retry and claim logic is unchanged. It runs in the worker process. Deployments must run that process for account email to be sent.
- **Graceful shutdown.** SIGINT or SIGTERM stops new claims. The dispatcher finishes the event it is running and returns unstarted claims to the queue without a failed attempt. The process exits 0 after a clean stop, and 1 after a fatal loop failure or when a loop does not stop within the grace period.
- **Supervision.** A loop that fails `outbox_worker_max_consecutive_errors` cycles in a row stops the process, so an orchestrator can restart it.
- **Health (D-2).** `/livez` and `/readyz` on `outbox_worker_probe_host:outbox_worker_probe_port`. Liveness fails when a loop stops heartbeating or the process has failed. Readiness also checks the database and that handlers are registered. Responses contain status words only.
- **Observability (D-2).** One JSON object per log line, carrying `worker_id`, `outbox_event_id`, `event_type`, `organization_id`, `correlation_id`, `attempt`, `outcome` and dead-letter reason. Payloads, recipients, tokens and exception messages are never logged. No metrics platform or dependency is added.
- **Operator inspection.** `python -m app.outbox.reporting` lists events with reason codes and sanitized errors. It never prints payloads.
- **Retention (D-7).** Delivered rows, dead letters and replay records are kept. No automatic purge runs. Configurable retention is not implemented because no retention policy has been approved.

Delivery is **at-least-once**. Exactly-once is not claimed. A crash after an external side effect but before the fenced outcome write causes that side effect to repeat when the event is re-claimed. Handlers must be idempotent, and any handler that calls an external system must pass an idempotency key to that system.

Payloads must be JSON, at most 64 KB, and must not contain secrets or personal data the consumer does not need.

## Alternatives Considered

- **Publish directly to a broker after commit:** rejected for now. It adds infrastructure and does not close the commit-versus-publish gap without its own outbox.
- **Reuse the email outbox table for all events:** rejected. Its encryption and email-specific fields would leak into unrelated events.
- **Fire events from application code after commit:** rejected. A crash between commit and publish loses the event.
- **Exactly-once processing:** not claimed. It cannot be guaranteed for external side effects without remote idempotency.
- **Keep the email worker in the API process:** rejected (D-3). Each API replica would run its own email loop, and API deploys would interrupt email delivery.
- **Retry "no administrator" alerts until one exists:** rejected (D-4). No retry can succeed until a person corrects the configuration, so the event is dead-lettered and replayed instead.

## Consequences

- Producers adopt the outbox by calling `enqueue_event` inside their own transaction. The usage ledger is the only producer today.
- Operators must run the worker process in every environment that handles events or account email. This is a deployment requirement and is documented in `docs/development/worker-deployment.md`.
- Account email sent by the API in earlier releases stops being sent by the API process. It is sent once the worker process runs. Queued emails are not lost, because they remain in `email_outbox_messages`.
- Rolling deployments must stop workers that predate migration `a1f7c3e9d2b6` before the new workers start. Those workers do not set `claim_token` and cannot pass the fence.
- Changing the retry policy, adding a reason code or changing the operator allowlist format requires an update to this ADR.

## Security Considerations

- Payloads are not logged. Log lines carry identifiers, outcomes and error type names only. A test asserts that payload and exception text are excluded.
- Stored errors are truncated to 500 characters and are single-line.
- Replay is an operator command. Its authorization is an operator name on the allowlist, which is **asserted, not authenticated**. Access to the command therefore depends on who can run it on a host that holds database credentials. Each replay records the asserted name and the reason, so the action is attributable to that name. Real operator authentication is not in place and is a known limitation.
- The probe endpoints bind to localhost by default and expose no tenant data. They are plain HTTP and are not authenticated, so they must stay on a private interface.
- Each handler is responsible for tenant isolation inside its own queries. The budget handler locks the budget by organization, and the notification handler checks membership. Each handler must have a cross-tenant test.
- The worker connects with the same database role as the API. A separate least-privilege role is recommended in the deployment instructions and is not yet provisioned.

## Operational Considerations

- **Responsible operations team: DealFlow Engineering.** No named individual owner, on-call rota, alert channel or support process is configured. These are open items, and they must be recorded before production use.
- **Required before production:** a deployment target for the worker process (container platform or service definition, see the runbook), a database role for the worker, the probe checks wired to the platform's restart policy, alerts on dead-letter count, oldest pending age, heartbeat staleness and lease-lost rate, and a configured `OUTBOX_OPERATOR_ALLOWLIST`. No deployment has been made.
- Scale by adding worker processes. Row locks and fencing make concurrent workers safe, and the concurrency test runs four workers against one database.
- The reporting and replay commands are operator tools. They are not HTTP endpoints.

## Known Limitations

1. **No handler deadline.** Python cannot stop a running handler, so the lease is the only bound. A handler that outlives its lease is not stopped, but its outcome is fenced, so it cannot mark a row delivered after another worker has taken it over. Its side effects can still have run. Database sessions can be bounded with `DATABASE_STATEMENT_TIMEOUT_MS` and `DATABASE_IDLE_TRANSACTION_TIMEOUT_MS`. Both default to off and are recommended for worker deployments.
2. **External side effects are at-least-once.** See the decision above.
3. **Authorization of replay is asserted, not authenticated** (see Security).
4. **Graceful shutdown was verified in-process** through the stop event. On Windows the operating system cannot deliver SIGTERM to a child process, so the OS-level signal path was not exercised in this environment. It must be verified on the deployment platform.
5. **No metrics.** Counters are available only as structured log fields, by decision D-2.
6. **Single-threaded handlers per process.** Concurrency is achieved with more processes, not threads inside one process.
7. **Probe server is plain HTTP** and is intended for an orchestrator on a private interface.
8. **Alert coalescing.** If usage crosses 85 percent before the 70 percent alert is delivered, the 85 percent alert is queued and the 70 percent one is not announced separately. Delivery of 85 percent marks both thresholds as reached.
9. **No retention purge.** Dead letters and delivered rows accumulate until an approved retention policy exists.
10. **Email worker coupling.** Account email now depends on the worker process. Monitoring of queued email age is not yet specified.

## Compatibility Considerations

- Schema change is additive (`a1f7c3e9d2b6`): two nullable columns on `outbox_events` and a new `outbox_replay_records` table. Downgrade drops them. Verified on an empty schema with `upgrade head`, `downgrade -1` and `upgrade head`.
- `python -m app.outbox.worker --once` and `--poll-interval` keep their previous behavior for outbox dispatch. `--serve` is the new deployment entry point.
- The API no longer starts an email thread. Test suites that relied on that thread's side effects were checked and pass unchanged.

## Related Decisions

ADR-0025 (module boundaries), ADR-0028 (the channel gateway uses this outbox), ADR-0029 (AI execution events and usage alerts use this outbox), ADR-0030 (environment and configuration standards; deployment definition is to be decided there).

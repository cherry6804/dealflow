# Background worker: running, configuring and operating

This runbook covers the background worker process introduced in WS3 (ADR-0026). It runs the transactional outbox (usage alerts and any future event consumers) and the encrypted email outbox (account verification, password reset, team invitations).

## Status

**No production deployment exists.** The repository defines no container image, orchestrator manifest or hosting target for this process. This document describes the executable entry point and its configuration so an operator can deploy it. Do not describe the worker as running in any environment until someone has deployed it and recorded the evidence.

Responsible operations team: **DealFlow Engineering**. No named owner, on-call rota, alert channel or support process is configured.

## What runs where

| Process | Command | Runs |
|---|---|---|
| API | `uvicorn app.main:app` | Requests only. Enqueues events and email in the same transaction as the change. Starts no background work. |
| Worker | `python -m app.outbox.worker --serve` | Outbox dispatch loop, email loop, health probes. |

Account email is queued by the API and **sent only by the worker**. If no worker runs, queued emails wait in `email_outbox_messages`. They are not lost.

## Start the worker

From the `backend` directory, with the same code version as the API:

```bash
uv run python -m app.outbox.worker --serve
```

The process logs one JSON object per line to stderr and stops when it receives SIGINT or SIGTERM.

## Required configuration

| Variable | Purpose |
|---|---|
| `APP_ENVIRONMENT` | `production` or the target environment name. |
| `DATABASE_URL` | Connection for the worker. Use a database role that is not a superuser. |
| `EMAIL_OUTBOX_ENCRYPTION_KEY` | Must equal the key the API uses. Queued emails are decrypted with it. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | Email delivery. Keep the password in the platform secret store. |
| `OUTBOX_OPERATOR_ALLOWLIST` | Comma-separated operator names allowed to replay dead letters. Empty refuses every replay. |

## Recommended configuration

| Variable | Default | Recommendation |
|---|---|---|
| `DATABASE_STATEMENT_TIMEOUT_MS` | `0` (off) | `30000`. Stops a stuck statement from holding row locks. |
| `DATABASE_IDLE_TRANSACTION_TIMEOUT_MS` | `0` (off) | `60000`. Ends an open transaction that has stopped making progress. |
| `OUTBOX_LEASE_SECONDS` | `300` | Keep above the longest expected handler run. |
| `OUTBOX_MAX_ATTEMPTS` | `5` | Attempts before a retryable failure is dead-lettered. |
| `OUTBOX_BASE_BACKOFF_SECONDS` / `OUTBOX_MAX_BACKOFF_SECONDS` | `30` / `3600` | Backoff bounds. Jitter is on by default (`OUTBOX_JITTER_ENABLED`). |
| `OUTBOX_POLL_SECONDS` | `5` | Sleep between empty outbox cycles. |
| `EMAIL_OUTBOX_POLL_SECONDS` | `2` | Sleep between empty email cycles. |
| `OUTBOX_WORKER_PROBE_HOST` / `OUTBOX_WORKER_PROBE_PORT` | `127.0.0.1` / `8081` | Bind the probes to a private interface only. |
| `OUTBOX_WORKER_STALE_SECONDS` | `120` | A loop with no heartbeat for this long fails liveness. Keep it several times the poll intervals. |
| `OUTBOX_WORKER_MAX_CONSECUTIVE_ERRORS` | `10` | Repeated loop failures stop the process so the orchestrator restarts it. |
| `OUTBOX_WORKER_SHUTDOWN_GRACE_SECONDS` | `30` | Time allowed for the running event and email to finish after a stop signal. |

## Health and readiness

- `GET /livez` returns 200 while both loops heartbeat and the process has not failed. Use it as the liveness probe.
- `GET /readyz` also checks the database and that event handlers are registered. Use it as the readiness probe.

Responses contain only status words per check. A 503 means the process should be restarted (livez) or not counted as ready (readyz).

## Stopping

Send SIGTERM and wait for the grace period. The worker finishes the event it is running, returns unstarted events to the queue without a failed attempt, lets a send in progress complete, and exits 0. If it has not exited when the platform's kill timeout expires, the platform will force-stop it. Events it had claimed then wait for their lease (`OUTBOX_LEASE_SECONDS`) before another worker takes them.

Exit code 1 means the process failed: a loop failed repeatedly, or a loop did not stop within the grace period.

## Rollout order (migration `a1f7c3e9d2b6`)

1. Stop every worker that predates the migration.
2. Apply the migration: `uv run alembic upgrade head`.
3. Start the new worker processes.

Workers that predate the migration do not set `claim_token`, so the new fence cannot recognise their claims. Running old and new workers at the same time can deliver one event twice.

## Scaling

Run more worker processes to increase throughput. Each process claims its own batch with row locks, and claims are fenced, so processes never handle the same claim at the same time. Start with two replicas for availability and scale from there. The test suite runs four concurrent workers against one database.

## Provider verification

The worker also verifies external provider connections (ADR-0032). Each cycle it queues due re-checks, then runs queued checks under a row lock, so two checks for one connection never overlap. Connections stay `verifying` or `unverified` until a check succeeds, and freshness expiry makes an unchecked connection not ready. Without a running worker, provider connections cannot become ready. Live provider calls are off unless `PROVIDER_LIVE_ADAPTERS_ENABLED` is set, and that flag must never be enabled in CI.

## Logs

Each line is a JSON object with `timestamp`, `level`, `logger`, `message` and, where relevant, `worker_id`, `loop`, `outbox_event_id`, `event_type`, `organization_id`, `correlation_id`, `attempt`, `outcome`, `dead_letter_reason`, `error_type`. Payloads, recipients, tokens and exception messages are never logged. Useful outcomes:

- `delivered`, `retried`, `dead_lettered`, `lease_lost`, `released` (outbox events)
- `loop_error`, `fatal` (supervision)
- `started`, `stopped`, `failed` (process lifecycle)

## Operator tasks

### List failures

```bash
uv run python -m app.outbox.reporting --status dead_letter --limit 50
```

Each line shows the event id, organization, event type, attempts, the dead-letter reason and a sanitized error. Payloads are never printed.

Reason codes:

| Reason | Meaning | Typical fix |
|---|---|---|
| `no_administrator` | No active member holds the budget-management permission. | Assign the permission to an administrator, then replay. |
| `no_recipient_accepts_alerts` | Every administrator has turned notifications off. | Ask an administrator to re-enable them, then replay. |
| `budget_not_found` | The budget row no longer exists. | Usually leave as is. Replay only if the budget was restored. |
| `invalid_alert_payload` | The event payload is malformed. | Investigate the producer. Do not replay until it is fixed. |
| `no_handler_registered` | The worker build lacks the handler for this event type. | Deploy a worker build with the handler, then replay. |
| `max_attempts_exhausted` | Retryable failures used every attempt. | Investigate the cause in the logs, fix it, then replay. |
| `permanent_error` | A handler reported a permanent problem. | Read the sanitized error and the handler's documentation. |

### Replay one dead letter

Always start with a dry run. It prints what would change and changes nothing.

```bash
uv run python -m app.outbox.replay --event-id EVENT_ID --organization-id ORG_ID \
  --operator YOUR_OPERATOR_NAME --reason "Administrator assigned; re-announce alert"
```

When the dry run is correct, repeat the command with `--confirm`:

```bash
uv run python -m app.outbox.replay --event-id EVENT_ID --organization-id ORG_ID \
  --operator YOUR_OPERATOR_NAME --reason "Administrator assigned; re-announce alert" --confirm
```

The replay:

- refuses an operator name that is not in `OUTBOX_OPERATOR_ALLOWLIST` (exit code 3);
- refuses an event that belongs to another organization, with the same message as an unknown event (exit code 2);
- changes nothing if the event is not dead-lettered, so running it twice is safe;
- refuses if this worker build has no handler for the event type (exit code 2);
- requires a reason of at least 10 characters;
- writes a row to `outbox_replay_records` in the same transaction, recording the operator name, the reason, and the previous status, attempts, reason and error.

After a replay, the next dispatch cycle runs the handler. Check the log for `delivered` or a new dead letter.

The operator name is asserted, not authenticated. Limit who can run this command to the people who hold database access.

### Retention

Nothing is purged automatically. Delivered rows, dead letters and replay records are kept until a retention policy is approved. Until then, do not delete rows by hand unless the data owner has approved it.

## Local verification

```bash
cd backend
APP_ENVIRONMENT=development uv run python -m app.outbox.worker --serve &
curl -s http://127.0.0.1:8081/livez
curl -s http://127.0.0.1:8081/readyz
```

Stop the process with Ctrl+C or SIGTERM. On Windows the operating system cannot send SIGTERM to a child process, so a forced stop is the only option there. Verify graceful shutdown on a Linux host.

## Before production (open items)

These are required before anyone can describe the worker as deployed:

1. A deployment target and definition for the worker process, decided through ADR-0030.
2. A least-privilege database role for the worker.
3. Restart policy wired to the liveness and readiness probes.
4. Alerts on dead-letter count, oldest pending outbox event, oldest queued email, heartbeat staleness and lease-lost rate. Alert destinations are not configured.
5. A named operator list in `OUTBOX_OPERATOR_ALLOWLIST`, approved by DealFlow Engineering.
6. Evidence that graceful shutdown works on the deployment platform.
7. A retention policy for delivered rows and dead letters.

Known limitations are listed in ADR-0026.

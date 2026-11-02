# AI usage reservations: lifecycle, expiry and concurrency (WS6 WP1)

Status: implemented in WS6 WP1. Owner: DealFlow backend. Story: DFR1-017 (prerequisite hardening).

This document describes the existing AI usage ledger in `backend/app/governance/usage_ledger.py`
and its table `ai_usage_events`. It is not a second ledger. Budgets live in
`organization_usage_budgets`, as before.

## 1. Purpose

Billable AI work must reserve quantity before it runs, then settle the actual quantity, or release
the reservation if the work fails. Before WP1 an abandoned reservation held budget forever, a
repeated request with a changed payload was silently accepted, and usage could be stored without a
budget. WP1 closes those gaps. No AI execution path calls the ledger yet.

## 2. States

| From | To | Operation | Notes |
|---|---|---|---|
| (none) | RESERVED | `reserve` | Sets `reservation_expires_at = now + RESERVATION_TTL`. Adds `reserved_quantity` to the budget. |
| (none) | RECORDED | `record` | Usage reported after the fact. Adds to `consumed_quantity`. Requires a budget. |
| RESERVED | RECORDED | `settle` | Refused after expiry. Moves reserved to consumed. |
| RESERVED | RELEASED (`released`) | `release` | Work failed or was cancelled. Allowed even after expiry while the reaper has not run. |
| RESERVED | RELEASED (`expired`) | `expire_stale_reservations` | Reaper only. Releases the reserved quantity. |
| RECORDED | REVERSED | `reverse` | Returns consumed quantity. The row is kept. |

No status was added. Expiry is represented as `RELEASED` with `released_reason = 'expired'`, so the
existing status model is unchanged. Terminal states are RECORDED (via settle), RELEASED, and
REVERSED. Each may be entered once. Repeating the same operation is a no-op. Repeating a different
operation on a terminal state is refused.

## 3. Reservation TTL

`RESERVATION_TTL = 15 minutes` (`usage_ledger.py`).

Rationale: the ledger has no executing provider calls yet, so there is no measured duration. 15
minutes is a conservative bound on how long a single billable step should hold budget. It is a
technical safety setting, not a commercial limit or customer commitment.

Assumption to confirm before any real provider call: a single billable operation must settle within
15 minutes of reservation. Longer work must be split into reservations that each fit the window, or
the TTL must be raised by a reviewed change. Raising it extends how long an abandoned reservation
can hold budget, so the change must be reviewed. The reaper cadence (below) bounds the cost of
abandonment.

## 4. Reaper

`expire_stale_reservations(db, now=None, batch_size=100)` is called once per worker cycle from
`app/outbox/runtime.py` (`_outbox_cycle`), in its own session and transaction, before outbox
dispatch.

- Processes at most `batch_size` candidates per call. Remaining candidates are handled in later cycles.
- Selects only RESERVED rows whose `reservation_expires_at <= now`.
- Locks the budget first, then the entry with `SKIP LOCKED`. If the entry is locked elsewhere, it is
  counted as skipped and left for a later pass.
- Re-checks status and expiry after locking, so a settled, released or still-open entry is never
  touched.
- If the budget for the entry is missing, the entry is skipped and logged. It is never released
  silently.

Reaper frequency is the worker's existing poll cadence. No new timer or scheduler was introduced.

## 5. Locking order

Every operation that changes state locks in the same order:

1. The budget row (`organization_usage_budgets`) with `SELECT ... FOR UPDATE`.
2. The entry row (`ai_usage_events`) with `FOR UPDATE`, or `FOR UPDATE SKIP LOCKED` in the reaper.

Every lock read uses `populate_existing`, so state read after a lock is the latest committed state,
not a value cached earlier in the same session. A decision is always made after both locks are held
and the entry is re-read.

Because the budget is locked first everywhere, two operations on the same budget are serialized,
and budget counters remain exact. The cost is that operations on one budget period are serialized.
This is acceptable at the current volume, which is zero, and it is the simplest correct choice.

## 6. Idempotency

- Uniqueness: `(organization_id, idempotency_key)` (`uq_ai_usage_events_org_idempotency`).
- Fingerprint: `request_fingerprint` is the SHA-256 of the operation kind (`reserve` or `record`)
  and the request fields (unit, quantity, occurred_at, provider, model, task_type, user, agent,
  workflow, execution, correlation, currency). The same key with the same fingerprint returns the
  stored entry. The same key with a different fingerprint raises `IdempotencyConflictError`.
- A reservation and a record that share a key conflict, because the kind is part of the fingerprint.
- Concurrent duplicates: the budget lock serializes same-unit duplicates, so the second request sees
  the committed entry. Cross-unit duplicates may race on the unique index. The insert runs in a
  savepoint, and a unique violation is resolved against the stored row. No `IntegrityError` escapes
  for an ordinary duplicate.
- Legacy rows written before WP1 have no fingerprint. They are returned unchanged and cannot be
  compared. This is the only case where a payload difference is not detected.

## 7. Budget enforcement

- `reserve` and `record` require a budget for the unit and the period containing `occurred_at`. If
  none exists, they raise `BudgetNotConfiguredError` and store nothing. This is fail-closed.
- `reserve` refuses quantity above the remaining budget with `BudgetExceededError`, and stores
  nothing.
- `record` counts usage against the budget even above the limit, and reports overrun. This is the
  documented behaviour for usage reported after the fact.
- Provider cost (`provider_cost_minor`) and customer credits (`customer_credits`) are separate
  units with separate budgets. They are never added together.
- Counters are checked before they are changed. If a release or reverse would make a counter
  negative, the operation raises `UsageInvariantError` and changes nothing.

## 8. Failure handling

- Every function flushes and never commits. The caller owns the transaction. A caller rollback
  removes the entry, the counter change and any outbox event in the same transaction.
- A refused operation raises before any row is written, so the caller does not need to roll back to
  avoid a misleading entry. Callers should still roll back on exception, as the API does.
- A reservation whose work fails must be released. If the process dies before release, the reaper
  releases it after expiry.

## 9. Migration

Revision `e6b1d7a4c9f2` (`backend/alembic/versions/e6b1d7a4c9f2_harden_ai_usage_reservations.py`),
on top of `d4e9a2c6f8b1`. It adds three nullable columns and two check constraints, and a partial
index on open reservations. Existing RESERVED rows receive `created_at + 15 minutes`, so they become
eligible for the reaper rather than holding budget indefinitely. Historical RECORDED, RELEASED and
REVERSED rows are not changed.

If any existing row violates a new check constraint, the migration fails and changes nothing.

Downgrade removes the columns and constraints. Open reservations remain RESERVED and lose their
expiry. They must then be settled or released by hand. Released and reversed history is kept.

## 10. Known limitations

- No AI path calls the ledger yet. Real-world concurrency and expiry behaviour depends on the
  callers that WP1 does not build.
- Budget serialization is per organization, unit and period. High-volume tenants will contend on
  one row. Measure before optimizing.
- Thresholds (70, 85, 100) are still fixed. They are configurable in WP2.
- Denied capability decisions are not audited by this module. Independent audit persistence is WP3.
- Legacy rows without a fingerprint cannot detect a changed payload.
- A reservation longer than 15 minutes cannot settle. This is intentional, and must be designed for
  before any long-running provider call.

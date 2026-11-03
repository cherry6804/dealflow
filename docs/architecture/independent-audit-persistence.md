# Independent audit persistence (WS6 WP3)

Status: implemented in WS6 WP3. Owner: DealFlow backend. Depends on the audit model in
`backend/app/db/models/audit_event.py`.

## 1. Problem

Audit rows were written into the caller's business transaction. When that transaction rolled back, the
audit row disappeared with it. A denied AI execution, a refused budget change, or a failed credential
rotation could leave no record at all. The authorization audit path (`persist_authorization_audit_event`)
already committed independently, but only for authorization decisions.

## 2. Options considered

| Option | Result |
|---|---|
| Keep the audit in the business transaction | Rejected. Lost on rollback, which is the defect. |
| Transactional outbox for audit | Rejected for these records. An outbox row also commits with the business transaction, so it is lost on the same rollback. It also delays visibility to the worker. |
| Dedicated audit writer service or second audit table | Rejected. Duplicates the existing `audit_events` model and creates a second system to operate and secure. |
| **Independent database transaction on the existing table** | **Chosen.** Reuses the model, the table and the existing independent-commit pattern. |

## 3. Design

`backend/app/audit/independent.py` provides one writer, `persist_independent_audit_event`:

- It opens a new session on the caller's engine. The business transaction is neither used nor committed,
  so the row survives its rollback.
- It commits before returning. A failed write raises `AuditPersistenceError`. The caller must not proceed.
- Rows carry the organization, the actor, a correlation identifier, an optional causation identifier and
  an optional idempotency key.
- Metadata is validated before any write. Keys that look like secrets are refused (`secret`, `token`,
  `passw`, `api_key`, `authoriz`, `cookie`, `signature`, `private`, `cipher`, `nonce`, `plaintext`),
  values must be JSON scalars, lists or objects, and the payload is capped at 4096 bytes.

### 3.1 Outcome lifecycle

A governed change records two rows:

1. `requested`, written and committed independently before the change. If this write fails, the change
   does not happen and the request returns 503 `AUDIT_UNAVAILABLE`.
2. `completed`, written in the business transaction after the change. Its `causation_id` names the
   requested row, and it shares the requested row's correlation identifier.

If the change rolls back, the requested row remains and no completed row exists. Nothing claims success.

A denial is terminal and is written once, as `denied`, independently.

Worker outcomes (verification results and system failures) keep no lifecycle. They are recorded as before
and are not governed mutations.

### 3.2 Idempotency and concurrency

- `idempotency_key` is unique per organization through a partial unique index, `uq_audit_events_org_idempotency_key`,
  which applies only where the key is set.
- A second write with the same key returns the stored row. Concurrent writers with one key race on the
  index, and exactly one row results.
- Rows without a key are not constrained.

Current callers do not supply client idempotency keys, so duplicate protection applies only where a caller
supplies one. This is a limitation, not a gap in the mechanism.

### 3.3 Immutability

A PostgreSQL trigger, `audit_events_immutable`, rejects any `UPDATE` that changes audit content. The only
change permitted is the foreign-key action `ON DELETE SET NULL` on `user_id` or `organization_id`, which runs
when the referenced user or organization is deleted. Without that exception, deleting a user would fail.

`DELETE` is not blocked. This is an approved limitation of WP3, not an oversight. Existing test cleanup deletes
audit rows, and no retention or purge policy exists yet. Any row can therefore be deleted directly in the
database until the retention work package adds a controlled deletion path. Until then, audit immutability
covers content updates only, not deletion.

### 3.4 Fail-closed behaviour

- A failed requested write raises `AuditPersistenceError` before the change. The application-level handler in
  `app/errors.py` maps it to HTTP 503 with code `AUDIT_UNAVAILABLE` and `Retry-After: 5`. No internal detail
  is returned.
- A failed completed write rolls back with the business change, leaving the requested row.

### 3.5 Attribution trust boundary

The writer never accepts an organization and actor as plain identifiers. It accepts an `AuditAttribution`
(`backend/app/audit/attribution.py`), which can be created in only two ways, and the writer verifies it on its
own connection before it writes anything.

**Principal propagation (requests).**
- The authentication layer is the only issuer of identity. `get_current_user_context` authenticates the session.
  `get_tenant_context` then confirms the request's organization is the session's organization and that the user
  holds an active membership in an active organization. It calls `issue_principal` and binds the result with
  `bound_principal` (`backend/app/audit/principal.py`).
- The binding is a context variable set by an async generator dependency, which is the form FastAPI keeps visible
  to both synchronous and asynchronous endpoints. A synchronous dependency loses the binding, so one was not used.
  The database check runs in a worker thread so the event loop is not blocked.
- `user_attribution` derives the user and organization from the bound principal. A claimed user or organization
  that differs from the principal is refused. This covers another active member of the same organization, and any
  user in another organization.
- `TrustedPrincipal` and `AuditAttribution` cannot be constructed by hand. Each requires a private token. A source
  test fails if anything other than the authentication layer calls `issue_principal`.

**Membership verification (no request).** Outside an authenticated request there is no principal to bind. The
attribution is then labelled `membership`, and the writer verifies that the user holds an active membership in an
active organization. This is the residual gap in this design, described under Limits.

**System attribution.**
- Each system actor has a `SystemActorCapability`, created once at import by the module that owns the actor
  (`register_system_actor`). Today these are `ai_execution_gate` and `automation_rate_limit`.
- A capability is accepted only if it is the registered object for its name. A name string is refused, and a
  look-alike object is refused. Registering a name twice fails.
- Inside a request, a system record must name the bound organization.

**Verification and refusal.**
- The writer verifies the organization is active, and for a user that the membership is active.
- A failed verification raises `AuditAttributionError` before any row is written. It maps to HTTP 403 with code
  `AUDIT_ATTRIBUTION_DENIED`, and the message names no identifiers. It is separate from a persistence outage (503).

**Limits.**
- **Non-request user attribution is membership-verified, not principal-bound.** Code that runs outside a request
  (none of the current governed paths do) can name any active member of an organization. Closing this completely
  needs a principal carried through every non-request caller. That touches about 75 direct-call tests and needs an
  explicit decision (open decision D-3 in the WP3 report).
- The authentication layer's own correctness (session handling, membership rows, organization binding) is the
  ultimate trust root. This design relies on it, and does not replace it.
- No audit read API exists, so there is no read-side tenant check to test.

## 4. Operations covered

| Operation | Requested row | Completed row | Denial row |
|---|---|---|---|
| Capability enable or disable | yes | yes | — |
| AI usage budget change | yes | yes | — |
| Alert threshold change (WP2) | yes | yes | — |
| Provider credential create, rotate, revoke | yes | yes | — |
| Provider connection create, verification request, rotate, disconnect | yes | yes | — |
| Retention change, legal hold place and release, privacy request create and cancel, export ready | yes | yes | — |
| AI execution denial (`require_ai_execution`) | — | — | yes |
| Rate-limit denial on deal-created automation | — | — | yes |

Not covered, deliberately: worker verification outcomes and system failures in the provider service (their
durability is the attempt log), and authorization decisions, which already committed independently.

## 5. Schema

Migration `b4d8f2a6c1e9`, on `f2a8c4e6b0d3`:

- Adds nullable `outcome`, `causation_id` and `idempotency_key` to `audit_events`.
- Adds the partial unique index `uq_audit_events_org_idempotency_key`.
- Adds `reject_audit_event_change()` and the `audit_events_immutable` trigger.

Existing rows are not changed. Their new columns are null. Downgrade drops the trigger, its function, the index
and the three columns. Rows keep their content, and any lifecycle information stored only in the new columns
is lost.

## 6. Limitations and risks

- **Two rows per success.** Every governed change now records a requested and a completed row. Reports and
  counts must filter by `outcome`. Tests that counted rows were updated to check each outcome explicitly.
- **Connection pool.** Each requested write takes a second connection from the pool while the business
  transaction holds its own. Under heavy governed-change load this doubles connection use for those requests.
  Pool exhaustion would make governed changes return 503 rather than block silently. Operators should watch
  pool wait time and 503 `AUDIT_UNAVAILABLE` rates after deployment.
- **Operational risk.** A failure in the audit table fails every governed change closed. That is intended, but
  it turns an audit outage into a change outage. Monitor the `AUDIT_UNAVAILABLE` response code.
- **Lifecycle semantics.** A `requested` row without a `completed` row means the change was attempted and did
  not commit. It is not an error to be cleaned up, and it is not proof that the change happened.
- **Known limitation: unrestricted deletion.** `DELETE` on `audit_events` is not restricted by the database, as
  approved for WP3. The retention work package owns the controlled deletion path.
- **No audit read API exists.** No endpoint reads `audit_events`, so cross-tenant read denial cannot be tested
  end to end. Organization scoping is enforced when rows are written. A read surface must be designed with
  its own authorization before it is added.
- **DELETE is not blocked** (section 3.3).
- **Client idempotency keys** are not yet supplied by the administrative routes.
- **Pre-existing lint findings** remain in files this change touches but does not own.

## 7. Deployment and migration

1. Apply migration `b4d8f2a6c1e9`. It is additive and quick, but it adds a trigger on `audit_events`. Run it
   during a normal release window.
2. Confirm the Alembic head is `b4d8f2a6c1e9`.
3. Deploy the application. Governed changes now commit a requested row first. If the audit table is
   unwritable, those changes return 503 rather than proceed.
4. Downgrade past this revision drops the lifecycle columns and the immutability trigger.

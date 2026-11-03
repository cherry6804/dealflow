# E13 completion evidence: DFR1-006, DFR1-017, DFR1-050

Status of branch `feature/DFR1-E13-ai-governance-consent-security-usage` after the merge of `origin/develop`. It
separates code completion, test verification, external activation and approved blockers. **No story is Done.** The
epic stays open until every acceptance criterion is met or is an explicitly approved external blocker.

## 1. Status per story

| Story | Code and tests | External activation or decision still required |
|---|---|---|
| DFR1-006 | Central gate on develop's framework with consent, channel policy, approval and budget gates; provider readiness from develop's ADR-0032 subsystem; per-rule and per-step revalidation; audited decisions | DFR1-002 (ADR-0025/26/27 still Proposed). DFR1-005 (SIBVO AI and channel plan keys unconfirmed). Channel send permission (section 6.2). Live provider verification (section 6.1). |
| DFR1-017 | Ledger with reserve, settle, release, reverse, expiry reaper with audit, idempotency, budgets, configurable thresholds, breakdowns by capability, unit and provider, in-app alerts | No AI producer (DFR1-015). SIBVO usage reconciliation (DFR1-053): the usage contract is Proposed, not approved. The maintenance scheduler (D7). |
| DFR1-050 | Table-level inventory enforced by test for all 69 tables; export with not-covered notices; deletion with dependency deferral and post-deletion verification; legal holds; retention for documents and invitations; governed privacy changes recorded independently (section 6.3); log redaction | Decisions D1, D4, D7, D8, D9, D11, D13 (section 3). Encryption at rest (D11) not met for documents. Audit immutability for deletion (D8) not verified. |

## 2. Acceptance criteria mapping

### DFR1-006 (backlog wording)

| Criterion | Evidence | Status |
|---|---|---|
| No optional AI or automation executes unless all applicable gates pass | `evaluate_execution` is the only execution path. Order: actor, resource, consent, channel policy, approval, rate, budget, audit. Denials carry stable reasons. Tests: `test_governance_execution_gate.py`, `test_execution_gates.py`, `test_consent.py`, `test_approvals_and_channel_policy.py`, `test_provider_connection_lifecycle.py` | Met for every capability that has an executor. No AI executor exists yet. |
| Manual CRM operations continue when AI is disabled | `test_manual_deal_creation_still_works_when_automation_is_off` and existing deal API tests | Met |
| In-flight disable policy documented | `ws6-governance-execution-controls.md` (section 2 onwards) and the revalidation tests | Met |

### DFR1-017 (backlog wording)

| Criterion | Evidence | Status |
|---|---|---|
| Provider cost separated from customer credits | Units are never summed; breakdowns group by unit (`usage_breakdown`) | Met |
| Budgets enforced server-side | Reservation inside the gate before billable work; `budget_not_configured`, `budget_exhausted`, `usage_key_conflict` deny | Met. No producer calls it yet. |
| Idempotent usage records | Same key and quantity returns the same entry; a different request under the same key is refused | Met |
| Auditability of every usage adjustment | Reversal writes a requested record before the budget changes and a linked completed record in the same transaction (`reverse` in `usage_ledger.py`; `tests/test_usage_reversal_audit.py`, 6 tests). Release, expiry and budget changes already audit. | Met for reversal, release, expiry and budget changes |
| Configurable 70/85/100 alerts | Organization thresholds (`alert_threshold_service`), 100 fixed; in-app notifications to holders of `governance.budgets.manage` | Met for in-app delivery. No external delivery. |

### DFR1-050 (backlog wording)

| Criterion | Evidence | Status |
|---|---|---|
| Retention jobs auditable | Retention and expiry write the requested and completed records (section 6.3) | Met for documents and invitations |
| Legal holds and required records handled | Holds block deletion and not export; billing and audit records are mandatory records | Met |
| Secrets and sensitive content redacted from logs | Traceback logging removed from document and import services; `tests/test_log_redaction.py` guards it; provider credentials are encrypted and never returned | Met for backend application code |

## 3. Decision records (product, legal or infrastructure owner)

| Decision | Question | Recommended option | Safe interim behaviour (in code) | Owner |
|---|---|---|---|---|
| D1 | Clear free-text fields on deletion, or delete rows? | Clear only approved personal free-text fields (scope in section 5.9 of the architecture document) | Nothing cleared. These categories report `deletion_executor_not_built` | Product and legal |
| D4 | Retention period per category | Set periods per category with a legal basis | No period is set. Retention runs only for documents and invitations, and only after a period exists | Product and legal |
| D7 | Scheduler for `privacy_maintenance` and `usage_maintenance` | Scheduled jobs in the deployment environment | Not scheduled. Both have `main()` entry points | Infrastructure |
| D8 | Audit immutability and deletion | Trigger-enforced immutability and a controlled deletion path | Content updates are blocked by develop's trigger; direct deletion is possible until a retention path exists (WP3, section 3.3) | Security and legal |
| D9 | Classification of remaining unclassified tables | Approve the proposal in section 5.8 | Every table has a recorded disposition in `table_inventory.py`. Nothing is exported or deleted that is not covered | Product and legal |
| D11 | Encryption at rest for stored documents | Managed key from the platform key service | Not met. Documents use private local storage without encryption at rest | Infrastructure and security |
| D13 | Import source files | Document-like: owned by the organization, removed with the batch after retention | Not exported and not deleted | Product |

## 4. External activations still required

- DFR1-002: approve ADR-0025, 0026 and 0027.
- DFR1-005: confirm the SIBVO plan feature keys for AI and channel capabilities.
- DFR1-053: approve the SIBVO usage contract and its reconciliation endpoint.
- Live provider verification: a provider probe runs only with a real credential and enabled live adapters (`PROVIDER_LIVE_ADAPTERS_ENABLED`). Tests use a mocked HTTP boundary only.
- A deployed worker and scheduler for outbox and maintenance jobs (D7).
- A managed key for document encryption at rest (D11).
- A send permission for channels, decided as in section 6.2.

## 5. Verification

Results are recorded in section 7 for the final run.

## 6. Design-gap closure in this merge

### 6.1 Provider subsystem (ADR-0032)

Develop's subsystem replaces the environment-variable design that this branch had built. That design and its 18 tests
are removed. The replacement coverage, in `tests/test_provider_connection_lifecycle.py`, is:

| Removed test (environment-variable design) | Replacement |
|---|---|
| A new connection starts not verified and is audited | `test_registration_stores_only_ciphertext_and_queues_one_check` |
| Invalid kind or secret reference is refused | `test_unsupported_provider_and_a_second_live_connection_are_refused` |
| One connection per kind per organization | `test_unsupported_provider_and_a_second_live_connection_are_refused` |
| The secret value is never stored, returned or audited | `test_registration_stores_only_ciphertext_and_queues_one_check`; credential redaction in `test_provider_secrets.py` |
| A missing secret is reported as unhealthy | `test_creating_a_connection_without_a_key_configuration_writes_nothing` (the equivalent failure is a missing key) |
| Without a registered probe nothing is verified | `test_a_provider_without_an_adapter_is_recorded_and_never_ready` |
| A successful or failing probe verifies or records only its code | `test_a_successful_check_connects_and_makes_the_provider_ready`, `test_a_rejected_credential_fails_and_is_not_ready`, `test_transient_failures_degrade_then_fail_at_the_threshold`, `test_a_timed_out_check_is_recorded_as_a_transient_failure` |
| A fresh verified connection satisfies the gate | `test_the_policy_gate_denies_without_a_ready_provider_and_passes_to_the_next_gate_with_one` |
| A stale verification needs a fresh check | `test_a_stale_verification_is_not_ready` |
| Removing the secret after verification fails closed | `test_revoking_the_credential_makes_the_connection_not_ready` |
| A disabled or unverified connection does not satisfy the gate | `test_disconnecting_ends_the_connection_and_a_new_one_can_be_made`, `test_checks_with_live_access_disabled_never_report_success` |
| A capability without a provider kind always fails closed | Covered by develop's registry: a capability with no provider has no ready provider (`providers_for_capability`). Not separately re-tested. |
| The provider check runs before consent | Consent ordering is tested in `test_consent.py` and the gate order in `test_approvals_and_channel_policy.py` |
| Another organization cannot see or change a connection | `test_another_organization_cannot_read_change_or_use_a_connection` |
| A read-only user can list but not register | `test_a_read_only_user_can_list_but_cannot_create_a_connection` |
| The API registers, verifies and disables a connection | `test_an_owner_creates_a_connection_through_the_api_without_echoing_the_secret`; verification and disconnect through the service tests above |

New coverage not in the removed tests: rotation, revocation, staleness of the credential version, the OpenAI adapter's
status classification at a mocked HTTP boundary (success, 401 rejection, 429 and 503, 404, connect errors, timeout,
live access disabled sends no request), and that the key never appears in any result, attempt or audit row.

Provider live access is not claimed. Verification with a real credential needs the external activation in section 4.

### 6.2 Channel send permission

Decision: **keep channel sending fail-closed. Do not grant a send permission to any role.**

- ADR-0029 gate 5 requires that the initiating user has permission on the target. It names no permission key.
- ADR-0028 (channels) is still Proposed and defines no send permission.
- The gate's default key for capabilities without their own permission is `ai.execute`. That key is not in the permission
  catalogue, so no role can hold it. Owners receive every catalogued key, so they are refused too.
- Tests: `test_channel_send_authorization.py` shows the owner and a member without a send permission are refused with
  `permission_denied`, and an actor who holds a granted key passes the actor gate (a test-only grant).

Decision needed (owner: product and security): the send permission key or keys (for example one per channel), the
roles that receive them (proposed: Admin and DealFlow Owner, with the owner-only set for manage actions), and the
approval that makes the key catalogued. Until then, every channel send is refused with `permission_denied`. No role is
changed by this branch.

### 6.3 Privacy audit independence

Privacy deletion, anonymization, retention and export expiry change data, so they are governed changes under WP3
(`independent-audit-persistence.md` section 3.1). This branch previously wrote their evidence inside the business
transaction, so a rollback removed it. The corrected pattern in `app/governance/privacy.py` and
`privacy_execution.py` is:

- `record_requested_privacy_event` commits a `requested` row in its own transaction before the change. If it cannot be
  written, the change does not run (`AuditPersistenceError`).
- `record_completed_privacy_event` writes the outcome in the business transaction, linked to the requested row by
  `causation_id`. It commits or rolls back with the change.
- Processing and retention work, which has no user, is attributed to the registered system actor `privacy_lifecycle`
  within the bound organization. The request's requester is kept in the metadata.
- A skipped retention category and an export download are single terminal records written independently before the
  work runs.

Tests: `test_privacy_audit_independence.py` shows a requested row survives a rollback, an outcome row does not, a
deletion that fails after its requested row keeps the evidence and records no outcome, a change does not run without
its requested record, and outcome rows link to their requested row. Existing executor tests in `test_privacy_execution.py`
continue to pass.

Not independently committed: the completed outcome. A later failure in the same business transaction removes it, and
the requested row remains as the evidence that the attempt was made. This is WP3's intended behaviour.

## 7. Final verification

Recorded in the merge report. The counts below were produced by the final run on the disposable PostgreSQL 17 database
on port 5438. Port 5433 was not used.

- Backend: 2,114 passed, 14 skipped, 0 failed (full suite, final code including the usage reversal audit, fresh database on port 5438; 399.70 s; the run finished with no failures). The seven reversal-audit tests were rerun after the final import-order fix and passed.
- Frontend: tsc exit 0; vitest 18 files, 123 tests passed; lint 0 errors; build succeeded.
- Migrations: the chain applies from an empty database to head `n5e8a1c4d7b9` (one head, a merge point). Downgrade to `l3c8e2f5a1b7` and re-upgrade succeeded.
- Frontend: 123 of 123 tests passed (18 files). `tsc -b` exit 0. `oxlint` 0 errors (warnings only, in pages this branch does not change). `vite build` succeeded.

## 8. DFR1-053 (SIBVO usage reconciliation) inspection

Inspected SIBVO `develop` at `20df0ef`. Found: an entitlements module with seat routes (`GET`, `POST`, `DELETE` under
`/entitlements`), seat reservation on invitations (migration `f4a8c1e7d290`), and `docs/integrations/seats-and-trials.md`.
Found no usage-ingestion, usage-reporting or reconciliation endpoint, and no approved usage contract. The contract in
Dealsflo `docs/architecture/sibvo-dealsflo-entitlement-contract.md` section 7 is still "Proposed, for approval".

Status: **Blocked** on an approved contract. The minimum contract needed: an ingestion endpoint (or event feed) on SIBVO
that accepts Dealsflo's `reserved`, `recorded`, `released` and `reversed` usage events keyed by
`(organization_id, product_key, event_id)`, returns a reconciliation status per event, and defines who owns meters and
invoices (proposed in section 7 of the contract: SIBVO owns meters and invoices, Dealsflo owns source events). The
independent Dealsflo side (idempotent events, reversals, audit) is implemented; no SIBVO endpoint was created or assumed.

## 9. Completion method

Completion is measured by stories, not by code written. A story counts as Done only when every acceptance criterion is
satisfied and verified, and no approved external blocker remains.

| Story | Status | Basis |
|---|---|---|
| DFR1-006 | Partial (not Done) | Gate and controls implemented and tested. Open: DFR1-002 and DFR1-005 (external), channel send permission (decision), live provider verification (external). |
| DFR1-017 | Partial (not Done) | Ledger, budgets, idempotency, thresholds, breakdowns and audit implemented and tested. Open: no AI producer (DFR1-015), SIBVO reconciliation (DFR1-053, section 8), scheduled maintenance (D7). |
| DFR1-050 | Partial (not Done) | Inventory, export, deletion, holds, retention, governed audit and redaction implemented and tested. Open: decisions D1, D4, D7, D8, D9, D11, D13; encryption at rest (D11). |
| DFR1-053 | Blocked | External: approved SIBVO usage contract (section 8). |

Stories Done: 0 of 4. Criterion-level: the nine backlog acceptance criteria for DFR1-006, DFR1-017 and DFR1-050 are met
in code for the capabilities that exist, with DFR1-050 retention partial (documents and invitations only). Because no
story is Done, the honest epic completion figure is **0%**. The criterion-level figure is reported only as supporting
evidence, not as completion.

## 10. Provider health and readiness (ADR-0032 follow-on)

Audit before implementation. ADR-0032 already provides: lifecycle states (`unverified`, `verifying`, `connected`,
`degraded`, `failed`, `disconnected`); derived readiness that checks status, credential activity, verified credential
version and freshness; exponential backoff with a failure threshold; configurable timeout, verification interval,
freshness window and backoff ceiling; a row-locked outbox handler; scheduled re-verification with time-based
idempotency keys; rotation and revocation handling; per-attempt history; tenant-scoped reads; and secret redaction.

Gaps closed in this unit:

1. **Stale-connection detection is recorded.** Readiness was already derived as `stale`, but nothing recorded the
   transition. The worker now writes one `provider_connection.stale` audit row per staleness episode
   (`app/providers/health.py`). The idempotency key contains the connection and its last successful verification, so
   repeated and concurrent sweeps record each episode once, and a new verification starts a new episode. The row is
   written through the independent audit path with the registered `provider_health` system actor. It contains no
   secret and no provider message. A failed write for one connection is logged and does not stop the sweep.
2. **Denials say why.** The provider gate still returns `provider_not_connected` for every case without a ready
   provider, so existing reason codes are unchanged. `PolicyDecision.provider_readiness` now carries the specific
   state (for example `stale`, `credential_changed`, `credential_revoked`, `failed`, `degraded`). The field appears in
   `as_dict` only for provider-dependent capabilities. `best_provider_readiness` prefers a ready provider and otherwise
   reports the most useful state; it uses the same rules as `any_provider_ready`.
3. **A provider sweep cannot stop unrelated worker duties.** The sweep (due checks and staleness) runs in the same
   worker cycle as usage-reservation expiry and outbox delivery. A database failure in the sweep is logged with its
   error type only and the cycle continues.

Verification of this unit (fresh database on port 5438, final code):

- Full backend suite: exit code 0; 2,129 passed, 14 skipped, 0 failed (473 s) on the final code, including the
  pagination fix for stale sweeps (a first version re-read recorded episodes and could starve a backlog). A first full run had three failures in
  the approval tests, which patched the old `any_provider_ready` name. The shared seam in `tests/governance_helpers.py`
  now patches `best_provider_readiness`, and the rerun passed.
- Focused: provider health, provider lifecycle, policy and approval tests: 84 passed.
- Ruff `check` on all changed backend files: passed.
- Migration graph: single head `n5e8a1c4d7b9`. This unit adds no migration.
- Frontend: not affected. No frontend file changed. The decision payload gains an optional field only for
  provider-dependent capabilities.

Tests: `tests/test_provider_health.py` (14 tests) covers stale recording once per episode, a new episode after a new
verification, repeated and concurrent sweeps writing one row, a failed audit write not stopping other organizations,
secret absence from stale metadata, healthy connections not recorded, the outbox isolation, policy denial reporting the
readiness state, best-readiness precedence, and tenant scoping. Existing lifecycle and policy tests still pass
(44 passed across the three files). Provider calls use the mocked boundary only.

Still open for this story (not met, not claimed):

- **Live provider verification** needs a real sandbox credential and approved data-use terms (external). Until then the
  status is Not verified.
- **The sweep runs only in `python -m app.outbox.worker --serve`.** `--once` dispatches queued events and does not run the
  sweep, so a deployment that only runs `--once` never schedules provider checks or records staleness. The serve cycle is
  covered by `test_the_serve_cycle_schedules_and_runs_a_due_provider_check`, which runs `_outbox_cycle` end to end
  through the real handler. It does not start a separate OS process.
- **Scheduled health probes run only where the worker runs** (D7). If the worker is down, readiness still fails closed
  through freshness expiry, but no stale audit is written until it returns.
- **A failed connection is not re-verified automatically.** It needs a new verify request or an operator replay (WS3).
  This is deliberate, so a permanently rejected credential is not retried in a loop.
- **No alerting or metrics export.** Observability is the audit trail and the worker's structured log lines.
- **Attempt history has no retention purge** (WS3 D-7).
- **Readiness has no dedicated read endpoint for staleness history.** Stale rows are visible through the audit trail
  only.

## 12. WP-E13-next: DFR1-053 lifecycle and billing-webhook coverage

Branch: `feature/DFR1-E13-DFR1-053-lifecycle-tests`, cut from `origin/develop` (`81793d9`).

Scope and what the tests characterise. They describe existing behaviour; they do not add a downgrade feature.

- **Subscription downgrade (Dealsflo side).** SIBVO owns plan activation and its seat-capacity check (contract section 4.1).
  Dealsflo's part is how a downgraded signed snapshot replaces the earlier grant. `tests/test_dfr1_053_downgrade_lifecycle.py`
  covers: a downgrade denied once the next snapshot is due; a downgrade not visible before the held snapshot expires; a
  downgrade that removes the entitlement item (denied as missing); idempotent decisions after the downgrade (one SIBVO
  call); a downgrade snapshot for another organization (rejected, stored snapshot unchanged); SIBVO unreachable when the
  downgrade is due (no extension of the old grant). Six tests, all passing.
- **Billing audit API endpoints.** `tests/test_billing_audit_endpoints.py` sends real HTTP requests through `TestClient`
  against the real database. Only tenant resolution is overridden; the real `enforce_permission` check runs. Covered:
  unauthenticated requests refused; a member without `billing.audit.read` refused on list and detail; the list shows only
  the caller's organization; another organization's record returns 404 on detail; a repeated reconciliation appears once;
  an unknown webhook event writes no record. Six tests, all passing.
- **Billing reconciliation service idempotency.** Existing tests (`test_billing_reconciliation_service.py`) are mock-based.
  The endpoint tests above add a database-backed repeat, which exercises the service's `ON CONFLICT` path.

Defect found and fixed (model and migration drift):

- Migration `7a2c9e4d61b8` creates the unique constraint `uq_billing_reconciliation_records_webhook_event` on
  `billing_reconciliation_records (webhook_event_id)`. The ORM model did not declare it. Schemas built from the models
  (`create_all`, used by the test suite) therefore lacked the constraint. The service's
  `ON CONFLICT ON CONSTRAINT uq_billing_reconciliation_records_webhook_event` then raised `ProgrammingError` on a
  repeated event, instead of returning the existing record.
- Fix: `app/db/models/billing_reconciliation_record.py` declares `UniqueConstraint("webhook_event_id",
  name="uq_billing_reconciliation_records_webhook_event")`. The name and column match the migration exactly. No new
  migration is needed.
- The same file also had two Ruff findings before this change (an unused `select` import and an unsorted `JSON`
  import). Ruff's fix touched those two import lines. No other line changed for that reason.
- Note: a database created by `create_all` before this change keeps the old schema. Only a fresh model-built schema or
  the migration path gets the constraint.

Scope boundaries (not claimed by this work):

- **No Dealsflo webhook ingestion or replay endpoint exists, and none was created.** No Dealsflo code inserts
  `BillingWebhookEvent` rows, and `reconcile_webhook_event` is called only from tests. The SIBVO contract defines no webhook
  endpoint. The "replay through the actual endpoint" objective therefore cannot be met on the Dealsflo side without
  inventing an endpoint. The endpoint tests above cover the existing read endpoints only.
- **SIBVO-owned billing webhook replay** is outside this Dealsflo implementation scope. It belongs to SIBVO's billing module.
- **Downgrade seat-capacity enforcement** is SIBVO-side (contract section 4.1). Dealsflo does not re-check seat capacity on
  downgrade in these tests.

Verification (final code, fresh database `dealflow_test` on port 5438, recreated after the model correction; port 5433 not touched):

- Full Dealsflo backend suite: exit code **0**. **2,141 passed, 14 skipped, 0 failed** (758 s).
- Focused: the six downgrade tests, six endpoint tests, reconciliation service and model tests, billing entitlement,
  entitlement lifecycle and snapshot tests, billing audit API tests: 83 passed.
- Ruff `check` on the three changed backend files: passed.
- Migrations on an empty database `dealflow` (port 5438): `upgrade head` exit 0; `downgrade b4d8f2a6c1e9` exit 0;
  `upgrade head` exit 0. Single head `n5e8a1c4d7b9`. `downgrade -1` is refused with "Ambiguous walk" because the head is a
  merge point. That behaviour is in the existing graph and this change does not affect it.
- Frontend: not affected. No frontend file changed.
- SIBVO repository: not changed, so no SIBVO test run was required.

Status after this work: DFR1-053 remains **Blocked** (usage summaries and reconciled usage need the approved SIBVO usage
contract). The downgrade criterion and the webhook replay criterion now have lifecycle coverage in Dealsflo; endpoint-level
replay has no Dealsflo endpoint to test. E13 is not Done, and no story is Done.

## 14. WP-E13-decision-readiness: decision register and matrices

Deliverable: `docs/architecture/e13-decision-readiness.md`. Documentation only. It contains:

- a decision register covering the seven privacy and governance decisions (D1, D4, D7, D8, D9, D11, D13), the AI actor
  key, the AI and channel entitlement keys, role granting, fail-closed behaviour, and the SIBVO integration items (usage
  contract, event schema, idempotency, reversal, retry and replay, identity mapping, webhook ownership, failure audit);
- the dependency matrix, the implementation impact matrix, the decision-to-test traceability matrix, the prioritized
  sequence, and the list of decisions that block E13 completion versus those that can wait.

Each decision lists its current implementation, the unresolved question, its options, the trade-offs, the security and
tenant-isolation implications, the impacted files, the required tests, its dependencies and owner, a recommendation
labelled as such, and the cost of delay. No decision is approved.

Naming note: the user's labels for D1 and D9 differ from the existing register. The mapping is in the deliverable.

Story status: unchanged. DFR1-006, DFR1-017 and DFR1-050 remain Partial; DFR1-053 remains Blocked; E13 is not Done.

## 15. Post-merge verification of the decision-readiness documentation and identifier resolution

- PR #151 is merged into `develop` as merge commit **`137a3d1`**. Commit `e0d558b` is an ancestor.
- The merge changed three files, all under `docs/`: this evidence document, `e13-decision-readiness.md`, and the tracker.
  No application code, migration, permission, entitlement key, endpoint or configuration changed.
- `e13-decision-readiness.md` contains 20 decision entries and the dependency, implementation-impact, traceability and
  sequence matrices (Parts A to F).
- The identifier conflicts are recorded in `docs/architecture/e13-decision-resolution-plan.md`. D1 and D9 have competing
  definitions in the register and in the readiness file. Several D-numbers (D1, D4, D7, D8) also name different decisions
  in ADR-0032. No identifier was renamed or reinterpreted. The release owner must rule on the scheme (options R1 to R3
  for D1 and D9, and N1 or N2 for the collisions).
- The owners are recorded as roles in the sources. The repository names no individual, so no one is named in the plan.

Story status: unchanged. DFR1-006, DFR1-017, DFR1-050 remain Partial; DFR1-053 remains Blocked; E13 is not Done.

## 16. AI actor execution permission: proposal for approval (not approved)

- Merge state checked: PR #152 is merged into `develop` as `22a4c54`, which includes `84d5d11`.
- Proposal: `docs/architecture/e13-ai-actor-permission-proposal.md`. It records the current authorization behaviour, the
  findings and conflicts, a candidate key (`governance.ai.execute`, a placeholder), the role grants, delegation and
  attribution, default deny, the capability, entitlement, consent, readiness and budget interactions, revocation, audit,
  tenant isolation, and the required tests.
- Key findings: `ai.execute` is referenced by the gate but not catalogued, so every AI request is refused today. Deal-created
  automation already reuses the target permission (`deals.create`), which conflicts with the readiness file's recommended
  new key. The proposal keeps both gates, the target permission and the AI key.
- **Not approved.** The approval needed is six answers from the release owner and the security owner, listed in section 10
  of the proposal. No permission key has been added and no role grant has changed.
- Story status: unchanged. DFR1-006 remains Partial; DFR1-017, DFR1-050 and DFR1-053 keep their status; E13 is not Done.

## 17. DFR1-015 AI gateway core (E06) and DFR1-016 status

Branch: `feature/DFR1-E06-ai-gateway-core`, cut from `origin/develop` at `6eab89a`. This is an E06 unit, recorded here
because the E13 governance gates it depends on are documented in this file.

What exists (code and tests):

- Organization task routes: `ai_task_routes` (migration `f7c3a9d1e5b2`, one row per organization and task, no credential
  stored). Owner-only write through `governance.capabilities.manage`; read through `governance.capabilities.read`.
  Provider keys must be LLM providers in the registry, and model names are validated.
- Adapter boundary: an OpenAI text and embedding adapter. It makes no network call while live access is disabled. Tests use
  an httpx mock transport. The adapter classifies responses as success, transient, timed out or permanent, and never reads
  or logs a response body beyond the output it returns.
- Execution path (`app/ai_gateway/service.py`): task support, route, the shared execution gate (entitlement, switches,
  provider readiness, actor, resource, consent, rate, budget), credential resolution for the organization only, bounded
  attempts (retries only transient failures), settlement of actual usage against the gate's reservation, and
  schema-checked structured output.
- Failure handling: a failed call with no usage releases the reservation. A provider answer whose usage cannot be settled
  is withheld (`usage_settlement_failed`), so no unmetered output is returned.

Verification (final code):

- `tests/test_ai_gateway.py`: 52 tests, all passing on the isolated database (port 5438). They cover adapter HTTP
  mapping, structured-output acceptance and refusal, the execution path, retries and timeouts, credential and live-access
  failures, budget and gate denials, tenant isolation of routes and credentials, secret absence from results and audit
  metadata, route validation and audit, and owner-only route writes over HTTP.
- Migration on an empty database `dealflow`: upgrade head, downgrade one step, re-upgrade. Single head
  `f7c3a9d1e5b2`.
- Ruff `check` on the new and changed backend files: passed.
- Full backend suite on the final code: exit code 0; 2,193 passed, 14 skipped, 0 failed (900 s), on the isolated database (port 5438), recreated before the run. Port 5433 was not touched.

Test-only seams (documented in the test module): readiness (no verified connection can be created without a live
provider), the AI actor key (pending approval), the AI resource gate (no AI resource store exists), and the AI rate decision
(no rate rule is approved). Each is patched for tests only. The production denial order is asserted by
`test_production_layers_deny_in_order_and_never_reach_the_provider`: actor, then resource, then rate.

What is not met, and why DFR1-015 is not Done:

- No live sandbox verification. No provider credential or sandbox account exists in this environment, and no fabricated
  provider result is recorded.
- Production AI execution remains denied. No approved AI actor key, no AI resource store (agents and workflows arrive
  with DFR1-018 and DFR1-019), and no approved AI rate rule exist. Each is a decision or a dependency, not something this
  unit may invent.
- Fallback provider: the acceptance criterion names it; none is implemented.
- Speech, multimodal, audio, image and page usage: declared in the task model, with no adapter.
- Outcome audit: execution outcomes are visible through the usage ledger (settled and released entries) and the gate's
  decision audit. A requested and completed outcome audit (the WP3 pattern) is not yet added to the gateway.
- Frontend: no UI for routes. Not required for the backend criterion; the route API is ready for one.
- Lint debt: `app/db/models/__init__.py` already had four Ruff findings on `develop`. They are unchanged here. This change
  adds two lines to that file and no new finding.

DFR1-016 (knowledge ingestion and retrieval): not started. It depends on DFR1-015 and on the same production gates.

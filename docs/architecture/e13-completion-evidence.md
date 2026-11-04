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

## 19. DFR1-015 completion pass (E06): gaps, classification and verification

Branch: `feature/DFR1-E06-ai-gateway-core`. This pass adds the two code-level gaps and classifies the rest.

Acceptance criteria, classified:

| Criterion | State | Classification |
|---|---|---|
| Route text, embedding, speech and multimodal tasks through adapters | Text and embedding implemented; speech and multimodal refused with `task_not_supported` | Provider dependency (no speech or multimodal provider chosen) |
| Timeout | Implemented, bounded (`ai_gateway_timeout_seconds`) | Met |
| Retry | Implemented, transient failures only, bounded (`ai_gateway_max_attempts`) | Met |
| Fallback | **Implemented in this pass.** Optional second route per task, tried only after a transient failure. Permanent failures stop the task. | Code gap, closed |
| Structured outputs | Implemented for text (exact key set and JSON types) | Met for text; embeddings return vectors |
| Provider and model configurable by task | Implemented (owner-only routes, primary and fallback) | Met |
| Secrets protected | Credentials resolved per organization at call time, never stored in routes, never in results or audit | Met |
| Token usage captured | Implemented (input and output tokens, settled to actual) | Met |
| Audio, image and page usage captured | Units exist; no provider reports them | Provider dependency |
| Provider failure handled safely | Implemented (classified failures, released reservations, withheld unmetered answers) | Met |
| Outcome audit for model calls | **Implemented in this pass.** Requested record committed before any provider call; completed record linked to it, holding codes and numbers only | Code gap, closed |
| Live sandbox verification | Not performed. Needs a credential and approved data-use terms | External approval and credential |

Decisions made in this pass (implementation-level, not product decisions):

- A fallback is tried only after a transient failure or a missing credential. A permanent failure stops the task, because
  another provider would hit the same fault, or would answer a request the first provider refused.
- The requested audit record is written after the gate allows the call and before the credential is resolved. If it cannot
  be written, the call is not made.
- The completed audit record holds the task, provider, model, outcome, reason code, attempt count and usage numbers. It never
  holds the prompt, the output or the credential.

Verification on the final code (`feature/DFR1-E06-ai-gateway-core`):

- Backend, focused: `tests/test_ai_gateway.py`: 62 passed.
- Backend, full suite (fresh `dealflow_test` on port 5438): exit code 0; 2,203 passed, 14 skipped, 0 failed (386 s).
- Migration on a fresh `dealflow` database (port 5438): upgrade head exit 0; downgrade one step exit 0; re-upgrade exit 0.
  Single head `f7c3a9d1e5b2`. The fallback columns and the pair constraint are present.
- Ruff `check` on the changed backend files: passed.
- Frontend (`frontend/`): `npm run build` (tsc -b and vite build) exit 0; `npm run lint` exit 0 with two existing warnings in
  `RequirementsPage.tsx` and `DealsPage.tsx`, neither touched here; `npx vitest run` exit 0, 123 passed. No frontend file changed.

Commands used (reproducible on the disposable server):

```
DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5438/dealflow_test APP_ENVIRONMENT=test .venv/Scripts/python.exe -m pytest tests/test_ai_gateway.py -q
DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5438/dealflow_test APP_ENVIRONMENT=test .venv/Scripts/python.exe -m pytest -q
DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5438/dealflow alembic -c ../alembic.ini upgrade head   (then downgrade -1, upgrade head)
.venv/Scripts/ruff.exe check app/ai_gateway app/api/ai_gateway.py app/db/models/ai_task_route.py tests/test_ai_gateway.py
cd frontend && npm run build && npm run lint && npx vitest run
```

Not done, and why this story stays open:

- No live provider verification (external: credential and data-use approval).
- Speech and multimodal adapters, and audio, image and page usage (provider choice required).
- Production AI execution stays closed: the AI actor key, the AI resource store and an approved AI rate rule are open
  (see `e06-ai-execution-decision-proposal.md`).
- DFR1-016 (knowledge ingestion) has not started.

## 20. DFR1-015 resume record (not ready to merge)

Status: **NOT READY TO MERGE.** Code complete for the parts that need no external input. Story stays open.

Branch: `feature/DFR1-E06-ai-gateway-core`. Commits: `17ce46a` (gateway core), `0d37fb0` (fallback and outcome audit).
Base: `origin/develop` at `6eab89a`. No PR exists yet. Merge: not authorized.

Exact items that prevent completion (external, not code):

1. Product approval, AI actor key: `governance.ai.execute` (or a named alternative), grants, and owner-only status. Source:
   `docs/architecture/e13-ai-actor-permission-proposal.md`, section 10.
2. Product approval, AI rate rule values (requests per user, per organization, concurrency). Currently refused by design
   (`rate_limit_not_configured`). Source: `docs/architecture/e06-ai-execution-decision-proposal.md`, section 3.
3. AI resource store and publish state (DFR1-019). Without it the resource gate refuses every AI call. This is a dependency on
   another story, not an approval.
4. Provider data-use approval for OpenAI (E01 matrix, row 5). Blocks any call that carries customer data.
5. Sandbox credential and a sandbox organization with a spend cap, then one recorded successful live verification, and
   `PROVIDER_LIVE_ADAPTERS_ENABLED=true` in that sandbox only.
6. First speech and multimodal provider choice, if those acceptance items stay in DFR1-015 (otherwise they move to a later story).

Code-level items that remain: none for DFR1-015 beyond the above, provided the approvals are granted as proposed.
When item 1 is granted, the code change is: add the key to the catalogue (migration to backfill existing roles), point
`DEFAULT_AI_PERMISSION` at it, and remove the test seam `allow_actor_execution_permission` from the gateway tests only where the
production path is tested.

Resume checklist (next session):

1. `git switch feature/DFR1-E06-ai-gateway-core` and confirm `0d37fb0` (or the newer commit recorded here).
2. Confirm the decisions above in writing before changing any gate or configuration.
3. Commands (from `backend/`, with the disposable server on port 5438 running, never port 5433):
   - `DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5438/dealflow_test APP_ENVIRONMENT=test .venv/Scripts/python.exe -m pytest tests/test_ai_gateway.py -q`
   - `DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5438/dealflow_test APP_ENVIRONMENT=test .venv/Scripts/python.exe -m pytest -q`
   - `DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5438/dealflow alembic -c ../alembic.ini upgrade head` (then `downgrade -1`, `upgrade head`)
   - `.venv/Scripts/ruff.exe check app/ai_gateway app/api/ai_gateway.py app/db/models/ai_task_route.py tests/test_ai_gateway.py`
   - `cd frontend && npm run build && npm run lint && npx vitest run`
4. Reusable components: `app/ai_gateway/` (service, routing, adapters, structured, contracts, tasks), the execution gate,
   the usage ledger, `app/provider_secrets` (credential resolution), the independent audit writer, `tests/governance_helpers.py`
   seams.
5. Recovery note: if the disposable PostgreSQL on port 5438 is not running, restart it from its own data directory
   (`C:/Users/amoun/AppData/Local/Temp/e13-pg-5438`) with `pg_ctl`. Do not use port 5433.
6. Open PR text: `C:/Users/amoun/AppData/Local/Temp/` (regenerate from section 19 if missing). The PR must say "not ready to
   merge" until items 1 to 5 are resolved.

## 21. DFR1-016 tenant-scoped knowledge ingestion and retrieval (E06)

Branch: `feature/DFR1-E06-knowledge-ingestion`, cut from `origin/develop` at `da28b6b` (DFR1-015 merged as PR #154).
Dependency DFR1-015: merged. Story is not Done; see the open items.

Built:

- Chunking: bounded windows (1,000 characters, 100 overlap), at most 200 chunks per document, documents up to 1 MB.
- Ingestion (`app/knowledge/service.py`, `ingest_document`), in order: `documents.read` checked in the database; the document is
  available and in the organization; its classification is eligible; its content type is plain text; the bytes decode as strict
  UTF-8. Embeddings go through the AI gateway (`ai.document_processing`, embedding task). Chunks are written only after every
  embedding succeeds. Re-ingesting unchanged content makes no provider call.
- Retrieval, in order: `documents.read`; query bounds; one gateway embedding; chunks of available, eligible documents of the
  organization only; best `top_k` by cosine similarity, with citations (document id, display name, chunk index). Results carry
  `untrusted=True`; the module never places retrieved text into a prompt.
- Derived data: `knowledge_chunks` (migration `b9e4f2a7c1d3`, downgrade drops it). Chunks are removed by
  `remove_document_chunks`. Retrieval also filters on the document's current status, so a stale chunk is never returned.
- Privacy inventory: `knowledge_chunks` is `not_covered`, with the reason that it is derived and removed with its source.

Gaps fixed while building this story:

- **Gateway reservation key (defect, DFR1-015 code).** The gate's reservation key came from the correlation id and capability.
  Two calls for the same capability with no correlation id shared a key, so the second call was refused as
  `usage_key_conflict`. Every gateway call now carries its own idempotency key. Covered by the retrieval and ingestion tests,
  which make several calls in one test.

Eligibility (proposal, not approved): only `PUBLIC` and `INTERNAL` documents are ingested. `CONFIDENTIAL` and `RESTRICTED` are
excluded until product approves otherwise.

Verification:

- `tests/test_knowledge.py`: 24 tests passing. Covers chunk bounds, storage with embeddings, unchanged re-ingestion, permission
  refusal, classification refusal, content-type and encoding refusal, unavailable and foreign documents, oversized documents
  and too many chunks, failed embedding leaving prior chunks untouched, production refusal, ranking with citations, exclusion of
  archived, restricted and foreign documents, permission refusal for retrieval, invalid queries, data-only handling of hostile
  text, chunk removal, and metering through the gateway.
- Full backend suite (DFR1-016 first commit): exit code 0; 2,227 passed, 14 skipped, 0 failed (595 s).
- Migration on a fresh `dealflow` database (port 5438): upgrade head exit 0; downgrade one step exit 0; re-upgrade exit 0;
  single head `b9e4f2a7c1d3`.
- Ruff: the new and changed files pass. `app/db/models/__init__.py` keeps four findings that exist on `develop` (an unsorted
  import block, a duplicate import, an unsorted `__all__`, and a duplicate `__all__` entry); this change adds two lines to that
  file and no new finding.
- Frontend: `npm run build` exit 0, `npm run lint` exit 0 (two existing warnings), `npx vitest run` exit 0 with 123 tests. No
  frontend file changed.

Open items (external or product, not code):

1. The AI actor key, the AI resource store (DFR1-019) and an approved AI rate rule. Until then every embedding is refused by
   the production gate, so ingestion and retrieval cannot run in production.
2. Live embeddings need provider data-use approval and a recorded sandbox verification (E01 matrix, row 5).
3. Eligible classifications: product approval (the proposal above).
4. Similarity search is application-side. A pgvector index needs the `vector` extension, which is not installed on the test
   server. Installing it, or accepting application-side search at this scale, is a decision.
5. Not built: an HTTP route, a hook from document upload, text extraction for PDF and office formats, and a prompt-injection
   evaluation against a real model (no model is reachable in tests).

Pending work reported in Phase 1 of this story (nothing discarded, nothing merged):

- `feature/DFR1-E07-typed-tool-registry` (DFR1-018): one commit `6937172`, no PR. Depends on DFR1-008, which is open.
- `docs/E06-ai-execution-decisions`: one commit `1c2e397`, no PR (documentation).
- `docs/E13-post-merge-audit`: two commits, no PR (documentation).
- `docs/E13-post-merge-verification-2`: two commits, no PR (documentation).
- `main` is four commits ahead of `develop` (revert and CI commits). Not touched.

## 22. DFR1-016 completion pass: HTTP APIs, upload lifecycle, extraction, deletion, and untrusted content

Branch: `feature/DFR1-E06-knowledge-ingestion`. Builds on the first commit `57e9e2a`.

Built in this pass (reusing the existing gateway, document service, outbox, privacy executor and tenant/permission stack):

- **HTTP APIs** (`app/api/knowledge.py`): `POST /api/v1/knowledge/documents/{id}/ingest` (repeat-safe) and
  `GET /api/v1/knowledge/search` (query 1 to 200,000 characters, top 1 to 10). Both require `documents.read` in the verified
  organization and the current user. Search hits carry `untrusted_data: true`.
- **Upload lifecycle:** the upload commit also enqueues `knowledge.ingest_requested` in the same transaction
  (`app/documents/service.py`). The outbox handler (`app/knowledge/handlers.py`) runs in both worker entry points. A transient
  provider failure raises and is retried by the outbox. A refusal (AI off, ineligible document) is recorded and not retried.
- **Extraction** (`app/knowledge/extraction.py`): plain text, Markdown and CSV (strict UTF-8); XLSX through openpyxl, which the
  project already declares; DOCX through the standard library (ZIP and `word/document.xml` only). Limits: 10 MB XML, 500 ZIP
  members, 20 MB uncompressed, 10 sheets, 5,000 rows, 50 columns, 200,000 characters. DOCTYPE and ENTITY declarations are refused.
  PDF through `pypdf` 6.21.4 (text only; encrypted files, malformed files, zero-page files and files over 100 pages are refused;
  200,000 characters maximum; recovery and cross-reference limits set). Legacy or presentation formats are refused with
  `format_not_supported`. Dependency record: `docs/development/python-dependency-register.md`.
- **Deletion:** the privacy document executor (`app/governance/privacy_execution.py`) removes a document's chunks before the
  document row. Without this, the RESTRICT foreign key would have made every ingested document undeletable (a defect found
  here and fixed).
- **Concurrency:** ingestion locks the document row, so concurrent requests for one document serialize.
- **Gateway fix** (from the first commit): each gateway call has its own budget-reservation key.

Requirement mapping:

| Requirement | Status |
|---|---|
| Authenticated, tenant-scoped APIs | Met (tests: 403 without `documents.read`, cross-tenant search returns nothing, cross-tenant ingest returns `document_unavailable`) |
| Upload lifecycle integration | Met (event in the upload transaction; handler indexes the stored file; tests use real local storage) |
| Safe extraction for supported formats | Met for TXT, MD, CSV, XLSX, DOCX and PDF (pypdf, approved for this story). Malformed, encrypted, oversized and page-limit PDFs are tested and refused |
| Prompt injection and untrusted retrieved content | Met as data handling (hostile text returned verbatim in `untrusted_data`, response shape fixed, no permission change). A model-level evaluation needs a reachable model |
| Retrieval with available infrastructure | Met (application-side cosine over org-scoped rows; no extension required) |
| Deletion, reprocessing, duplicate ingestion, authorization, tenant isolation, failure recovery | Met (tests in `tests/test_knowledge_lifecycle.py` and `tests/test_knowledge.py`) |
| Gate, usage ledger, budget and audit for every embedding | Met through the gateway (each embedding is gated, metered and audited) |

Verification (final code, `feature/DFR1-E06-knowledge-ingestion`):

- Focused: `tests/test_knowledge.py`, `tests/test_knowledge_lifecycle.py`, `tests/test_ai_gateway.py`: 116 passed on the final
  code (after the docstring change, on a freshly created `dealflow_test`). The earlier 107 figure was before the PDF tests.
- Full backend suite, after the PDF pass (`d016c-full.log`, pytest exit code 0): 2,257 passed, 14 skipped, 0 failed (397 s).
  Earlier run on the pre-PDF code: 2,248 passed, 14 skipped, 0 failed (516 s).
- Migration, fresh `dealflow` on port 5438: upgrade head exit 0; downgrade one step exit 0; re-upgrade exit 0; single head
  `b9e4f2a7c1d3`.
- Ruff: clean on the new and changed files. Pre-existing findings are unchanged and not introduced here: four in
  `app/db/models/__init__.py`, and one blind `except` in `app/documents/service.py` (present on `develop`).
- Frontend: build exit 0; lint exit 0 (two existing warnings); `vitest run` exit 0 with 123 tests. No frontend file changed.

External approvals and dependencies still open (the code-level criteria are complete except where they need these):

1. PDF extraction: resolved. `pypdf` 6.21.4 is pinned; the advisory scan reports no known vulnerabilities; the licence file is
   BSD-style. The approver should still confirm the full licence text in the dependency register.
2. `vector` extension: not needed for the current implementation. Only a later index optimization would need it.
3. Eligible classifications: product approval (proposal: `PUBLIC` and `INTERNAL` only).
4. Production AI execution: the AI actor key, the AI resource store (DFR1-019), an approved AI rate rule, provider data-use
   approval, and a sandbox credential with a recorded verification. Until these exist, every embedding is refused by the gate.
5. Document upload has no archive or delete endpoint of its own. Deletion runs through the privacy executor. Archive
   status changes, if added later, must also call `remove_document_chunks` and `remove_document_review`.

## 23. DFR1-035 document and multimodal extraction MVP (E10)

Branch: `feature/DFR1-E10-document-extraction-mvp`, cut from `origin/develop` at `eb21536` (DFR1-016 merged as PR #155).
Dependencies DFR1-015 and DFR1-016 are on `develop`.

Routes, chosen by what the stored file is. Every route runs under the same tenant, permission, eligibility and deletion rules.

| Stored file | Route | Provider call | Stored when |
|---|---|---|---|
| PDF with a text layer | Labelled values copied from the text layer | None | Any page yields text |
| Scanned PDF: no text, every page a JPEG drawn on the page, up to 5 pages | OCR adapter, page by page, then the same labelled-value rules on the transcript | One gateway multimodal call per page | Every page transcribed by the gateway |
| PNG or JPEG, including floor plans | Gateway multimodal task with a structured output | One gateway call | The reply matches the schema |

Built:

- **Gateway** (`app/ai_gateway`): `TaskType.MULTIMODAL` is implemented. An `ImageInput` carries the bytes; its repr excludes them.
  The gateway accepts one PNG or JPEG per request, at most 8 MB, whose bytes match the stated type. It requires a structured
  output schema and an input estimate. Budget units reserved per call: output tokens, estimated input tokens and images. The
  OpenAI adapter sends the image inline as a data URL and reports the image count, so the images reservation settles.
  Nothing else changed in the gateway's existing text and embedding paths.
- **Execution controls, unchanged and applied to every call:** entitlement and switches, provider readiness, actor permission,
  rate, budget, route selection, credential resolution, timeout, bounded retries, and audit. An organization with no
  `images` budget is refused with `budget_not_configured` before any provider call.
- **OCR adapter** (`app/multimodal/ocr.py`): `OcrAdapter` is the provider-independent interface. `GatewayOcrAdapter` is the
  only implementation, so no OCR engine is built and no text is produced unless the gateway answers.
- **Scanned-page extraction** (`app/knowledge/extraction.py`, `extract_embedded_jpeg_pages`): reads each page's own image
  resource and checks the JPEG signature. No rasteriser, no Pillow. Pages drawn any other way are refused with
  `scanned_page_unavailable`. More than five pages are refused with `ocr_page_limit_exceeded`.
- **Review** (`app/multimodal/review.py`): fields come from a fixed allowlist of keys. Model output is dropped unless every
  part is present, the key is allowlisted, and the confidence level is one of high, medium or low. The model's evidence is
  kept as a quote. Summaries from the model are stored as text and never change permissions.
- **Traceability:** each field carries its page number, its evidence, its `evidence_basis` (`text_layer`, `ocr_transcript`, or
  `model_quote`), its confidence (`verbatim_text_layer`, `ocr_transcription`, or `model_reported_<level>`), and the method,
  provider and model. The response carries `untrusted_data: true` and a disclaimer.
- **Storage** (`app/db/models/document_review.py`, migration `c1a5e7d9f3b4`, not yet on develop): one review per document,
  now with `method`, `provider_key` and `model`. Re-review replaces the row under the document row lock. Refusals store nothing.
- **Reuse:** `documents.read`, the classification rule (`PUBLIC` and `INTERNAL` only, a proposal), the document lifecycle,
  privacy deletion (`remove_document_review`, called before the document row), the table inventory, and the gateway's audit
  and usage records.

Refusals, with the reason returned and nothing stored:

| Condition | Reason | Provider call |
|---|---|---|
| No route for the multimodal task | `no_route_configured` | None |
| No `images` budget | `budget_not_configured` | None |
| Bytes do not match the stated type, or over 8 MB | `invalid_request` | None |
| Two provider failures (5xx or 429) | `failed` with `provider_unavailable` | Two |
| Reply does not match the schema | `failed` with `invalid_structured_output` | One |
| Scanned page is not a directly drawn JPEG | `scanned_page_unavailable` | None |
| More than five scanned pages | `ocr_page_limit_exceeded` | None |
| A page's OCR fails after earlier pages worked | `failed` with `provider_unavailable`; no partial text stored | Earlier pages and the failed page |
| `CONFIDENTIAL`, `RESTRICTED` | `classification_not_eligible` | None |
| Another organization | `document_unavailable` | None |
| Encrypted, malformed, text formats, legacy formats | `encrypted_document`, `content_unreadable`, `format_not_supported` | None |

Acceptance criteria:

| Criterion | Status |
|---|---|
| Process PDFs for text, metadata and structured fields | Met for PDFs with a text layer |
| Process images and floor-plan images | Code-level complete through the gateway's vision-capable route, tested against a mock provider boundary. **Blocked in production** (see open items 1 and 2) |
| Scanned-PDF detection and OCR through a provider-independent adapter | Detection and the adapter are complete and tested with a mock. **Blocked in production** by the same approvals. No other OCR path exists |
| Structured information with source references, pages and confidence | Met. Model and OCR outputs are labelled with their basis and are not verified facts |
| Image, floor-plan, scanned-PDF, malformed, unsupported, oversized and tenant-isolation validation | Met (tests listed below) |
| Outputs traceable and treated as untrusted data | Met |
| Reuse of lifecycle, deletion, audit and usage controls | Met |
| Upload is scanned | **Not met.** No malware scanner exists in this repository. Upload validates file signatures only |

Tests:

- `tests/test_document_vision_ocr.py` (15 tests): floor-plan review through the vision route with quoted evidence and the
  image's exact bytes sent; allowlist and completeness filtering, with injected summary text as data; schema mismatch refused;
  provider outage stores nothing; no images budget sends nothing; mismatched and oversized image bytes never sent; another
  organization cannot send an image; scanned-PDF transcription page by page with page numbers kept; OCR page limit; a failed
  page stores nothing; non-JPEG scanned page refused; JPEG page order and repr; extractor refusals; gateway refusal without a
  route.
- `tests/test_document_review.py` (16 tests): PDF text-layer values, summaries and metadata, get after post, re-review,
  scanned PDF without a JPEG page refused, images without a route refused, text formats, confidential and restricted,
  encrypted and page-limit PDFs, invalid PDF refused at upload, documents.read on both routes, tenant isolation, hostile
  text stays data, deletion removes the review.

Verification (final code on `feature/DFR1-E10-document-extraction-mvp`):

- Focused, `tests/test_document_vision_ocr.py` and `tests/test_document_review.py`: 31 passed.
- Full backend suite: 2,287 passed, 14 skipped, 1 failed (exit 1, 378 s). The failure is `tests/test_provider_health.py::test_concurrent_sweeps_record_each_episode_once`, a real-thread race test on the provider health sweep. This branch does not change `app/providers/`. The same test failed in 2 of 4 isolated reruns and passed in 2, so it is intermittent. It is recorded as a known flaky test, not fixed here.
- Migrations on a freshly created `dealflow` database (port 5438): upgrade head exit 0; downgrade one step exit 0;
  re-upgrade exit 0; single head `c1a5e7d9f3b4`.
- Ruff: clean on every new and changed backend file, including the test files.
- Security: `pip-audit` on the exported locked dependency set: "No known vulnerabilities found", exit 0. No new dependency.
- Frontend (no frontend file changed): `npm run build` exit 0 (includes the TypeScript build); `npm run lint` exit 0;
  `npx vitest run` exit 0, 123 tests.

Open items (external approvals or provider work; each one blocks a criterion named above, and none is marked done):

1. Image and floor-plan review in production: the AI actor key for `ai.document_processing`, the AI resource store (DFR1-019),
   an approved AI rate rule, provider data-use approval, a sandbox credential with a recorded verification, a vision-capable
   model routed for the multimodal task, and an `images` budget per organization. Until these exist, the gate refuses every call.
2. Scanned-PDF OCR in production: the same approvals as item 1, since OCR runs through the same gateway task.
3. Upload malware scanning: no scanner is in this repository.
4. Eligible classifications: product approval (proposal: `PUBLIC` and `INTERNAL` only).
5. Mixed PDFs (some pages with text, some scanned) are read from the text layer only. Scanned pages are routed to OCR only
   when the whole document has no text.
6. No review UI. The API is the only surface.

## 24. DFR1-035 completion pass: malware scanning and a provider-health concurrency defect

Branch: `feature/DFR1-E10-document-extraction-mvp`, continuing from `21a3237`.

### Concurrency defect (pre-existing on develop, not caused by DFR1-035)

- Test: `tests/test_provider_health.py::test_concurrent_sweeps_record_each_episode_once`. Reproduced at 1 failure in 8 isolated
  runs before the fix. A temporary probe showed the per-sweep counts as `[1,1,1,1]`, `[0,1,1,1]`, `[1,1,0,1]` and similar, with
  one audit row in every run.
- Root cause: `_record_stale` checked whether an episode was recorded, then inserted it. When two sweeps raced, the loser's
  insert hit the idempotency key. `persist_independent_audit_event` then returned the stored row, and `_record_stale` treated
  that as a successful write. Every racing sweep therefore counted an episode it did not record, so the reported count was
  wrong. The stored data was correct: one row, guarded by the unique partial index.
- The test's expectation `all(count == 1)` codified that over-count. It is corrected to `sorted(results) == [0, 0, 0, 1]`: exactly
  one sweep writes the episode and the others count nothing. The correction is to the expectation, and the defect is fixed in
  the code.
- Fix: `persist_idempotent_audit_event` (in `app/audit/independent.py`) returns True only when the call wrote the row. The
  internal writer is shared, so the audit trail's behaviour is unchanged. `_record_stale` uses it.
- Regression: `test_a_sweep_that_loses_the_insert_race_counts_nothing` forces the race deterministically and asserts the count
  is zero. The concurrency test passed 40 of 40 isolated repetitions after the fix. `tests/test_provider_health.py` passed 15 of
  15 repeated runs.
- Develop: `app/providers/` and `app/audit/` are unchanged on this branch compared with `origin/develop`, so the defect is present
  on develop. A separate fix is not needed beyond this change.

### Upload malware scanning (new)

- Scanner interface: `app/malware_scanning/base.py` (`MalwareScanner`, `ScanStatus`, `ScanResult`). Only `clean` lets a file be
  stored. `infected`, `too_large`, `unavailable` and `error` each refuse the upload.
- ClamAV integration: `app/malware_scanning/clamav.py` speaks the clamd INSTREAM protocol with the standard library. No new
  dependency. Replies are parsed strictly: anything that is not `stream: OK`, `stream: <name> FOUND`, or a size-limit
  error is an error, never clean.
- Configuration: `CLAMAV_HOST` (empty means no scanner, and every upload is refused), `CLAMAV_PORT`, `CLAMAV_TIMEOUT_SECONDS`.
  A clamd daemon must run as its own service in each environment. The repository does not provide one, so production scanning
  needs that deployment.
- Order in the upload path: the size limit, then the signature check, then the scan, then storage. A file the signature check
  rejects never reaches the scanner. The scan runs on the staged bytes before anything is stored.
- Outcomes: infected returns 422 and stores nothing. The scanner's size limit returns 413. Unavailable, timed out, unreachable,
  unanswered or a malformed reply returns 503 and stores nothing. A failure to write the scan audit record also returns 503.
- Recording: every verdict is written to the independent audit trail (`document.malware_scan`) with its decision, status,
  engine, detail, size and, for infected files, the finding name. Documents store `scan_status`, `scan_engine` and `scanned_at`.
- Eligibility: AI ingestion and document review refuse any document whose `scan_status` is not `clean`, with
  `not_malware_scanned`. Retrieval also filters on `clean`. Documents created before this migration are `not_scanned` and are
  not eligible until a scan is recorded for them; no rescan job is built.
- Migration: `d2b6f8a1c4e7` adds the three document columns (downgrade removes them).
- Tests: `tests/test_malware_scanning.py` (14 tests) covers clean, large-file full scan, infected, unreachable, not configured,
  silent scanner, malformed reply, scanner size limit, malformed file before scanning, oversized file before scanning,
  unscanned documents refused for ingestion and review, clean documents past the gate, reply parsing, and that only clean
  documents are stored. Tests use `tests/clamd_fake.py`, a stand-in daemon that speaks the real protocol and reports the EICAR
  test string as a finding. It is not a malware engine, and the test environment does not bypass the scan.

### Verification

- Full backend suite on the final code (`pytest -q`, log `dfr1035-r3.log`): exit code 0; 2,303 passed, 14 skipped, 0 failed (398 s).
  The skips are the live SIBVO contract check, which is not configured here, and existing skips. The run was on the code as it
  stands now; the only later edit was this evidence record, which no test reads.
- Concurrency stability: `test_concurrent_sweeps_record_each_episode_once` passed 40 of 40 isolated runs. `test_provider_health.py` passed 16 of 16 in repeated runs.
- Migration chain, fresh `dealflow` database (port 5438): upgrade head exit 0; downgrade one step exit 0; re-upgrade exit 0; single head `d2b6f8a1c4e7`.
- Ruff, on every file this story changed: clean for new code. Findings remaining in touched files (blind `except` in the upload path, an
  import-order finding in `documents/service.py` and `models/document.py`, and a `datetime.UTC` finding) are present at HEAD on develop and were not introduced here.
- Frontend (no frontend file changed): `npm run build` exit 0, which includes the TypeScript build; `npm run lint` exit 0; `npx vitest run` exit 0, 123 tests.
- Security: `pip-audit` on the exported locked dependencies: "No known vulnerabilities found", exit 0. No dependency was added by this pass.
- Upload paths: `upload_document` is the only path that creates a document row or stores an uploaded file. The privacy export archive is written by the
  privacy executor, not from user input, so it is not a document upload. Every eligibility check that reads documents (`ingest_document`,
  `retrieve`, `review_document`) requires `scan_status = clean`. Retrieval filters on it in the database query.

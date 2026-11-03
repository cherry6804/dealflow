# E13 completion evidence: DFR1-006, DFR1-017, DFR1-050

Status of the E13 branch `feature/DFR1-E13-ai-governance-consent-security-usage` at the commit that adds this file.
It records what is implemented and tested, what is externally activated, and what is still blocked. A story is
**not** Done while any acceptance criterion is open. Detailed gap maps are in `ai-governance-and-usage-controls.md`.

## 1. Status per story

| Story | Implemented and tested | Still open (blocks Done) |
|---|---|---|
| DFR1-006 | Central gate; entitlement, switches, provider connection with health age, consent, channel policy (enablement, messaging window, quiet hours, contact do-not-disturb), approval lifecycle, actor and target checks, budget reservation, one audit record per decision | Depends on DFR1-002 (ADR-0025/26/27 still Proposed) and DFR1-005 (AI and channel plan feature keys unconfirmed). No provider probe is registered. No capability requires approval yet. |
| DFR1-017 | Ledger, reserve, settle, release, reverse, idempotency, budgets, 70/85/100 thresholds, breakdowns, reservation expiry, billable enforcement | No AI producer exists (DFR1-015). The usage reconciliation with SIBVO depends on the SIBVO contract, which is Proposed and not approved (DFR1-053). Maintenance jobs are not scheduled. |
| DFR1-050 | Table-level inventory enforced by test for all 63 tables; export with not-covered notices; deletion with dependency deferral and post-deletion verification; legal holds at request, execution and retention time; retention for documents and invitations; expiry job; log redaction of tracebacks; cross-tenant isolation | Decisions D1, D4, D7, D8, D9, D11 and D13 are open (section 3). Encryption at rest is not met (D11). Audit immutability is not verified (D8). The scheduler is not deployed (D7). |

No story is marked Done. The E13 epic remains open until DFR1-002, DFR1-005, DFR1-053 and the decisions in section 3 are resolved.

## 2. Acceptance criteria mapping

### DFR1-006 (backlog wording)

| Criterion | Evidence | Status |
|---|---|---|
| No optional AI or automation executes unless all applicable gates pass | `authorize_execution` is the only path to execution. Denials are `provider_not_connected`, `provider_unhealthy`, `provider_health_stale`, `consent_*`, `channel_*`, `contact_do_not_disturb`, `outside_messaging_window`, `quiet_hours`, `approval_*`, `budget_*`. Tests in `test_governance_execution_gate.py`, `test_consent.py`, `test_approvals_and_channel_policy.py`, `test_provider_connections.py` | Met for every capability that has an executor. No AI executor exists yet. |
| Manual CRM operations continue when AI is disabled | `test_manual_deal_creation_still_works_when_automation_is_off` and the existing deal API tests | Met |
| In-flight disable policy documented | Section 2.5 of `ai-governance-and-usage-controls.md`; per-step revalidation tests | Met |

Approval lifecycle (ADR-0029 gate 5): payload-hash binding (canonical SHA-256 of JSON), requester and approver must differ, expiry between one minute and seven days, single use recorded by `consumed_at`, row lock during check and consume, tenant isolation, permission checks (`governance.approvals.request`, `governance.approvals.decide`), audit of every transition without payload content, execution-time revalidation. Consumption happens last, so a refusal anywhere else leaves the approval unused.

Channel policy (ADR-0029 gate 7): fail closed without a policy row; enablement; IANA timezone; weekday bit mask; messaging window that may cross midnight; quiet hours; contact do-not-disturb. Writes are validated (an enabled channel needs a window; equal start and end are refused).

### DFR1-017 (backlog wording)

| Criterion | Evidence | Status |
|---|---|---|
| Provider cost separated from customer credits | Separate units in `usage_ledger.py`; breakdowns never sum units together (section 4.2 of the architecture document) | Met |
| Budgets enforced server-side | `reserve` inside the gate, before billable work; `BudgetNotConfiguredError` and `BudgetExceededError` deny | Met for the reservation path. No producer calls it yet. |
| Idempotent usage records | Repeated keys with the same quantity return the same entry; a different request under the same key is `usage_key_conflict` | Met |
| Configurable 70/85/100 alerts | Warning and critical percentages in `organization_usage_budgets` (defaults 70 and 85, validated to stay below 100). Exhaustion at 100 is a denial. `alert_delivery.py` creates in-app notifications for holders of `governance.budgets.manage`, once per event, unit, period, threshold and recipient | Met for in-app notifications. No email or external delivery is built. |

### DFR1-050 (backlog wording)

| Criterion | Evidence | Status |
|---|---|---|
| Retention jobs auditable | Each retention run and each deletion writes an audit event through `audit_privacy_event` with categories, counts and outcomes, and no personal values | Met for documents and invitations |
| Legal holds and required records handled | Holds block deletion and not export. Billing and audit records are mandatory records, never deleted by a request | Met |
| Secrets and sensitive content redacted from logs | Traceback logging removed from the document and import services (`logger.error` with the same message, no traceback). `tests/test_log_redaction.py` fails if traceback logging returns. Outbox error text is redacted. Provider secrets are never logged or returned | Met for the backend application code |

## 3. Decision records (product, legal or infrastructure owner)

Engineering did not decide any of these. Each shows the safe interim behaviour that is already in the code.

| Decision | Question | Recommended option | Alternatives | Safe interim behaviour (in code) | Owner | Stories |
|---|---|---|---|---|---|---|
| D1 | Clear free-text fields on deletion, or delete rows? | Clear only the approved personal free-text fields (scope in section 5.9 of the architecture document). Keep rows so references stay intact. | Delete rows (breaks references; needs a rule per dependent table) | Nothing cleared. These categories report `deletion_executor_not_built` | Product and legal | 050 |
| D4 | Retention period per category | Set periods per category with a legal basis | Keep indefinitely (not compliant with a stated period) | No period is set. Retention runs only for documents and invitations, and only after a period exists | Product and legal | 050, 017 |
| D7 | Scheduler and environment for `privacy_maintenance` and `usage_maintenance` | Run both as scheduled jobs in the deployment environment, owned by the platform team | Run from an operator shell; a worker process | Not scheduled. Both entry points are callable with `python -m` and do nothing until invoked | Infrastructure | 050, 017 |
| D8 | Are audit events immutable and not readable by administrators? | Enforce immutability with a database trigger and restrict reads to a named auditor role | Accept the current state as sufficient | Not verified. No immutability trigger exists and no administrator read path has been reviewed | Security and legal | 050 |
| D9 | Classification of the 19 remaining unclassified tables | Approve the proposal in section 5.8 of the architecture document | Classify case by case | Each table has a recorded disposition in `table_inventory.py` (not covered, configuration, governance record, SIBVO owned or platform record). Nothing is exported or deleted that is not already covered | Product and legal | 050 |
| D11 | Encryption at rest for stored documents | Managed key from the platform key service, applied to document storage | Application-level encryption with an environment key (already used for the email outbox) | Not met. Documents are stored in private local storage without encryption at rest. The email outbox is encrypted with an environment key | Infrastructure and security | 050 |
| D13 | Import source files | Treat as document-like: owned by the organization, deleted with the batch after the retention period | Keep indefinitely as import evidence | Not exported and not deleted | Product | 050 |

Decisions D2, D3, D5, D6, D10 and D12 were recorded earlier with their approvals (section 5.6 of the architecture document).

## 4. External activations still required

- Provider probes and accounts for each provider kind (DFR1-007, DFR1-015). A probe is registered only after its credentials and account exist. None is registered.
- An approved ADR-0025, 0026 and 0027 set (DFR1-002).
- Confirmed SIBVO plan feature keys for AI and channel capabilities (DFR1-005).
- An approved SIBVO usage contract and its reconciliation endpoint (DFR1-053).
- A deployed scheduler for `privacy_maintenance` and `usage_maintenance` (D7).
- A managed key for document encryption at rest (D11).

## 5. Verification

- Backend: full suite on a fresh PostgreSQL 17 database created for this checkpoint, port 5436. Result: 1568 passed, 7 skipped, 0 failed.
- Migrations: the whole chain applied from an empty database to head `n5e8a1c4d7b9`. Then `n5e8a1c4d7b9` and `m4d9f3a6c2e8` downgraded and upgraded again with no errors.
- Lint: `ruff check` passes on every new file. Pre-existing ordering findings in `app/db/models/__init__.py` are unchanged.
- Frontend: `vitest run` 84 of 84 passed. `npm run build` (type check and Vite build) succeeded. `oxlint` reports 0 errors and warnings in pages this branch does not change.

Not run in this checkpoint: the 5433 server was not used. An earlier background job may have run a single `CREATE DATABASE dealflow_test` statement against it, which is recorded in the checkpoint report for the owner to check.

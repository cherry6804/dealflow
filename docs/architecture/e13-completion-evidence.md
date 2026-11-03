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

- Backend: 2,107 passed, 14 skipped, 0 failed (full suite, final code, fresh database on port 5438; the run finished with no failures).
- Migrations: the chain applies from an empty database to head `n5e8a1c4d7b9` (one head, a merge point). Downgrade to `l3c8e2f5a1b7` and re-upgrade succeeded.
- Frontend: 123 of 123 tests passed (18 files). `tsc -b` exit 0. `oxlint` 0 errors (warnings only, in pages this branch does not change). `vite build` succeeded.

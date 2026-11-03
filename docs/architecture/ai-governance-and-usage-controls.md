# AI governance, usage controls and privacy (DFR1-E13)

**Status:** Partial. No E13 story is complete. ADR-0029 is **Accepted** (2026-10-30, with amendments
A to E). DFR1-002 is **not** complete (section 2.6). DFR1-053 is blocked.

**Related:** ADR-0029 (Accepted), ADR-0026 (outbox, Proposed), ADR-0027 (SIBVO entitlement, Proposed),
`sibvo-dealsflo-entitlement-contract.md`.

## 1. Authority boundaries

- SIBVO remains the authority for identity, organizations, memberships, subscriptions, plans,
  entitlements, seats and billing. Dealsflo stores no subscription or invoice. It reads SIBVO's
  attested access snapshot and fails closed when that snapshot cannot be verified.
- Dealsflo owns capability switches, retention policies, legal holds, privacy request records, the
  usage ledger, organization budgets, and the audit records of those changes.

## 2. Capability policy and execution gate (DFR1-006)

Status: **Partial. Not Done.** The gate is centralized and fails closed. Only one optional capability can
run today: deal-created automation for organizations that have turned it on and whose plan includes
`workflow_automation`. Every other gate is either verified or is blocked by a dependency that does not
exist yet (section 2.7). DFR1-006 depends on DFR1-002 (architecture approval, still To Do) and DFR1-005
(SIBVO contract, still To Do in the backlog), so it cannot be closed by code alone.

### 2.1 Catalogue

`app/governance/capabilities.py` is code. Every capability is disabled by default. A capability can be
executable only when it declares a SIBVO plan feature (`entitlement_feature`).

| Key | Parent | SIBVO feature | Provider gate | Consent gate | Approval gate |
|---|---|---|---|---|---|
| `ai.master`, `automation.master` | none | none (masters are not executed) | | | |
| `ai.assistant`, `ai.agents`, `ai.workflow_execution`, `ai.predictions`, `ai.content_generation`, `ai.document_processing` | `ai.master` | **none confirmed** (denied as `entitlement_not_defined`) | yes | | |
| `ai.voice` | `ai.master` | **none confirmed** | yes | yes | |
| `automation.deal_created_rules` | `automation.master` | `workflow_automation` | | | |
| `channels.whatsapp`, `channels.email`, `channels.sms`, `channels.voice` | none | **none confirmed** | yes | yes | |

Plan feature keys for AI and channels are not in the SIBVO access snapshot contract. Until DFR1-005 confirms
them, those capabilities cannot run. This is deliberate. Dealsflo does not invent feature keys.

### 2.2 Policy evaluation (`app/governance/policy.py`)

`evaluate_capability` decides whether a capability is allowed for an organization. Gates run in this order,
and the first failing gate gives the reason:

1. Unknown capability: `unknown_capability`.
2. Plan feature, for capabilities that declare one, read from SIBVO's attested session snapshot
   (`app/governance/entitlement.py`, fail closed): `entitlement_unverified`, `wrong_organization`,
   `product_membership_inactive`, `trial_expired`, `subscription_not_active`, `entitlement_missing`,
   `entitlement_disabled`.
3. Organization switches, from the top of the chain: `master_disabled`, `capability_disabled`.
4. Executable capability with no confirmed plan feature: `entitlement_not_defined`.
5. Approval required by the catalogue: `approval_not_available`. No approval model exists (DFR1-025).
6. Provider required: `provider_not_connected`. No provider connection model exists.
7. Consent required: `consent_not_configured`. No consent model exists.
8. Otherwise `allowed`.

The policy is also used to show capability state in the settings screen. That display call writes no audit
record, because it does not authorize anything.

### 2.3 The execution gate (`app/governance/execution_gate.py`)

Every governed execution calls `authorize_execution`. It is the only path from a policy decision to
an execution, and it is used by every caller, including internal ones. The checks, in order:

1. Actor present. No actor (background or internal call without a user): `actor_required`.
2. Session belongs to the organization: `wrong_organization`.
3. Active membership of the actor in the organization: `membership_inactive`. Revoked access is refused here.
4. Target resource belongs to the organization: `target_organization_mismatch`.
5. Target resource is published and active: `resource_not_active`.
6. Policy (section 2.2).
7. Billable work: `budget_gate_not_available`. Billable work is refused until DFR1-017 provides budgets.
8. Actor holds the required permission in the organization, through the existing permission lookup:
   `actor_not_authorized`.

Every decision writes one audit record in the caller's transaction, allowed or denied: action
`capability.execution`, decision, permission key, resource type and ID, correlation ID, and metadata with
the capability, reason code, stage, policy version and billable flag. The record holds no payload and no
personal data beyond the actor's ID.

### 2.4 Enforcement points

- **Deal-created automation** (`execute_deal_created_automations`, called from `POST /api/v1/deals`):
  - Initial gate before any rule is read. A denial returns no executions and leaves the deal in place, so
    manual CRM work continues.
  - Revalidation before each rule after the first (`stage = revalidation`). Each rule's status is read from
    the database again first. A turned-off switch, a lost entitlement, or a paused rule stops the remaining
    rules. Rules that already ran are kept.
  - The required permission is `deals.create`.
- No other execution path exists in this repository. Scheduled runs, workflow runs, agents, AI calls and
  channel sends are not built, so there is nothing else to govern yet.

### 2.5 In-flight policy

- Revalidation happens before each rule. It does not happen between the actions of one rule. An action
  that has started completes. Deal-created actions are internal follow-ups and notifications, and they
  run inside the same request, so no external work is in flight when a switch changes.
- A disabled master or capability, a lost entitlement, or a paused rule takes effect at the next check.
  Tests show each case stops the remaining rules.
- Cancel-or-complete for runs that outlast a request belongs to the agent runtime (DFR1-019), which is not built.

### 2.6 Existing organizations

Unchanged from the migration decision. Every existing organization starts with every capability disabled.
Migration `f3a7b9c1d2e4` enabled automation for every organization. Corrective migration `i7f2c9d4e1a8` removes
those unevidenced rows and grants nothing. Existing rules are preserved, not executed, and execution history is
not read or changed. Enablement and revocation are recorded with the actor, previous and new state, policy version,
source and correlation ID.

### 2.7 Acceptance-criteria gap map (DFR1-006)

| Criterion | Evidence | Status |
|---|---|---|
| Disabled by default, including existing organizations | `default_enabled` is False for every capability; migration `i7f2c9d4e1a8`; `test_a_new_organization_never_runs_deal_automation`; `tests/test_migration_automation_default.py` | Verified |
| Explicit organization opt-in and revocation | `test_revoking_opt_in_stops_the_next_run_and_is_audited`; enablement audited by `set_capability_enabled` | Verified |
| Product entitlement and subscription eligibility | `test_an_expired_trial_denies_even_when_switches_are_on`, `test_a_plan_without_the_feature_denies`, `test_a_disabled_plan_feature_denies`, `test_revoked_product_access_denies`, `test_an_unverified_snapshot_fails_closed`, `test_a_session_for_another_organization_is_refused` | Verified for `workflow_automation`. AI and channel plan keys unconfirmed (DFR1-005) |
| Consent and channel eligibility | `test_a_consent_requirement_denies_while_no_consent_model_exists`; channels deny | Fails closed. Consent model not built |
| Provider health and configuration | `test_a_provider_requirement_denies_while_no_provider_connection_exists`; AI and channel capabilities deny | Fails closed. Provider connection model not built (DFR1-003, DFR1-004, DFR1-015) |
| Resource publication and activation | `test_a_draft_or_paused_rule_never_executes`; `test_pausing_a_rule_mid_run_stops_it...`; per-rule revalidation | Verified for deal-created rules. Agent and workflow publication not built (DFR1-019, DFR1-023) |
| Actor permission and target-resource permission | `test_an_actor_without_the_permission_for_the_action_is_refused`; `test_a_target_from_another_organization_is_refused`; `test_an_inactive_membership_denies...`; `test_another_organizations_deal_cannot_be_executed` | Verified at organization scope. **Record-level permission** (for example, owner-only deals) is not defined by the policy sheet and is not implemented |
| Usage budgets and limits | `test_billable_work_is_denied_until_the_budget_gate_exists`. No rate, concurrency or step limits | Billable work denied. Budgets, rate and concurrency not built (DFR1-017) |
| Required approvals | `test_a_capability_that_needs_approval_denies_because_no_approval_exists` | Fails closed. Approval model not built (DFR1-025) |
| In-flight revalidation and safe stopping | `test_turning_automation_off_mid_run_stops_the_remaining_rules`; `test_each_later_step_is_revalidated_and_audited` | Verified at rule granularity (section 2.5) |
| Background execution authorization | `test_an_execution_without_an_actor_is_refused`. No scheduler or background executor exists | Verified for the one path that exists. Any future background executor must call `authorize_execution` |
| Fail-closed behaviour | Unknown capability, unverified snapshot, missing or disabled plan feature, undefined feature, no actor, no membership | Verified |
| Complete audit of allowed and denied execution | `test_allowed_and_denied_decisions_are_both_audited_with_the_reason` | Verified. Audit is in the caller's transaction, so a rolled-back operation leaves no decision record |
| Manual CRM works when AI is disabled | `test_manual_deal_creation_still_works_when_automation_is_off`; existing deal API tests | Verified |

### 2.8 Blockers and external dependencies

1. **DFR1-002**: ADR-0025, ADR-0026 and ADR-0027 are still Proposed. The story stays To Do.
2. **DFR1-005**: SIBVO plan feature keys for AI and channel capabilities are unconfirmed. Dealsflo will not invent them.
3. **Provider connection model** (DFR1-003, DFR1-004, DFR1-015): needed for gate 6.
4. **Consent and channel policy model** (DFR1-034 and channel stories): needed for gate 7.
5. **Approval model** (DFR1-025, which depends on DFR1-023): needed for gate 5.
6. **Usage budgets and limits** (DFR1-017): needed before any billable execution.
7. **Record-level permission scope**: not defined in the policy sheet. Product decision needed.

### 2.9 ADR-0029 and DFR1-002

- **ADR-0029: Accepted** on 2026-10-30, with amendments A to E. Section 2.7 records the enforcement status of each gate.
- **DFR1-002: not complete.** ADR-0025, ADR-0026 and ADR-0027 are still Proposed.
- **DFR1-006 cannot be marked complete** while DFR1-002 is open and blockers 2 to 7 in section 2.8 remain.

## 3. Settings API and permissions

| Method and path | Permission | Notes |
|---|---|---|
| `GET /api/v1/governance/access` | authenticated tenant member | Which governance permissions the caller holds. Shapes the UI only. |
| `GET /api/v1/governance/capabilities` | `governance.capabilities.read` | Stored switch plus effective decision. |
| `PATCH /api/v1/governance/capabilities/{key}` | `governance.capabilities.manage` (owner-only) | Requires `confirm: true`. Audited. |
| `GET /api/v1/governance/usage/budgets` | `governance.usage.read` | Current UTC month. |
| `PUT /api/v1/governance/usage/budgets/{unit}` | `governance.budgets.manage` (owner-only) | Requires `confirm: true`. Audited with before and after. |
| `GET /api/v1/governance/privacy/categories` | `governance.privacy.read` | Classification register, including `producer_exists`. |
| `GET /api/v1/governance/privacy/retention` | `governance.privacy.read` | Current retention per category. |
| `PUT /api/v1/governance/privacy/retention/{category}` | `governance.privacy.manage` (owner-only) | Versioned. Audited. |
| `GET /api/v1/governance/privacy/legal-holds` | `governance.privacy.read` | Organization-scoped. |
| `POST /api/v1/governance/privacy/legal-holds` | `governance.privacy.manage` (owner-only) | Reason required. Audited. |
| `POST /api/v1/governance/privacy/legal-holds/{id}/release` | `governance.privacy.manage` (owner-only) | Audited. |
| `GET /api/v1/governance/privacy/requests` | `governance.privacy.read` | Also expires ready exports past their window. |
| `POST /api/v1/governance/privacy/requests` | `governance.privacy.manage` (owner-only) | Export or deletion. Requires `confirm: true`. |
| `POST /api/v1/governance/privacy/requests/{id}/cancel` | `governance.privacy.manage` (owner-only) | Audited. |

Every organization comes from the server-side tenant context. A request for an organization the caller
does not belong to is refused with 403. Owner-only keys are in `OWNER_ONLY_PERMISSION_KEYS`.

## 4. AI usage ledger and budgets (DFR1-017)

### 4.1 Schema

- `ai_usage_events`: unique on `(organization_id, idempotency_key)`. Unit, reserved quantity, actual
  quantity, status (`reserved`, `recorded`, `released`, `reversed`), provider, model, task type, user,
  agent, workflow, execution, correlation ID, currency, occurred-at.
- `organization_usage_budgets`: unique on `(organization_id, unit, period_start)`. Limit, reserved,
  consumed, and the highest alert threshold already announced.

### 4.2 Units

`tokens_input`, `tokens_output`, `audio_ms`, `images`, `document_pages`, `provider_cost_minor`,
`customer_credits`. Each is an integer in its own unit. Provider cost is in minor currency units.
Provider cost and customer credits never share a budget.

### 4.3 Lifecycle

| Operation | Budget effect | Repeat call |
|---|---|---|
| `reserve` | `reserved += q`. Refused when no budget exists (`BudgetNotConfiguredError`) or `q > remaining` (`BudgetExceededError`). | Returns the existing entry. |
| `settle` | `reserved -= reserved_q`; `consumed += actual`. Actual above the reservation is recorded as overrun. | Returns the recorded entry. |
| `release` | `reserved -= reserved_q`. Used for failed or cancelled work. | Returns the released entry. |
| `record` | `consumed += q`, even above the limit. Used for usage reported after the fact. | Returns the existing entry; no second count. |
| `reverse` | `consumed -= quantity`. The row is kept with status `reversed`. | Returns the reversed entry. |

Budget rows are locked (`SELECT ... FOR UPDATE`) before any change. A concurrent test runs two
reservations against one budget; exactly one is refused.

### 4.4 Threshold alerts: delivery status

`70`, `85` and `100` percent thresholds enqueue `ai.usage.threshold_reached` to the transactional outbox.
One event is enqueued per period at the highest threshold newly crossed.

**Delivery.** The outbox worker registers `deliver_usage_threshold_alert`
(`app/governance/alert_delivery.py`). It creates an **in-app notification** for each active member whose
role grants `governance.budgets.manage`. It sends no email, SMS, or other external message. Notifications
are keyed by event, recipient and threshold, so a retry does not duplicate them. An administrator who has
turned off notifications for this type is skipped, which is their preference.

**Failure.** If no notification can be created (no administrator, or every administrator has notifications
off), the handler raises. The event is retried and then dead-lettered, so the failure stays visible. The
event is marked `delivered` only after the handler returns without error.

**The worker must run.** Delivery happens only in the outbox worker process (`python -m app.outbox.worker`).
The repository defines no deployment of that worker, so until an operator runs it, an alert remains pending.
An enqueued alert is not a delivered alert.

**Tested.** `tests/test_usage_alert_delivery.py`: delivery to the administrator and `delivered` status;
no notification for a user without the permission; idempotent redelivery; and dead-lettering when no
administrator exists.

### 4.5 Verification (what the tests show)

| Property | Evidence |
|---|---|
| Idempotency under duplicate events | Repeated reserve, settle, release, record and reverse calls change nothing. `test_a_delayed_provider_report_delivered_twice_is_counted_once`. |
| Concurrent reservations | `test_concurrent_reservations_cannot_exceed_the_limit` (two threads, PostgreSQL row lock). |
| Reserve / settle / release / reverse | Lifecycle tests, including partial settlement (60 reserved, 25 used, 35 returned). |
| Failed and partially completed executions | Release on failure; settlement below the reservation returns the difference; settlement above it is recorded as overrun. |
| Alert deduplication | Each of 70, 85 and 100 fires once; a single change crossing several thresholds announces only the highest. |
| Period boundaries and timezone | Calendar months in UTC. `test_period_is_decided_in_utc_not_local_time`. |
| Provider cost vs customer credits | Separate units and budgets (`test_units_are_budgeted_independently`). |
| No double counting during retries | Repeated settle, release and record calls are no-ops. |
| Tenant isolation | Same idempotency key in two organizations creates two entries; cross-tenant budget read and change refused. |

### 4.6 Missing AI gateway producers

No producer exists in the codebase, so no real usage is recorded. Every production usage path is
missing:

- AI gateway (DFR1-015): text, embedding, speech and multimodal calls. It must emit reserve, settle or
  release for each billable call, with provider, model, tokens, audio duration, image count, document
  pages and provider cost, and it must reuse the call's idempotency key on retry.
- Agent runtime (DFR1-019), workflow runtime, voice (DFR1-027, DFR1-028): all bill through the gateway.
- SIBVO usage summaries and reconciliation (DFR1-053): blocked on the approved contract.

No usage data has been fabricated.

## 5. Privacy, retention and requests (DFR1-050)

Status: **Partial.** Processing is real for two categories in each direction and is covered by tests.
Most organization data is not yet exported or deleted, and that is recorded per request rather than
hidden. The acceptance criteria also depend on voice (DFR1-027, DFR1-028), documents (DFR1-035) and
organization AI settings (DFR1-036), which are not complete.

### 5.1 Operations

| Operation | Executes? | Detail |
|---|---|---|
| Data classification | Yes (static register) | `app/governance/data_classification.py`. Each category has `producer_exists` and `organization_owned`. |
| Retention periods | Stored; enforced for two categories | Versioned days per category. Enforced for `documents.files` and `team.invitations` only (section 5.3). Periods are configured by the organization. None is set by default. |
| Legal holds | Yes, at three points | Checked when the request is created, again when the deletion runs, and again on every retention run. A hold in place is never bypassed. Recorded and audited. |
| Deletion eligibility | Yes | Reason codes: `not_customer_deletable`, `legal_hold_active`, `no_producer_yet`, `category_unknown`, `not_organization_owned`. |
| Deletion request processing | Yes, in the background | Outbox handler. Retried on failure. A repeat run is a no-op. Storage removal is idempotent. |
| Export request processing | Yes, in the background | Outbox handler. One ZIP artifact per request at a fixed key, so a retry replaces it and never orphans an object. |
| Export download | Yes | `GET /governance/privacy/requests/{id}/export`. Requires `governance.privacy.manage`, is organization-scoped, audited (`privacy.export.downloaded`), and sent with `Cache-Control: no-store`. `409` before the artifact exists; `410` after expiry, and the stored object is removed. |
| Export expiry | Yes, on access and by a scheduled job | `expire_request_export` removes the object. `app.governance.privacy_maintenance` expires due exports. **Nothing schedules it in this repository.** |
| Cancellation | Yes | Audited. Removes the stored object of a ready export. |
| External provider deletion | **Not applicable today** | No external provider holds organization data in this repository. Stored documents are in private local storage. Email outbox rows are platform data (see 5.2). |

### 5.2 Category matrix

Each row is what the code does today. Anything not listed as done is **not** claimed.

| Category | Export | Deletion | Retention | Why |
|---|---|---|---|---|
| `crm.contacts` | Yes | Identity fields anonymized (`anonymized_partial`) | Not enforced | Linked leads, profiles, requirements, deals and follow-ups are not changed. Whether an old contact may be anonymized while deals reference it is a product and legal decision. |
| `crm.leads` | Yes | Not processed (`deletion_executor_not_built`) | Not enforced | Free-text notes. Decision: anonymize or delete, and what happens to dependent follow-ups. |
| `crm.follow_ups` | Yes | Not processed | Not enforced | Free-text titles and descriptions. Same decision as leads. |
| `crm.customer_profiles`, `crm.requirements`, `crm.deals` | Not built (`no_export_producer_yet`) | Not processed | Not enforced | No exporter or executor yet. Deals hold financial and commission records that may have a retention obligation. |
| `documents.files` | Yes, with the stored files. All or nothing: a missing object, a checksum mismatch, or a total over `PRIVACY_EXPORT_MAX_BYTES` excludes the whole category | Stored object, then metadata row (`deleted`) | Enforced by age (`created_at`) | None. |
| `team.invitations` | Yes. The token hash is never exported | Email replaced by a non-deliverable placeholder; pending invitations revoked (`anonymized`) | Enforced by age | None. |
| `messaging.email_outbox` | Excluded (`not_organization_owned`) | Excluded | Not applicable | Platform authentication and invitation mail carries no organization ID. It cannot be exported or deleted for one organization. Platform retention is a separate decision. |
| `messaging.conversations`, `voice.call_records`, `voice.transcripts`, `ai.prompts_and_responses`, `ai.embeddings`, `ai.execution_traces` | No producer (`no_producer_yet`) | No producer | Not applicable | Channel, voice and AI execution are not built (DFR1-015, 019, 027, 028). Blocked, not covered. |
| `ai.usage` | Not built | Not deleted | Not applicable | Financial record. Retained by design. |
| `billing.records`, `audit.events` | Not built | Not deleted | Not applicable | Financial and security records. Never deleted by a customer request. Whether they must be exported on request is a decision. |
| `security.credentials` | Never exported | Never deleted by a customer request | Not applicable | Secret references. No provider connection exists yet. |

### 5.3 Retention enforcement

`app.governance.privacy_execution.enforce_retention` applies the organization's period to each enforced
category, using the same executors as a deletion request. Each category is checked for legal holds
first. A skipped category is audited (`privacy.retention.skipped`), and an enforced run is audited
(`privacy.retention.enforced`) with its cutoff and count. Retention is per organization and never
crosses tenants. A repeat run deletes nothing new.

A category with a period but no enforcer is reported as `not_enforced`. It is never reported as applied.

### 5.4 Scheduled work

`python -m app.governance.privacy_maintenance` runs export expiry and retention for every organization
with a period. Each export and each organization runs in its own transaction. A failure is rolled back,
counted, and logged with the exception type only. The run continues, and it exits non-zero on any failure.

Scheduling is not configured. Until a scheduler runs this command, retention does not run, and an expired
export's object is removed only when it is downloaded or its request is cancelled.

### 5.5 Settings

| Setting | Default | Meaning |
|---|---|---|
| `PRIVACY_EXPORT_TTL_DAYS` | 7 (1–90) | Download window for a generated export. An operating choice, not a legal period. |
| `PRIVACY_EXPORT_MAX_BYTES` | 50 MiB | Total stored-document bytes one export may include. Above this, documents are excluded, not truncated. |

No legal retention period is set in code. Periods come only from each organization's retention policy.

### 5.6 Decisions still needed (product or legal)

1. Anonymize or delete leads, follow-ups, customer profiles, requirements and deals on deletion, and how to treat records that other records depend on.
2. Whether contacts may be retention-enforced while deals or leads reference them.
3. Whether billing and audit records must be included in an export on request.
4. Whether a platform-level retention period applies to the email outbox, which sits outside any organization.
5. Whether a separate record of deleted categories must be kept. Currently only the audit event and the request's execution record remain.

### 5.7 Verification

- `tests/test_privacy_execution.py`: 32 tests. They cover export coverage and ZIP contents; all-or-nothing document export (missing object, checksum mismatch, size limit); exclusions; invitation token omission; leads and follow-ups export; deletion; holds at request and execution time; storage-failure rollback and retry; idempotency; download access and expiry; cross-tenant refusal; retention per organization and per category; legal-hold skip; the expiry job; cancellation; failure isolation between organizations; and absence of personal data from logs.
- Migrations: `j1a6e3c9b4d2` verified upgrade, downgrade and upgrade on a fresh PostgreSQL database that ran the full chain from empty.

## 6. Frontend

Route `/settings/governance`. Three sections, each shown only when the server reports read access. Manage
controls appear only when the server reports manage access, and the server still enforces every request.
Confirmation is required for every consequential change.

The page lists, for each request, what was exported or deleted and what was not. The request form labels deletion as deletion, and every incomplete category is shown with its reason.
Tests: `governanceLabels.test.ts` and `pages/GovernancePage.test.tsx`.

**Not verified in a browser.** The page needs the migrations applied to the shared dev database and a
backend restart. Neither was done.

## 7. Migrations

| Revision | Adds or changes |
|---|---|
| `f3a7b9c1d2e4` | Creates `organization_capability_settings`; wrote blanket automation rows (**superseded** by `i7f2c9d4e1a8`); capability permissions. Downgrade refuses to drop the table after people have changed switches. |
| `g4b8c0d2e5f6` | Creates `ai_usage_events` and `organization_usage_budgets`; usage permissions |
| `h5c9d1e3f6a7` | Creates the privacy tables; privacy permissions |
| `i7f2c9d4e1a8` | Adds `source`; removes the blanket automation rows. Grants nothing. Downgrade refuses after people have changed switches, and never re-enables anything. |
| `j1a6e3c9b4d2` | Adds `attempt_count`, `processed_at` and `execution` to `privacy_data_requests`. Existing rows keep their status and get an empty execution record. Downgrade drops only these three columns. |

Verified in a disposable schema inside `dealflow_test`: `upgrade head`, `downgrade base` (81 revisions),
`upgrade head`, with exit code 0 at each step. `tests/test_migration_automation_default.py` (10 tests)
covers: active rules, draft rules, disabled rules, no rules, historical executions, organizations created
after migration, explicit opt-in after migration with its actor, no change to rules, executions or
notifications, rollback and reapplication without re-enabling, and refusal to roll back after people have
changed switches.

## 8. Security and tenant isolation

Tested: cross-tenant policy reads and writes, legal holds scoped per organization, privacy requests not
visible or changeable across organizations, idempotency keys scoped per organization, cross-tenant budget
reads and changes refused, read-only users refused on manage endpoints, unknown categories and
capabilities refused, concurrent budget reservations, and the migration rules above.

Entitlement enforcement tests (`tests/test_governance_entitlement.py`, 18 tests): each failed gate
(missing or disabled entitlement, expired trial, subscription not active, suspended product membership,
revoked access, wrong organization, SIBVO unavailable, malformed entitlement response), organization
switches disabled, child capability disabled, inactive rule, an unauthorized actor, and a denied
automation never blocking manual deal creation.

**Not tested, because the feature does not exist:** consent and opt-out bypass, approval bypass and stale
approvals, replayed webhooks, outbox retry policy bypass by AI consumers, export data leakage, and
legal-hold bypass by external deletion.

## 9. Known limitations

- Consent, channel policy, approvals, provider health, and the AI gateway are not built. Channel and voice
  capabilities deny until they exist.
- No production usage is recorded (section 4.6).
- Threshold alerts are delivered only by a running outbox worker (section 4.4).
- Retention is enforced for documents and team invitations only (section 5.3). Contacts, leads and other categories are reported as not enforced. Export and deletion are built for the categories in section 5.2 only.
- The entitlement snapshot is bounded by the E12 revalidation interval (section 2.2).
- Transactional account email is outside the capability model (section 11, entry 7).
- Governance audit events are written to `audit_events` (event types `governance` and `privacy`). No UI
  for browsing them exists.

## 10. Dependency and blocker matrix

| Story | Status | Dependency | Owner | Remaining |
|---|---|---|---|---|
| DFR1-002 | **Not complete** | ADR-0025, ADR-0026, ADR-0027 still Proposed; diagrams and ownership map not recorded | Engineering and product | Approve the remaining ADRs and record the diagrams and ownership map |
| DFR1-006 | Partial | DFR1-002 (To Do: ADR-0025/26/27 Proposed), DFR1-005 (To Do in the backlog; the entitlement check in code exists) | Engineering and product | Provider connection and health (DFR1-003, 004, 015); consent and channel policy; approval model (DFR1-025); budget, rate and concurrency gates (DFR1-017); record-level permission scope; cancel-or-complete for runs that outlast a request (DFR1-019). Section 2.8 lists each blocker |
| DFR1-017 | Partial | DFR1-015 (AI gateway), DFR1-005 (done) | AI platform (E06) | Gateway producers; running the outbox worker in production; dashboard breakdowns; SIBVO reconciliation (DFR1-053) |
| DFR1-050 | Partial | DFR1-028, DFR1-035, DFR1-036 | Voice, documents, settings | Export and deletion for the CRM categories (leads, follow-ups, customer profiles, requirements, deals) and anonymization of linked records; export of conversations, calls, transcripts and AI data (no producers); a product decision on retention for contacts; scheduling of `privacy_maintenance`; decisions in section 5.6 |
| DFR1-053 | Blocked | DFR1-017, DFR1-036, approved SIBVO ingestion contract | SIBVO and Dealsflo | Ingestion, reconciliation, lifecycle tests |

## 11. Enforcement matrix (every execution entry point)

Columns: **Policy** = governance check location. **Entitlement** = SIBVO entitlement verified in this path.
**Enabled** = organization master and capability switches. **Resource** = rule or resource activation.
**Actor** = authorization of the initiating user. **Consent** = consent and channel policy. **Budget** =
usage budget. **Approval** = human approval. **Failure** = behaviour on denial or error.

| # | Entry point | Exists today? | Policy | Entitlement | Enabled | Resource | Actor | Consent | Budget | Approval | Failure |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Deal-created automation** (`execute_deal_created_automations`, called from `POST /deals`) | Yes | Enforced: `automation.deal_created_rules` | **Enforced:** SIBVO `workflow_automation`, attested snapshot, fail closed | Enforced (master and child) | Enforced: rule status ACTIVE | Deal creation requires `deals.create` (API). Automation needs an attested user context. | N/A: actions are internal (follow-up, in-app notification) | N/A: nothing is billable | N/A: none configured | Denial returns no executions, and the deal is still created. A per-rule error is recorded as a failed execution inside a savepoint. |
| 2 | **API-triggered execution** | Only via #1 | Same as #1 | Same as #1 | Same as #1 | — | — | — | — | — | — |
| 2a | Rule activation (`POST /automation-rules/{id}/activate`) | Yes | Not applicable: changes status, executes nothing | — | Not checked. A rule can be activated while automation is off and simply will not run. | Changes rule status | Requires the automation permission | — | — | — |
| 3 | **AI gateway** | **No** (DFR1-015) | Not implemented | — | — | — | — | — | — | — | — |
| 4 | **Agent runtime** | **No** (DFR1-019) | Not implemented | — | — | — | — | — | — | — | — |
| 5 | **Workflow runtime** | **No executor.** `FOLLOW_UP_OVERDUE` is named in a comment only | Not implemented | — | — | — | — | — | — | — | — |
| 6 | **Outbox consumers** | Worker exists. **Usage alert handler registered** (in-app notifications). No other governed handler. | Alert handler sends in-app notifications only. Any future handler that performs optional work must call the policy engine. | — | — | — | — | — | — | — | Unhandled events dead-letter. Alert with no recipient dead-letters. |
| 7 | **Communication sending: transactional email** (email outbox worker: verification, password reset, team invitation) | Yes | **Exempt** under ADR-0029 Amendment C. Remains subject to authentication, tenant authorization, rate limiting, audit, delivery security and legal requirements. | Not applicable | Not applicable | Not applicable | Triggered by account actions | Not applicable (essential account messages) | Not applicable | Not applicable | Retries and dead-letter in the email outbox |
| 7a | Communication sending: marketing, promotional, AI-generated or automated customer messages; WhatsApp, SMS, outbound email campaigns, voice calls | **No** (channel gateway not built) | Not implemented; channel capabilities deny | — | — | — | — | Not implemented | — | — | — |
| 8 | **Voice operations** (inbound and outbound calls, transcription) | **No** (DFR1-027, DFR1-028) | Not implemented | — | — | — | — | — | — | — | — |
| 9 | **Background jobs** | Outbox worker; email worker; billing webhook reconciliation (writes reconciliation records) | Not applicable to optional execution. | — | — | — | — | — | — | — | Retries and dead-letter, existing behaviour |
| 10 | **Scheduled execution** | **No scheduler in the repository.** `infrastructure/` contains only a README. | Not implemented | — | — | — | — | — | — | — | — |

**Conclusion.** Governance is enforced at one execution entry point (#1), including SIBVO entitlement. It is
not universal. Entries 3, 4, 5, 7a, 8 and 10 do not exist, and must enforce the complete gate set when built.
Entry 6 has one governed handler, which sends in-app notifications only. Entry 7 is an exemption limited by
ADR-0029 Amendment C.

## 12. Story status

| Story | Status | Reason |
|---|---|---|
| DFR1-006 | **Partial** | Centralized execution gate (actor, membership, target, policy, billing, permission) with an audit record for every decision. One governed execution path (deal-created automation), revalidated before each rule. AI and channel capabilities fail closed (no confirmed plan feature, no provider or consent model, no approval model). DFR1-002 and DFR1-005 are open. |
| DFR1-017 | **Partial** | Ledger and budgets verified by tests. Alert delivery to administrators implemented (in-app, outbox worker). No production producer. |
| DFR1-050 | **Partial** | Background export (contacts, leads, follow-ups, invitations, documents with files), deletion (documents, invitations fully; contacts anonymized), retention for documents and invitations, expiry and cancellation with object removal, audited download, and failure-isolated maintenance. Not built: exporters and executors for most CRM categories, conversations, calls, transcripts and AI data; scheduling; provider deletion (none exists). Section 5 lists each category. |
| DFR1-053 | **Blocked** | Dependencies not delivered. |

No E13 story is complete. E13 is not Done.

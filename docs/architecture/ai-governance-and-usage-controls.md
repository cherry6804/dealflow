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
6. Provider required: a verified, fresh connection of the matching kind must exist. Denials are `provider_not_connected`, `provider_unhealthy` and `provider_health_stale`. No provider probe is registered yet, so none can pass.
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

### 2.4 Enforcement points and entry-point inventory

Inventory as of this checkpoint, from a search of API routes, services, outbox handlers, jobs and
external send paths.

| Entry point | Kind | Governed by the execution gate? | Why |
|---|---|---|---|
| Deal-created automation (`POST /api/v1/deals` → `execute_deal_created_automations`) | Automation execution | **Yes**: initial check, a check before every action, and a check before each later rule | The only path that creates an `AutomationExecution` or runs an action (`_execute_action`). |
| Automation rule create, update, list, get, activate, disable (`/api/v1/automation-rules`) | Configuration | No | These change rule configuration or status. They execute nothing. A rule can be activated while automation is off and will not run. |
| Deal creation notification to the deal owner (`_notify_deal_owner`) | In-app CRM notification | No | Standard manual CRM behaviour, not an optional AI or automation capability. |
| Usage threshold alert (outbox handler `deliver_usage_threshold_alert`) | Governance notification | No | An in-app administrator notice about the budget, not an AI execution. |
| Privacy export and deletion (outbox handler, `privacy_maintenance`) | Compliance processing | No | Required by data-protection obligations, not an optional capability. Documented in section 5. |
| Email outbox worker (verification, password reset, necessary account invitations) | Transactional email | No, by Amendment C | The narrow exemption for essential account communications. |
| AI model, voice, channel or provider calls | External execution | **Not built** | No AI SDK or provider integration exists in the repository. Nothing can call one. |
| Scheduled automation run | Background | **Not built** | No scheduler runs automation. Any future background executor must call `authorize_execution`. |

Any new execution path must be added to this table and must call `authorize_execution` before it does work.

### 2.5 In-flight policy

- The gate runs before the first action of each rule, before every later action, and before each later rule.
  A switch turned off, a lost entitlement, a paused rule, or a lost membership stops the remaining actions and
  rules. Actions already run are kept. Refused actions are recorded as `SKIPPED` with a generic reason, and the
  run is marked `SKIPPED` or `PARTIAL`.
- **Granularity limit.** The boundary is one call to `_execute_action`. The check runs immediately before each call.
  Inside one action, the work is a database write in the same transaction, so there is no separate step to revalidate.
  Each action is internal (a follow-up or an in-app notification), so no external work is ever in flight when a
  switch changes. Revalidation of a long-running external action needs the agent runtime (DFR1-019), which is not built.
- A disabled master or capability, a lost entitlement, or a paused rule takes effect at the next check. Tests show each
  case stops the remaining actions and rules.
- Cancel-or-complete for runs that outlast a request belongs to the agent runtime (DFR1-019), which is not built.

### 2.5a Null and empty plan feature keys

A missing, null or empty `entitlement_feature` is treated as undefined. Such a capability is denied as
`entitlement_not_defined`, after the switch chain. A snapshot entry whose `feature_key` is null, empty or absent
never matches a feature, so it cannot grant access. Tests cover null, empty and absent keys
(`test_a_null_or_empty_feature_key_can_never_grant_access`).

### 2.5b Record-level permission: decision required

The policy sheet says the actor must have permission "for target record/action". This checkpoint checks the
organization-level permission (`deals.create`) and the organization of the target. It does not check whether the actor
may act on one specific deal, such as an owner-only rule. That needs a product decision on the record-level scope,
for example owner, team or organization. Until it is decided, no record-level rule is invented and none is enforced.

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
| Consent and channel eligibility | Append-only consent records per contact, channel and purpose (`contact_consent_records`, migration `l3c8e2f5a1b7`). Grant, revoke and expiry. Versioned policy (version 1). Checked in the central gate on every execution: `consent_missing`, `consent_revoked`, `consent_expired`, `consent_channel_mismatch`. Revocation takes effect on the next execution. Tests: `tests/test_consent.py` (21). Channel policy is checked after consent: enablement, messaging window, quiet hours and contact do-not-disturb (`channel_policy.py`; tests in `tests/test_approvals_and_channel_policy.py`). Templates are not built. | Consent gate and channel policy verified. Production channel capabilities still deny: no confirmed plan feature and no provider connection |
| Provider connection and health | `tests/test_provider_connections.py` (18 tests): secret boundary (only the environment variable name is stored, the value is never returned or audited), verification outcomes, health age, secret removal, disabled connections, tenant isolation, permissions, and gate order before consent | Registry and gate verified. No provider probe is registered, so no real provider can be verified. Provider adapters and their external accounts are not built (DFR1-007, DFR1-015) |
| Resource publication and activation | `test_a_draft_or_paused_rule_never_executes`; `test_pausing_a_rule_mid_run_stops_it...`; per-rule revalidation | Verified for deal-created rules. Agent and workflow publication not built (DFR1-019, DFR1-023) |
| Actor permission and target-resource permission | `test_an_actor_without_the_permission_for_the_action_is_refused`; `test_a_target_from_another_organization_is_refused`; `test_an_inactive_membership_denies...`; `test_another_organizations_deal_cannot_be_executed` | Verified at organization scope. **Record-level permission** (for example, owner-only deals) is not defined by the policy sheet and is not implemented |
| Usage budgets and limits | `test_billable_work_is_denied_until_the_budget_gate_exists`. No rate, concurrency or step limits | Billable work denied. Budgets, rate and concurrency not built (DFR1-017) |
| Required approvals | `tests/test_approvals_and_channel_policy.py`: payload-hash binding, requester cannot approve own request, expiry, single use, two racing executions (one wins), changed payload refused, cross-tenant refused, permission refused over the API, refused execution leaves the approval unused | Built for the gate. No capability requires approval yet, so none can run through one until product names them (DFR1-025 workflow nodes remain open) |
| In-flight revalidation and safe stopping | `test_turning_automation_off_mid_run_stops_the_remaining_rules`; `test_revalidation_happens_before_every_action_not_only_every_rule`; `test_each_later_step_is_revalidated_and_audited` | Verified before every action and every later rule. Granularity limit in section 2.5 |
| Background execution authorization | `test_an_execution_without_an_actor_is_refused`. No scheduler or background executor exists | Verified for the one path that exists. Any future background executor must call `authorize_execution` |
| Fail-closed behaviour | Unknown capability, unverified snapshot, missing or disabled plan feature, undefined feature, no actor, no membership | Verified |
| Complete audit of allowed and denied execution | `test_allowed_and_denied_decisions_are_both_audited_with_the_reason` | Verified. Audit is in the caller's transaction, so a rolled-back operation leaves no decision record |
| Manual CRM works when AI is disabled | `test_manual_deal_creation_still_works_when_automation_is_off`; existing deal API tests | Verified |

### 2.8 Blockers and external dependencies

1. **DFR1-002**: ADR-0025, ADR-0026 and ADR-0027 are still Proposed. The story stays To Do.
2. **DFR1-005**: SIBVO plan feature keys for AI and channel capabilities are unconfirmed. Dealsflo will not invent them.
3. **Provider adapters and probes** (DFR1-007, DFR1-015): the connection model and gate exist (migration `m4d9f3a6c2e8`). Each real provider needs a registered probe and an external account before any AI or channel capability can run.
4. **Consent and channel policy**: built for gate 7. Still open: templates (DFR1-034) and the provider adapters (DFR1-007, DFR1-015).
5. **Approval**: lifecycle built for gate 5. Still open: the product decision on which capabilities require approval, and the approval workflow nodes (DFR1-025, which depends on DFR1-023).
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

Status: **Partial. Not Done.** The ledger, its lifecycle, idempotency, expiry, thresholds, breakdowns and
the execution-gate integration are implemented and tested. Nothing real is metered yet, because no AI
producer exists (DFR1-015). SIBVO usage reconciliation (DFR1-053) is blocked: no contract has been approved,
and nothing in the codebase calls SIBVO for usage.

### 4.1 Schema

- `ai_usage_events`: unique on `(organization_id, idempotency_key)`. Unit, reserved quantity, actual quantity,
  status (`reserved`, `recorded`, `released`, `reversed`), provider, model, task type, user, agent, workflow,
  execution, correlation ID, currency, occurred-at, **capability key** (null when unattributed), **expiry**
  (set for reservations), and **release reason** (for example `expired`).
- `organization_usage_budgets`: unique on `(organization_id, unit, period_start)`. Limit, reserved, consumed,
  highest alert already announced, and **warning and critical thresholds**. A check constraint enforces
  `1 <= warning < critical < 100`.
- Migration `k2b7d4e9a1c3` (after `j1a6e3c9b4d2`). Additive: new nullable columns, an index on
  `(status, expires_at)`, two threshold columns with defaults 70 and 85, and the constraint. Existing rows keep
  their values. Downgrade drops only these columns.

### 4.2 Units

`tokens_input`, `tokens_output`, `audio_ms`, `images`, `document_pages`, `provider_cost_minor`,
`customer_credits`. Each is an integer in its own unit. Provider cost is in minor currency units.
Provider cost and customer credits never share a budget, and breakdowns never sum units together.

### 4.3 Lifecycle

| Operation | Budget effect | Repeat with the same key and unit and quantity | Repeat with a different unit or quantity |
|---|---|---|---|
| `reserve` | `reserved += q`. Refused when no budget exists (`BudgetNotConfiguredError`) or `q > remaining` (`BudgetExceededError`). The entry expires after `usage_reservation_ttl_seconds`. | Returns the existing entry. | Refused (`IdempotencyConflictError`). Nothing changes. |
| `settle` | `reserved -= reserved_q`; `consumed += actual`. Actual above the reservation is recorded as overrun. | Returns the recorded entry. | Not applicable. |
| `release` | `reserved -= reserved_q`. Records a reason, for example `failed` or `entitlement_removed`. | Returns the released entry. | Not applicable. |
| `record` | `consumed += q`, even above the limit. For usage reported after the fact. | Returns the existing entry; no second count. | Refused. |
| `reverse` | `consumed -= quantity`. The row is kept with status `reversed`. | Returns the reversed entry. | Not applicable. |
| `release_expired` | `reserved -= reserved_q` for each reservation whose expiry has passed. Status `released`, reason `expired`. Audited. | Released entries are skipped. | Not applicable. |

**Concurrency.** Budget rows are locked (`SELECT ... FOR UPDATE`) before any change. Entries are locked before
settlement, release, reversal and expiry, and the lock order is always entry then budget. `reserve` and
`record` insert the new entry inside a savepoint first. If a concurrent request with the same key wins the race,
the unique index refuses the insert, nothing else has changed, and the winner's entry is returned or the
conflict is reported. Expiry locks entries with `SKIP LOCKED`, so two cleanup runs never work on one entry.

**Expiry.** A reservation not settled within `USAGE_RESERVATION_TTL_SECONDS` (default 900, range 60 to 86400) is
released by `python -m app.governance.usage_maintenance`. That default is an operating choice, not a legal period.
Settling or releasing an expired entry is refused, so its quantity is never counted twice. Cleanup is platform-wide and
idempotent, and it runs in batches, each committed on its own. Nothing schedules the job in this repository, so
until a scheduler runs it, an unsettled reservation holds its budget. Its quantity is never counted as consumed.

### 4.4 Thresholds and alerts

- Warning and critical thresholds are configurable per budget (`PUT /api/v1/governance/usage/budgets/{unit}` with
  optional `warning_percent` and `critical_percent`). Valid values are `1 <= warning < critical < 100`. The 100 percent
  (exhausted) alert is fixed. A change applies to future crossings.
- The highest threshold newly crossed by a change is announced once per budget per period. A change crossing several
  thresholds announces only the highest. Repeats are not announced again.
- Delivery is an **in-app notification** to each administrator (`governance.budgets.manage`), through the outbox
  (`deliver_usage_threshold_alert`). Retries are safe, and a failure to notify is retried and then dead-lettered.
  No email or other external message is sent. The outbox worker must be deployed to deliver anything (section 4.6).
- Budget changes are audited with the before and after limit and thresholds.

### 4.5 Breakdowns

`GET /api/v1/governance/usage/breakdown?group_by=capability|unit|provider` (`governance.usage.read`). The current UTC
calendar month. Only live entries count: reservations not yet settled, and recorded usage. Released, expired and
reversed entries are excluded. Each row shows recorded and reserved quantities and the entry count, per unit.
Entries without a capability or provider are shown as `unattributed`. Totals are organization-scoped.

### 4.6 Execution gate integration (DFR1-006)

A billable execution must reserve budget through the central gate (`app/governance/execution_gate.py`).
`ExecutionRequest.budget` carries the unit, quantity and idempotency key. The gate reserves last, after
every other check, so a refused execution never holds usage. Refusals:

| Reason code | Meaning |
|---|---|
| `budget_reservation_required` | Billable execution with no budget reservation requested. |
| `budget_not_configured` | No budget for the unit in this period. |
| `budget_exhausted` | The reservation would exceed the remaining budget. |
| `usage_key_conflict` | The key was already used for a different unit or quantity. |

The caller owns the reservation after an allowed decision. It must settle it when the work completes, or release it
when the work fails or the run stops. A run stopped by a removed entitlement releases its reservation (tested).

**No producer calls the gate with billable work.** No AI gateway, agent, voice or workflow runtime exists.

### 4.7 Acceptance-criteria gap map (DFR1-017)

| Criterion | Evidence | Status |
|---|---|---|
| Accurate organization-scoped usage ledger | Schema; `test_usage_and_idempotency_are_scoped_to_one_organization`; breakdown isolation test | Verified |
| Idempotent usage recording | `test_repeating_a_reservation_key_changes_nothing`; `test_a_delayed_provider_report_delivered_twice_is_counted_once`; `test_a_repeated_reservation_with_the_same_quantity_returns_the_same_entry` | Verified |
| Duplicate and conflicting idempotency keys | `test_a_conflicting_reservation_quantity_is_refused_and_changes_nothing`; `test_a_conflicting_unit_for_the_same_key_is_refused`; `test_a_conflicting_recording_for_an_existing_key_is_refused`; `test_two_simultaneous_first_requests_with_one_key_create_one_entry` | Verified (PostgreSQL) |
| Reservation, settlement, release, reversal | `tests/test_usage_ledger.py` lifecycle tests | Verified |
| Concurrency-safe budget enforcement | `test_concurrent_reservations_cannot_exceed_the_limit`; `test_concurrent_reservations_at_the_limit_admit_only_what_fits` | Verified (PostgreSQL) |
| Reservation expiry and automated cleanup | `test_an_unsettled_reservation_is_released_at_expiry...`; `test_cleanup_is_idempotent...`; `test_settling_an_expired_reservation_is_refused...`; `test_the_cleanup_job_releases...` | Verified. **Not scheduled** (section 4.3) |
| Organization budgets | `configure_budget`, `change_budget`, `PUT /usage/budgets/{unit}` | Verified |
| Configurable warning and critical thresholds | `test_configured_thresholds_drive_the_alerts`; `test_invalid_threshold_pairs_are_refused`; `test_the_default_thresholds_are_70_and_85` | Verified |
| Threshold transitions and duplicate alert prevention | `test_threshold_alerts_fire_once...`; `test_repeated_crossings_do_not_duplicate_alerts`; `test_a_threshold_is_announced_once_per_period_even_after_settlement` | Verified |
| In-app budget alerts and delivery reliability | `tests/test_usage_alert_delivery.py` (delivery, idempotent redelivery, dead-lettering). Outbox worker must run | Verified in tests. **Not deployed** |
| Accurate usage breakdowns by capability and period | `test_breakdowns_group_by_capability_unit_and_provider...`; `test_breakdowns_are_organization_scoped`. Current month only | Verified for the current period. Period selection not built |
| Dashboards | Usage panel: budgets, thresholds and breakdown table | Verified in unit tests. Not browser-verified |
| Safe behaviour when budgets are exhausted | `test_exhausted_budget_refuses_new_work_until_capacity_is_released`; `test_gate_denies_billable_work_when_the_budget_is_exhausted...` | Verified |
| Integration with the DFR1-006 gate | `test_billable_work_reserves_budget_through_the_gate`; gate denial tests; `test_entitlement_removed_during_execution...` | Verified for the gate. **No producer** calls it |
| Entitlement removal during execution | `test_entitlement_removed_during_execution_stops_the_run_and_the_caller_releases_usage` | Verified at the gate |
| Usage producers (AI gateway, agents, voice, workflows) | None | **Blocked: DFR1-015** |
| SIBVO usage reconciliation | None | **Blocked: DFR1-053 (E12) needs an approved contract** |
| Capability-level budgets "where appropriate" | Budgets are per unit only | **Decision needed**: which capabilities get their own limit |

### 4.8 Blockers and dependencies

1. **DFR1-015 (AI gateway)**: the only source of real usage. Until it exists, every figure in the ledger is zero.
2. **DFR1-053 (E12), SIBVO reconciliation**: needs an approved contract for usage summaries and reconciliation. No
   contract is approved, so nothing has been implemented or called, and no reconciliation success is reported.
3. **Scheduling**: `usage_maintenance` and the outbox worker need a deployment that runs them. None is defined here.
4. **Per-capability budgets**: a product decision on which capabilities get their own limits.

### 4.9 Verification

- `tests/test_usage_reservations.py`: 25 test functions (28 cases, one parametrized) covering duplicate and conflicting keys, the concurrent first request,
  concurrent reservations at the limit, expiry and cleanup, exhaustion and recovery, thresholds, breakdowns, organization
  isolation, and the gate.
- `tests/test_usage_ledger.py` and `tests/test_usage_alert_delivery.py`: the existing lifecycle, threshold and delivery tests.
- Migration `k2b7d4e9a1c3`: upgrade, downgrade and re-upgrade verified on a fresh PostgreSQL cluster that ran the full
  chain from empty.

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
| `crm.customer_profiles` | Yes | Not processed (`deletion_executor_not_built`) | Not enforced | Customer notes are free text. Deletion approach is decision 1 in 5.6. |
| `crm.requirements` | Yes (lead, profile, status, budget range) | Not processed | Not enforced | Requirement sub-records (locations, preferences, history) are not exported; see 5.2a. |
| `crm.deals` | Yes, with payment milestones and commissions | Not processed | Not enforced | Financial and commission records. Retention is decision 1 in 5.6; they are never deleted by a request while the decision is open. |
| `documents.files` | Yes, with the stored files. All or nothing: a missing object, a checksum mismatch, or a total over `PRIVACY_EXPORT_MAX_BYTES` excludes the whole category | Stored object, then metadata row (`deleted`) | Enforced by age (`created_at`) | None. |
| `team.invitations` | Yes. The token hash is never exported | Email replaced by a non-deliverable placeholder; pending invitations revoked (`anonymized`) | Enforced by age | None. |
| `messaging.email_outbox` | Excluded (`not_organization_owned`) | Excluded | Not applicable | Platform authentication and invitation mail carries no organization ID. It cannot be exported or deleted for one organization. Platform retention is a separate decision. |
| `messaging.conversations`, `voice.call_records`, `voice.transcripts`, `ai.prompts_and_responses`, `ai.embeddings`, `ai.execution_traces` | No producer (`no_producer_yet`) | No producer | Not applicable | Channel, voice and AI execution are not built (DFR1-015, 019, 027, 028). Blocked, not covered. |
| `ai.usage` | Yes (metering fields only; no prompt or response text) | Not deleted | Not applicable | Financial record. Retained by design. |
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

### 5.2a Classification gap

The register in `data_classification.py` covers 19 categories. The database has 44 tables with an `organization_id`
column. 17 are mapped to a category (payment milestones and deal commissions are exported as part of `crm.deals`).
Eight of the 27 unmapped tables are now exported as CRM sub-records (section 5.8). The remaining 19 are neither exported nor deleted by any request, and every artifact lists them under `not_covered`. `email_outbox_messages` has no
organization column and is covered by decision 5. Each needs a
sensitivity and a retention treatment decided by product and legal before it is added. Until then it is not claimed
as covered.

Unclassified, organization-owned tables (27): `activities`, `customer_requirement_history`,
`customer_requirement_locations`, `customer_requirement_possession_parking_preferences`,
`customer_requirement_property_preferences`, `deal_negotiations`, `deal_negotiation_history`, `deal_stage_history`,
`import_batches` (uploaded source files are referenced by storage key), `notifications`, `notification_preferences`,
`organization_memberships`, `properties`, `referrals`, `requirement_match_runs`, `requirement_match_run_results`,
`requirement_property_shortlists`, `requirement_shortlist_events`, `site_visits`, `team_member_removals`,
`automation_rules`, `automation_executions`, `auth_sessions`, `subscriptions` (SIBVO is authoritative for subscriptions),
`roles`, `organization_capability_settings`, `organization_usage_budgets`, `privacy_*` (governance records),
`outbox_events` and `privacy_*` are system and governance records, not customer data. Membership and subscription data
belong to SIBVO and should be handled by SIBVO's own processes; this is decision 6 in 5.6.

### 5.6 Decisions required before further work (product or legal)

Status after review (approved directions are recorded in the review, not implied by this list):

| Decision | Status |
|---|---|
| D1 free-text clearing | Approved as a direction. Field scope in 5.9 awaits approval. **Nothing cleared.** |
| D2 contact deferral | Approved. Extended to property owner and source contacts, and referrers. Rechecked at execution and on retry. |
| D3 billing and audit exports | Approved to exclude both, listed as not covered. |
| D4 retention periods | **Open.** No period set. |
| D5 email outbox | Approved to exclude. Platform retention **open**. |
| D6 SIBVO authority | Approved. Dealsflo does not delete or modify membership or subscriptions. Handoff in 5.10. |
| D7 scheduler | **Open.** Not deployed, not operational. |
| D8 tombstones | **Not verified** (5.10). Audit events are not yet shown to be immutable or readable by administrators. |
| D9 classification | Proposal in 5.8, not authorized. Nothing enabled. |
| D10 export approval | Met as decided (5.10). |
| D11 encryption | **Not met** (5.10). Needs a managed-key choice. |
| D12 holds | Met as decided. Holds block deletion, not export. |
| D13 import attachments | Treated as document-like. Not deleted. |


Each decision lists what it changes and what is left until it is answered. None has been assumed.

1. **Deletion approach for CRM free text and deals.** Options: (a) clear free-text fields only (customer notes,
   lead interest, outcome and next action, follow-up title and description, deal notes), keeping every row, so references
   stay intact; or (b) delete rows, which breaks references from deals, requirements and follow-ups and is blocked
   for deals with financial records. Consequence of (a): personal content is removed and the structure stays. Consequence
   of (b): referential breaks need a rule for each dependent table. Until decided, these categories are reported as
   `deletion_executor_not_built`.
2. **Contact anonymization while records depend on it.** Implemented as the proposed default: a contact that a lead or
   customer profile still references is left unchanged and reported as `deferred_dependent`. Other contacts are
   anonymized. The outcome stays `anonymized_partial`, so the request cannot read as complete. Consequence: a contact
   linked to a lead is never anonymized by a deletion until the dependency is removed or the rule is changed. Approval is
   needed to confirm this rule, because it determines what a deletion changes.
3. **Billing and audit records in an export.** Option: include them for a customer-authorized export, with named sensitive
   fields filtered out. The fields to filter (for example webhook payload fragments, provider references, actor identifiers)
   and the authorization rule (who may request them) are not defined. Until they are, billing and audit records are reported
   as `not_exported` with reason `export_not_built`, and never silently excluded.
4. **Retention periods.** No period is set in code. Each category needs a number of days and a legal basis, decided by
   product and legal. Retention is enforced only for documents and invitations, and only after a period is set.
5. **Platform email outbox.** It holds authentication and invitation mail with no organization ID. A platform-level period
   and an export route for individuals, if any, need a decision. It stays excluded from per-organization export and deletion.
6. **Membership, subscription and identity data.** Who answers an export request for membership and subscription data
   that SIBVO holds: SIBVO, Dealsflo, or both. This affects the classification in 5.2a.
7. **Scheduling and deployment.** Scheduling is not configured. An operator must run `privacy_maintenance` on a schedule
   before any automatic retention or expiry runs. Decision: which scheduler and environment, and who owns it.
8. **Tombstones.** Deletion audit events already record categories, counts and outcomes, with no personal values. A separate
   tombstone table is not built. Decision: whether the audit event is sufficient, or a separate record is required.

### 5.7 Verification

- `tests/test_privacy_execution.py`: 43 tests. Review controls added in this checkpoint: the not-covered notice in every artifact, CRM sub-record exports with allowlisted fields and no actor identifiers, a deferral for contacts referenced by properties and referrals, a failed post-deletion check that rolls back and never completes, a legal hold that blocks deletion but not export, and a read-only administrator refused for export requests and downloads. `tests/test_outbox_error_redaction.py`: database error text is withheld from the outbox. Dependent contacts: a lead or a customer profile defers the contact (`deferred_dependent`); a dependency created after the request is respected at execution time; a retry after a failure re-evaluates dependencies; independent contacts are anonymized; a deferred contact never produces a complete status. They cover export coverage and ZIP contents; all-or-nothing document export (missing object, checksum mismatch, size limit); exclusions; invitation token omission; leads, follow-ups, customer profiles, requirements, deals with payment milestones and commissions, and AI usage export (organization-scoped, with a cross-organization check); deletion; holds at request and execution time; storage-failure rollback and retry; idempotency; download access and expiry; cross-tenant refusal; retention per organization and per category; legal-hold skip; the expiry job; cancellation; failure isolation between organizations; and absence of personal data from logs.
- Migrations: `j1a6e3c9b4d2` verified upgrade, downgrade and upgrade on a fresh PostgreSQL database that ran the full chain from empty.

### 5.8 Classification proposal for the 27 unclassified tables (for review, not authorization)

This is a proposal. A classification never authorizes deletion or anonymization. Each row shows the owner and the source of
authority, the personal data present, what export does today and what is proposed, the deletion position, the retention
requirement (open under D4), legal-hold applicability (D12), the foreign-key restrictions that a deletion must respect, and the
tests required. "Pending" means the decision is open and no behaviour is enabled.

Tables marked **exported** are now covered by a read-only export under their parent category (applied in this checkpoint).

| # | Table | Owner / authority | Personal or sensitive data | Export | Deletion / anonymization | Retention | Holds (D12) | Key FK restrictions (delete rule) | Tests required |
|---|---|---|---|---|---|---|---|---|---|
| 1 | activities | Dealsflo (CRM) | Lead interaction notes | **Exported** under `crm.follow_ups/activities` (title, description, type, lead, times). `details` JSON and actor excluded | Pending D1 (title, description). `details` needs review first | Pending D4 | Yes, via `crm.follow_ups` | lead CASCADE; actor → memberships RESTRICT | export allowlist; actor and details absent |
| 2 | customer_requirement_history | Dealsflo | Snapshot of a customer's requirement | **Exported** under `crm.requirements/requirement_history` (snapshot included, actor excluded) | Pending D1 (snapshot content review) | Pending D4 | Yes, via `crm.requirements` | requirement NO ACTION; users RESTRICT | export; actor absent; snapshot review |
| 3 | customer_requirement_locations | Dealsflo | Customer's preferred city and locality | **Exported** under `crm.requirements/requirement_locations` | Structural, keep (matching depends on it) | Pending D4 | Yes | requirement CASCADE | export |
| 4 | customer_requirement_property_preferences | Dealsflo | Customer preference | **Exported** under `crm.requirements/requirement_property_preferences` | Structural, keep | Pending D4 | Yes | requirement CASCADE | export |
| 5 | customer_requirement_possession_parking_preferences | Dealsflo | Customer preference | **Exported** under `crm.requirements/requirement_parking_preferences` | Structural, keep | Pending D4 | Yes | requirement CASCADE | export |
| 6 | deal_negotiations | Dealsflo | Negotiation state for a deal | **Exported** under `crm.deals/negotiations` (state, times; `updated_by` excluded) | Pending D4 (financial relation) | Pending D4 | Yes, via `crm.deals` | deal CASCADE; `updated_by` → memberships RESTRICT | export; actor absent |
| 7 | deal_negotiation_history | Dealsflo | Free-text note on a negotiation step | **Exported** under `crm.deals/negotiation_history` (note included, actor excluded) | Pending D1 (note) and D4 | Pending D4 | Yes | negotiation CASCADE; actor → memberships RESTRICT | export; actor absent |
| 8 | deal_stage_history | Dealsflo | Free-text reason for a stage change | **Exported** under `crm.deals/stage_history` (reason included, actor excluded) | Pending D1 (reason) | Pending D4 | Yes | deal CASCADE; actor → users SET NULL | export; actor absent |
| 9 | import_batches | Dealsflo | Uploaded source file; contacts loaded from it | Not exported (D13). Treated as document-like | Pending D13 (ownership, dependencies, retention) | Pending D4 | Yes, once classified | contacts → import_batches **RESTRICT** (a contact row blocks deletion of its batch); org CASCADE | not-covered notice; later: document-style export and deletion tests |
| 10 | notifications | Dealsflo (per user) | Notification text may name customers | Not exported | Pending D9 | Pending D4 | Yes, once classified | users CASCADE | not-covered notice; export for the recipient only |
| 11 | notification_preferences | Dealsflo (per user) | User preference | Not exported | Pending D9 | n/a | Yes, once classified | users CASCADE | not-covered notice |
| 12 | organization_memberships | **SIBVO** (D6) | Member identity | Not exported. SIBVO answers | **Dealsflo must not delete or modify** (D6) | SIBVO | Not applicable to Dealsflo | users CASCADE; org CASCADE; referenced RESTRICT by deals, leads, follow-ups, activities, requirements and others | handoff notice; test that Dealsflo privacy paths never write it |
| 13 | subscriptions | **SIBVO** (D6) | Plan and billing state | Not exported. SIBVO answers | **Dealsflo must not modify** (D6) | SIBVO | Not applicable to Dealsflo | plans RESTRICT; org CASCADE | handoff notice; test as above |
| 14 | roles | Dealsflo configuration (role definitions) | No personal data | Not exported (configuration) | Not applicable | n/a | No | org CASCADE; membership_roles CASCADE | not-covered notice |
| 15 | organization_capability_settings | Dealsflo configuration | Actor user recorded | Not exported (configuration) | Not applicable | Keep for the audit trail (D8) | No | users **RESTRICT** (a user row cannot be deleted while a change record refers to it) | not-covered notice |
| 16 | organization_usage_budgets | Dealsflo configuration and billing | None (aggregate quantities) | Not exported | Not applicable (financial record) | Pending D4 | No | org RESTRICT | not-covered notice; keep out of deletion |
| 17 | properties | Dealsflo (inventory) | Owner and source contacts; addresses may identify owners | Not exported | Pending D9. Owner and source references block contact anonymization (**deferred**, see 5.2) | Pending D4 | Yes, once classified | contacts NO ACTION (owner, source); deals, site visits and documents **RESTRICT**; shortlists CASCADE | not-covered notice; contact-deferral test (exists) |
| 18 | referrals | Dealsflo | Referred person's name, phone and email (a third party) | Not exported | Pending D9 and legal review (third-party data) | Pending D4 | Yes, once classified | contacts, customer profiles and deals **RESTRICT**; users SET NULL | not-covered notice; contact-deferral test (exists) |
| 19 | requirement_match_runs | Dealsflo (derived) | Matches made for a customer | Not exported | Pending D9 | Pending D4 | Yes, once classified | memberships **RESTRICT**; org CASCADE | not-covered notice |
| 20 | requirement_match_run_results | Dealsflo (derived) | Matched property per run | Not exported | Pending D9 | Pending D4 | Yes, once classified | match runs CASCADE | not-covered notice |
| 21 | requirement_property_shortlists | Dealsflo | Shortlisted properties for a customer | Not exported | Pending D9 | Pending D4 | Yes, once classified | requirements CASCADE; properties CASCADE; memberships **RESTRICT** | not-covered notice |
| 22 | requirement_shortlist_events | Dealsflo | Shortlist actions by a member | Not exported | Pending D9 | Pending D4 | Yes, once classified | memberships **RESTRICT**; org CASCADE | not-covered notice |
| 23 | site_visits | Dealsflo | Visit notes, outcome and feedback | Not exported | Pending D1 (notes, feedback, outcome) and D9 | Pending D4 | Yes, once classified | customer profiles, leads, memberships and properties **RESTRICT** | not-covered notice; deletion blocked by dependencies |
| 24 | team_member_removals | Dealsflo | Removal reason (free text) and removed user | Not exported | Pending D9 | Pending D4 | Yes, once classified | users **RESTRICT** (both); org RESTRICT | not-covered notice |
| 25 | automation_rules | Dealsflo configuration | Rule may name a creator (SET NULL) | Not exported | Not applicable (configuration) | n/a | No | users SET NULL; org CASCADE | not-covered notice |
| 26 | automation_executions | Dealsflo (execution history) | References deals and actions | Not exported | Pending D4 (kept as the execution record) | Pending D4 | Yes, once classified | rules CASCADE; org CASCADE | not-covered notice |
| 27 | auth_sessions | Dealsflo identity | Session credentials | **Never exported** | Session revocation only, not privacy deletion | Session lifetime (configuration, not a legal period) | No | users CASCADE; org CASCADE | test that exports never include credentials |

Summary of the classification:
- **SIBVO-owned (not changed by Dealsflo):** organization_memberships, subscriptions (D6).
- **Configuration, not customer data:** roles, organization_capability_settings, organization_usage_budgets, automation_rules.
- **Customer or personal data, exported in this checkpoint:** 8 tables (rows 1 to 8).
- **Customer or personal data, not exported (pending classification):** rows 9 to 11, 17 to 24, 26.
- **Never exported:** auth_sessions.

Restrictions that a future deletion must respect (from the foreign-key query above):
- `properties` is referenced by `deals`, `site_visits` and `documents` with RESTRICT. A property cannot be deleted while those rows exist.
- `contacts` is referenced by `import_batches` with RESTRICT, so a batch cannot be removed while its contacts remain.
- `referrals` references contacts, customer profiles and deals with RESTRICT.
- Membership rows are referenced with RESTRICT by most CRM tables. A membership cannot be removed by a privacy request.

### 5.9 Free-text field inventory for decision D1 (for approval; nothing is cleared yet)

D1 approves selective clearing of approved personal free-text fields. The inventory below is the exact scope for your approval.
No field has been cleared, and no destructive behaviour has been enabled.

| Field | Table (category) | Personal content | Financial or legal record? | Dependencies | Proposal |
|---|---|---|---|---|---|
| customer_notes | customer_profiles (crm.customer_profiles) | Yes | No | Profile referenced by requirements, deals and site visits | Clear, pending approval |
| interest, outcome, next_action | leads (crm.leads) | Yes | No | Deals, follow-ups and requirements reference the lead | Clear, pending approval |
| title, description | follow_ups (crm.follow_ups) | Yes | No | Lead and site visit | Clear, pending approval |
| title, description | activities (crm.follow_ups) | Yes | No | Lead | Clear, pending approval. Review `details` JSON first |
| notes | deals (crm.deals) | Yes | Deal record | Payments, commissions, negotiations | **Hold for D4**. Financial relation |
| notes | payment_milestones (crm.deals) | Possibly | **Yes, financial** | Deal | **Keep**. Financial retention pending |
| terms | deal_commissions (crm.deals) | Possibly | **Yes, financial** | Deal | **Keep**. Financial retention pending |
| note | deal_negotiation_history (crm.deals) | Possibly | Negotiation record | Negotiation | Pending D4 |
| reason | deal_stage_history (crm.deals) | Possibly | Stage record | Deal | Clear, pending approval |
| snapshot (JSON) | customer_requirement_history (crm.requirements) | Yes | No | Requirement | Review contents first |
| notes, feedback, outcome | site_visits (unclassified) | Yes | No | Customer, lead, property | Pending D9 |
| referral_name, referral_phone, referral_email, notes | referrals (unclassified) | **Third-party personal data** | No | Contacts, customer profiles, deals | Pending D9 and legal review |
| reason | team_member_removals (unclassified) | Possibly | Governance record | Membership | Pending D9 |
| title, message | notifications (unclassified) | Possibly | No | Recipient | Pending D9 |
| description | documents (documents.files) | Possibly | No | Lead, property | Clear, pending approval |
| first_name, last_name, email, phone | contacts (crm.contacts) | Yes | No | Leads, profiles, properties, referrals | Already anonymized where no dependency exists (D2) |

Consequences of clearing: the row and its structure remain, so references, counts and history stay intact. The content is lost
permanently. Search, matching and reports that read these fields change. Clearing `payment_milestones.notes` or
`deal_commissions.terms` could remove records that financial rules require, which is why those rows are held.

### 5.10 Evidence for the remaining approved decisions

- **D8 (tombstones): not yet verified.** Audit events are written in the same transaction as the operation they record. Application
  code never updates or deletes them, and no API reads them, so an administrator cannot inspect deletion evidence today. No database
  trigger or constraint prevents change, so immutability is a convention, not a control. Deletion records are therefore not yet
  verified for durability, completeness or access control. Recommended: a database trigger that refuses UPDATE and DELETE on
  `audit_events`, and a read path for administrators. Both need approval, and the trigger changes how test cleanup works.
- **D11 (encryption at rest): not met.** Export artifacts and stored documents are written as plain files to local storage
  (`LocalObjectStorage`). The only encryption in the codebase is application-level Fernet for the email outbox, keyed from the
  `EMAIL_OUTBOX_ENCRYPTION_KEY` environment variable, which is not managed key management. The storage factory lists an `s3`
  backend, but no S3 implementation exists. Encryption cannot be claimed. A managed-key option needs your choice (cloud key service
  with envelope encryption, or host-level encryption of the storage volume). Each choice has a different migration cost.
- **D10 (export approval): met as decided.** The request and the download both require `governance.privacy.manage`. Both are
  organization-scoped and audited (`privacy.export.requested`, `privacy.export.downloaded`). A test shows that a read-only
  administrator is refused.
- **D12 (holds block deletion, not export): met as decided.** A test shows that a hold blocks deletion and leaves export unchanged.
- **D6 (SIBVO authority): documented.** Dealsflo privacy paths do not write membership or subscription tables. A handoff notice is
  listed for each such table in every artifact. The cross-product request flow is: the requester contacts Dealsflo, Dealsflo
  records the request and states the SIBVO-owned data it does not cover, and SIBVO answers for its own data. The SIBVO side of
  this flow is not implemented here and needs SIBVO's agreement.
- **D5 (email outbox): met as decided.** Platform email is listed as not covered and is outside organization export and deletion.
  The platform retention period is open.
- **D4 and D7: open.** No retention period is set. Privacy maintenance is not scheduled, so it is not operational.

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

- Consent, channel policy, approvals, and the AI gateway are not built. Provider connections exist, but no provider probe is registered. Channel and voice
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
| DFR1-006 | Partial | DFR1-002 (To Do: ADR-0025/26/27 Proposed), DFR1-005 (To Do in the backlog; the entitlement check in code exists) | Engineering and product | Provider adapters and probes (DFR1-007, 015); consent and channel policy; approval model (DFR1-025); budget, rate and concurrency gates (DFR1-017); record-level permission scope; cancel-or-complete for runs that outlast a request (DFR1-019). Section 2.8 lists each blocker |
| DFR1-017 | Partial | DFR1-015 (AI gateway, not built), DFR1-005 (To Do in the backlog) | AI platform (E06) | Gateway producers; running the outbox worker in production; dashboard breakdowns; SIBVO reconciliation (DFR1-053) |
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
| DFR1-017 | **Partial** | Ledger lifecycle, idempotency and conflict refusal, concurrency, reservation expiry and cleanup, configurable thresholds, breakdowns, and gate integration are implemented and tested. No AI producer (DFR1-015) and no approved SIBVO reconciliation contract (DFR1-053) exist. Cleanup is not scheduled. Per-capability budgets are undecided. |
| DFR1-050 | **Partial** | Export for contacts, leads, follow-ups, customer profiles, requirements, deals (with milestones and commissions), AI usage metering, invitations and documents with files. Deletion for documents (full), invitations (full) and contacts (identity fields, partial). Retention for documents and invitations. Expiry, cancellation, audited download, failure-isolated maintenance. Not built: deletion for CRM free text (decision 1), billing and audit export (decision 3), most unclassified tables (section 5.2a), scheduling (decision 7). Section 5.6 lists the decisions. |
| DFR1-053 | **Blocked** | Dependencies not delivered. |

No E13 story is complete. E13 is not Done.

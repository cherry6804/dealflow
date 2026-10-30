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

## 2. Capability policy (DFR1-006)

### 2.1 Catalogue

`app/governance/capabilities.py` is code, so a new capability needs a reviewed gate set. Every
capability is disabled by default.

| Key | Parent | SIBVO feature | Provider gate | Consent gate |
|---|---|---|---|---|
| `ai.master` | none | | | |
| `automation.master` | none | | | |
| `ai.assistant`, `ai.agents`, `ai.workflow_execution`, `ai.predictions`, `ai.content_generation`, `ai.document_processing` | `ai.master` | none defined yet | yes | |
| `ai.voice` | `ai.master` | none defined yet | yes | yes |
| `automation.deal_created_rules` | `automation.master` | `workflow_automation` | | |
| `channels.whatsapp`, `channels.email`, `channels.sms`, `channels.voice` | none | none defined yet | yes | yes |

The SIBVO feature key `workflow_automation` is the existing SIBVO plan feature. A capability without a
defined SIBVO feature key cannot pass the entitlement gate, so it stays denied.

### 2.2 Evaluation sequence

`app/governance/policy.py::evaluate_capability` returns a `PolicyDecision` with `allowed`,
`reason_code`, `explanation`, `policy_version` and `correlation_id`. Gates run in this order, and the
first failing gate decides the reason:

1. **Unknown capability:** denied (`unknown_capability`).
2. **Entitlement** (only where the capability declares a SIBVO feature). `app/governance/entitlement.py`
   reads the attested session snapshot:
   - no attested session, or no snapshot (SIBVO unavailable, session revoked): `entitlement_unverified`;
   - snapshot bound to another organization: `wrong_organization`;
   - no product role (product membership inactive or suspended): `product_membership_inactive`;
   - expired trial: `trial_expired`; other non-eligible subscription status: `subscription_not_active`;
     only `active` and `trialing` are eligible;
   - malformed or non-list entitlements: `entitlement_unverified`;
   - feature absent from the plan: `entitlement_missing`; present but disabled: `entitlement_disabled`.
3. **Organization switches:** walk the chain from the top master down. `master_disabled` above the
   capability, `capability_disabled` on the capability itself.
4. **Provider required:** denied (`provider_not_connected`). No provider integration exists.
5. **Consent required:** denied (`consent_not_configured`). No consent model exists.
6. Otherwise allowed (`allowed`).

Denial explanations are generic. They never reveal plan contents or internal policy.

The snapshot is the one E12 validates through SIBVO introspection. Its freshness is bounded by the
E12 revalidation interval (30 seconds by default). A subscription change in SIBVO can therefore take up
to that interval to reach Dealsflo. This is an accepted bound, not an immediate revocation.

### 2.3 Enforcement points

- **Deal-created automation** (`execute_deal_created_automations`, called from `POST /api/v1/deals`)
  evaluates `automation.deal_created_rules` with the request's user context. A denial returns an empty
  list and creates no execution. The deal is created normally, so manual CRM work is unaffected.
- No other execution path is governed, because no other execution path exists (section 11).

### 2.4 In-flight policy

- A disabled master or capability, or a lost entitlement, takes effect on the next evaluation. Tests
  show an active rule stops producing executions as soon as its master is turned off, and as soon as the
  entitlement is missing or disabled.
- Work already started is not cancelled by this change. The cancel-or-complete policy belongs to the AI
  runtime (DFR1-019), which is not built.

### 2.5 Existing organizations (decision 1)

**Decision.** Every existing organization starts with every optional AI and automation capability
disabled. No migration enables anything. An organization can use a capability only after an authorized
administrator enables it under the policy.

**Why no existing organization has an opt-in.** Before E13 no organization-level automation switch
existed. No action in the database recorded an enablement. The last-updating user on a rule shows who
touched the rule, not which action or interface enabled it, so it is not evidence of opt-in and is not
used.

**Migration behaviour.** The first E13 migration (`f3a7b9c1d2e4`) enabled automation for every
organization. The corrective migration `i7f2c9d4e1a8` removes only those unevidenced rows (no actor,
policy version 1, source `manual`) and grants nothing. After it runs:

- every existing organization has no automation switch, so automation is disabled;
- existing automation rules are preserved with their configuration, status, creator and history;
- execution history is not read or changed;
- the migration executes no rule and creates no notification.

**Enablement records.** Every change records the organization, the actor, the capability, the previous
state, the new state, the timestamp, the policy version, the source (`settings_api`) and a correlation ID.
Disablement and revocation are recorded the same way, with `action` set to `disabled`.

### 2.6 ADR-0029 and DFR1-002

- **ADR-0029: Accepted** on 2026-10-30, with amendments A (default policy), B (existing organizations),
  C (transactional email exemption), D (compatibility) and E (enforcement). The ADR records the
  enforcement status of each gate and each entry point.
- **DFR1-002: not complete.** Its acceptance criteria require the architecture diagram, context and
  container views, data ownership map, API conventions and approved ADRs. ADR-0025, ADR-0026 and
  ADR-0027 are still Proposed, and the backlog still shows DFR1-002 as To Do. Its status is unchanged.
- **DFR1-006 cannot be marked complete** while DFR1-002 is open and the remaining gates in section 11 are
  unimplemented.

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

### 5.1 What each operation actually does

| Operation | Executes? | Detail |
|---|---|---|
| Data classification | Yes (static register) | `app/governance/data_classification.py`. Shows `producer_exists`. Seven categories have no producer today. |
| Retention policy storage | Records only | Versioned days per category. |
| Retention enforcement | **Not built** | Retention days are not used in any eligibility decision or purge. No purge job exists. |
| Legal hold placement and release | Yes | Recorded and audited. |
| Legal hold enforcement | Checked in eligibility only | Deletion eligibility returns `legal_hold_active`. No deletion path exists, so nothing can bypass the hold, because nothing deletes. |
| Deletion eligibility evaluation | Yes | Reason codes: `not_customer_deletable`, `legal_hold_active`, `no_producer_yet`, `category_unknown`. |
| Deletion request creation | Records only | Stores per-category decisions. Status `eligibility_recorded` (some eligible) or `blocked` (none). **No data is deleted.** `test_a_deletion_request_removes_no_data_and_an_export_creates_no_artifact`. |
| Actual deletion or anonymization | **Not built** | No code path removes or anonymizes any category. |
| External provider deletion confirmation | **Not built** | No provider exists to confirm against. |
| Export request creation | Records only | Status `awaiting_artifact_generation`. |
| Export artifact generation | **Not built** | No artifact producer. An export never becomes `ready` through the API. |
| Export expiry | Yes, for attached artifacts | `expire_export_if_due`. Nothing is attached today, so nothing expires. |
| Cancellation | Yes | Audited. Only for open requests. |

### 5.2 Decision recorded

Retention is stored and versioned, and the classification is shown to administrators. It is **not
enforced**. A retention period does not cause any deletion and does not make data eligible for deletion.

### 5.3 Blocked for DFR1-050

The acceptance criteria name messages, calls, transcripts, documents and AI data. Their producers are
blocked: voice (DFR1-027, DFR1-028), documents (DFR1-035), organization AI settings (DFR1-036), and the
channel gateway.

## 6. Frontend

Route `/settings/governance`. Three sections, each shown only when the server reports read access. Manage
controls appear only when the server reports manage access, and the server still enforces every request.
Confirmation is required for every consequential change.

The page states that deletion requests perform no deletion, and that exports are awaiting generation.
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
- Retention is not enforced (section 5.2). Export artifacts and deletion execution are not built.
- The entitlement snapshot is bounded by the E12 revalidation interval (section 2.2).
- Transactional account email is outside the capability model (section 11, entry 7).
- Governance audit events are written to `audit_events` (event types `governance` and `privacy`). No UI
  for browsing them exists.

## 10. Dependency and blocker matrix

| Story | Status | Dependency | Owner | Remaining |
|---|---|---|---|---|
| DFR1-002 | **Not complete** | ADR-0025, ADR-0026, ADR-0027 still Proposed; diagrams and ownership map not recorded | Engineering and product | Approve the remaining ADRs and record the diagrams and ownership map |
| DFR1-006 | Partial | DFR1-002 (open), ADR-0029 (Accepted), DFR1-005 (done) | Engineering and product | Consent and channel policy; provider health; publication and activation; actor permission on target; budget and rate gates; approval gate; AI runtime in-flight policy (DFR1-019); gates 3, 7, 8 and 9 for AI |
| DFR1-017 | Partial | DFR1-015 (AI gateway), DFR1-005 (done) | AI platform (E06) | Gateway producers; running the outbox worker in production; dashboard breakdowns; SIBVO reconciliation (DFR1-053) |
| DFR1-050 | Partial | DFR1-028, DFR1-035, DFR1-036 | Voice, documents, settings | Retention enforcement; deletion execution and anonymization; external deletion confirmation; export artifacts; coverage for messages, calls, transcripts and AI data |
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
| DFR1-006 | **Partial** | Foundation, entitlement enforcement and one entry point. DFR1-002 open. Consent, provider, approval and budget gates not implemented for any AI capability. |
| DFR1-017 | **Partial** | Ledger and budgets verified by tests. Alert delivery to administrators implemented (in-app, outbox worker). No production producer. |
| DFR1-050 | **Partial** | Classification, legal holds, eligibility and request records. No retention enforcement, deletion, anonymization, export artifacts or provider deletion. |
| DFR1-053 | **Blocked** | Dependencies not delivered. |

No E13 story is complete. E13 is not Done.

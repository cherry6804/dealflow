# AI governance, usage controls and privacy (DFR1-E13)

**Status:** Partial. DFR1-006 and DFR1-017 have dependency-independent foundations. DFR1-050 has a
foundation for classification, retention, legal holds and request records. No story is complete.
ADR-0029 is still Proposed (section 2.6).

**Related:** ADR-0029 (Proposed), ADR-0026 (outbox, Proposed), ADR-0027 (SIBVO entitlement, Proposed),
`sibvo-dealsflo-entitlement-contract.md`.

## 1. Authority boundaries

- SIBVO remains the authority for identity, organizations, memberships, subscriptions, plans,
  entitlements, seats and billing. Dealsflo stores no subscription or invoice.
- Dealsflo owns capability switches, retention policies, legal holds, privacy request records, the
  usage ledger, organization budgets and the audit records of those changes.

## 2. Capability policy (DFR1-006)

### 2.1 Catalogue

`app/governance/capabilities.py` is code, so a new capability needs a reviewed gate set. Every
capability is disabled by default.

| Key | Parent | Provider gate | Consent gate |
|---|---|---|---|
| `ai.master` | none | | |
| `automation.master` | none | | |
| `ai.assistant`, `ai.agents`, `ai.workflow_execution`, `ai.predictions`, `ai.content_generation`, `ai.document_processing` | `ai.master` | yes | |
| `ai.voice` | `ai.master` | yes | yes |
| `automation.deal_created_rules` | `automation.master` | | |
| `channels.whatsapp`, `channels.email`, `channels.sms`, `channels.voice` | none | yes | yes |

### 2.2 Evaluation sequence

`app/governance/policy.py::evaluate_capability` returns a `PolicyDecision` with `allowed`,
`reason_code`, `explanation`, `policy_version` and `correlation_id`.

1. Unknown capability: denied (`unknown_capability`).
2. Walk the chain from the top master down. The first disabled switch denies: `master_disabled` above
   the capability, `capability_disabled` on the capability itself.
3. Provider required: denied (`provider_not_connected`). No provider integration exists.
4. Consent required: denied (`consent_not_configured`). No consent model exists.
5. Otherwise allowed (`allowed`).

Gates not implemented, and therefore not claimed: **SIBVO entitlement verification for these
capabilities**, provider health, resource publication and activation, per-actor permission on the
target, budget and rate gates, human approval. These are listed in section 11.

### 2.3 Enforcement points

- `execute_deal_created_automations` evaluates `automation.deal_created_rules` before any rule runs.
  A denial returns an empty list and creates no execution. The deal is created normally.
- No other execution path is governed, because no other execution path exists (section 11).

### 2.4 In-flight policy

- A disabled master or capability takes effect on the next evaluation. Tests show an existing active
  rule stops producing executions as soon as its master is turned off.
- Work already started is not cancelled by this change. The cancel-or-complete policy belongs to the
  AI runtime (DFR1-019), which is not built.

### 2.5 Existing organizations (corrected)

The first E13 migration (`f3a7b9c1d2e4`) enabled automation for every existing organization, which
granted it without evidence. The corrective migration `i7f2c9d4e1a8` replaces that:

- **Evidence rule.** An organization is granted `automation.master` and `automation.deal_created_rules`
  only when it has a DEAL_CREATED automation rule with status ACTIVE and a recorded activating user
  (`updated_by_user_id`). Activation is an explicit user action (`POST /automation-rules/{id}/activate`),
  so that is the only reliable prior opt-in in the database. The grant is recorded with
  `source = migration_evidence_active_rule`.
- **Everything else is disabled.** Organizations with no rules, with only DRAFT or DISABLED rules, or
  with an active rule whose activator is unknown get no row, so they are disabled.
- **Blanket rows removed.** Rows written by `f3a7b9c1d2e4` (no actor, policy version 1, source
  `manual`) are deleted.
- **Nothing else changes.** Automation rule rows and execution history are not modified.
- **Limit of the evidence.** The database records who last updated a rule, not which path set it
  to ACTIVE. Edits made after activation can change the recorded actor while the rule stays active.
  The evidence is therefore reliable for "a named user has activated and maintained this rule", not
  for "this exact user made the opt-in decision".

Organizations created after the migration have no row and start disabled.

Measured on the test database before the correction: 114 of 5,619 organizations have an active
DEAL_CREATED rule with a recorded activator. All other organizations are now disabled.

### 2.6 ADR-0029 and DFR1-002 (not approved)

- **ADR-0029 status: Proposed.** Its header reads "approval pending". Its Compatibility section says
  "No AI capability exists today, so nothing is migrated", which does not cover the automation
  grandfathering decision in section 2.5.
- **DFR1-002 status: To Do** in the Jira backlog. Its acceptance criteria (architecture diagram,
  context and container views, data ownership map, API conventions, ADRs approved) are not recorded as
  met.
- **ADR-0025, ADR-0026 and ADR-0027 are also Proposed.**

**Decision required to approve ADR-0029:** (a) confirm the ten gates and the disabled-by-default rule;
(b) confirm the evidence rule for existing organizations in section 2.5, and add it to the ADR;
(c) confirm that transactional account email is outside the capability model (section 11); (d) record
who approves, and the date.

DFR1-006 cannot be marked complete while ADR-0029 and DFR1-002 are unresolved.

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

Every organization comes from the server-side tenant context. A request for an organization the
caller does not belong to is refused with 403. Owner-only keys are in `OWNER_ONLY_PERMISSION_KEYS`,
so custom roles cannot be granted them.

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

### 4.4 Verification (what the tests show)

| Property | Evidence |
|---|---|
| Idempotency under duplicate events | Repeated reserve, settle, release, record and reverse calls change nothing (`test_repeating_a_reservation_key_changes_nothing`, `test_a_delayed_provider_report_delivered_twice_is_counted_once`, reversal and release repeat tests) |
| Concurrent reservations | `test_concurrent_reservations_cannot_exceed_the_limit` (two threads, PostgreSQL row lock) |
| Reserve / settle / release / reverse | Lifecycle tests, including partial settlement (60 reserved, 25 used, 35 returned) |
| Failed and partially completed executions | Release on failure; settlement below the reservation returns the difference; settlement above it is recorded as overrun |
| Alert deduplication | Each of 70, 85 and 100 fires once; a single change crossing several thresholds announces only the highest (`test_one_change_crossing_several_thresholds_announces_only_the_highest`) |
| Period boundaries and timezone | Calendar months in UTC. `test_period_is_decided_in_utc_not_local_time`: 00:30 on 1 March in Kolkata is February in UTC |
| Provider cost vs customer credits | Separate units and budgets (`test_units_are_budgeted_independently`) |
| No double counting during retries | Repeated settle, release and record calls are no-ops |
| Tenant isolation | Same idempotency key in two organizations creates two entries; cross-tenant budget read and change refused |

**Known gap, stated plainly:** alerts are enqueued to the outbox, but no outbox handler is registered
in production (section 11). The worker refuses events without a handler and they will dead-letter, so
**no threshold alert reaches an administrator yet.**

### 4.5 Missing AI gateway producers

No producer exists in the codebase, so no real usage is recorded. Every production usage path is
missing:

- AI gateway (DFR1-015): text, embedding, speech and multimodal calls. It must emit reserve, settle
  or release for each billable call, with provider, model, tokens, audio duration, image count,
  document pages and provider cost, and it must reuse the call's idempotency key on retry.
- Agent runtime (DFR1-019), workflow runtime and voice (DFR1-027, DFR1-028): all bill through the
  gateway.
- SIBVO usage summaries and reconciliation (DFR1-053): blocked on the approved contract.

No usage data has been fabricated.

## 5. Privacy, retention and requests (DFR1-050)

### 5.1 What each operation actually does

| Operation | Executes? | Detail |
|---|---|---|
| Data classification | Yes (static register) | `app/governance/data_classification.py`. Shows `producer_exists`; seven categories have no producer today. |
| Retention policy | Records only | Versioned days per category. **Retention days are not used in any eligibility decision or purge.** No purge job exists. |
| Legal hold placement and release | Yes | Recorded and audited. Enforced in deletion eligibility (`legal_hold_active`). |
| Legal hold enforcement on deletion | Only in eligibility | There is no deletion execution, so the hold is checked at request time and nothing can bypass it, because nothing deletes. |
| Deletion eligibility evaluation | Yes | Reason codes: `not_customer_deletable`, `legal_hold_active`, `no_producer_yet`, `category_unknown`. |
| Deletion request creation | Records only | Stores per-category decisions. Status `eligibility_recorded` (some eligible) or `blocked` (none). **No data is deleted.** Verified by `test_a_deletion_request_removes_no_data_and_an_export_creates_no_artifact`. |
| Actual deletion or anonymization | **Not built** | No code path removes or anonymizes any category. |
| External provider deletion confirmation | **Not built** | No provider exists to confirm against. |
| Export request creation | Records only | Status `awaiting_artifact_generation`. |
| Export artifact generation | **Not built** | No artifact producer. An export never becomes `ready` through the API. |
| Export expiry | Yes, for artifacts that are attached | `expire_export_if_due`. Nothing is attached today, so nothing expires. |
| Cancellation | Yes | Audited. Only for open requests. |

### 5.2 Retention decision recorded

Retention is stored and versioned, and the classification is shown to administrators. It is **not
enforced**. A retention period does not cause any deletion, and it does not make data eligible for
deletion. This must be built before retention can be claimed.

### 5.3 Blocked for DFR1-050

The acceptance criteria name messages, calls, transcripts, documents and AI data. Their producers are
blocked: voice (DFR1-027, DFR1-028), documents (DFR1-035), organization AI settings (DFR1-036), and the
channel gateway. DFR1-050 cannot be complete until those producers exist and deletion and export are
executed for each category.

## 6. Frontend

Route `/settings/governance`. Three sections, each shown only when the server reports read access.
Manage controls appear only when the server reports manage access, and the server still enforces
every request. Confirmation is required for every consequential change.

- **Capabilities.** Grouped by category, with the stored switch and the effective decision and reason.
- **Usage and budgets.** Current-month status per unit. Provider cost is shown as currency, and token
  counts are never shown as currency.
- **Privacy and retention.** Register, retention editor, legal holds, and export and deletion requests.
  The page states that no deletion is performed.

Tests: `governanceLabels.test.ts` and `pages/GovernancePage.test.tsx`.

**Not verified in a browser.** The page needs the migrations applied to the shared dev database and a
backend restart. Neither was done.

## 7. Migrations

| Revision | Adds or changes |
|---|---|
| `f3a7b9c1d2e4` | Creates `organization_capability_settings`; writes blanket automation rows (**superseded**); capability permissions |
| `g4b8c0d2e5f6` | Creates `ai_usage_events` and `organization_usage_budgets`; usage permissions |
| `h5c9d1e3f6a7` | Creates the privacy tables; privacy permissions |
| `i7f2c9d4e1a8` | Adds `source`; removes blanket automation rows; grants automation only on evidence (section 2.5) |

Verified: `tests/test_migration_automation_default.py` (8 tests) covers an existing organization without
opt-in, with explicit opt-in, with an active rule and no known activator, with only inactive rules, an
organization created after the migration, rule rows unchanged, downgrade and reapplication, and refusal
to downgrade after people have changed switches.

**Downgrade behaviour.** The downgrade refuses to run when a person has changed a capability switch
(`source = manual` with an actor), so such changes are not lost. It otherwise restores the blanket
state of `f3a7b9c1d2e4`. Downgrading past `f3a7b9c1d2e4` drops the table and every switch with it, so
export `organization_capability_settings` first.

**Operator note.** `alembic upgrade head` writes evidence-based automation rows for existing
organizations. It changes no other data.

## 8. Security and tenant isolation

Tested: cross-tenant policy reads and writes, legal holds scoped per organization, privacy requests
not visible or changeable across organizations, idempotency keys scoped per organization, cross-tenant
budget reads and changes refused, read-only users refused on manage endpoints, unknown categories and
capabilities refused, concurrent budget reservations, and migration evidence rules.

**Not tested, because the feature does not exist:** consent and opt-out bypass, approval bypass and
stale approvals, replayed webhooks, outbox retry policy bypass by AI consumers, export data leakage,
legal-hold bypass by external deletion.

## 9. Known limitations

- Consent, channel policy, approvals, entitlement verification for these capabilities, and the AI
  gateway are not built. Channel and voice capabilities deny until they exist.
- No production usage is recorded (section 4.5).
- No threshold alert is delivered (section 4.4).
- Retention is not enforced (section 5.2). Export artifacts and deletion execution are not built.
- The governance audit trail is written to `audit_events` (event types `governance` and `privacy`).
  No UI for browsing it exists.

## 10. Dependency and blocker matrix

| Story | Status | Dependency | Owner | Remaining |
|---|---|---|---|---|
| DFR1-006 | Partial | DFR1-002 (To Do), ADR-0029 (Proposed), DFR1-005 (done) | Engineering and product | Approve ADR-0029 and DFR1-002. SIBVO entitlement gate. Consent and channel policy. Provider health. Publication and activation. Actor permission on the target. Budget and rate gates. Approval gate. AI runtime in-flight policy (DFR1-019). |
| DFR1-017 | Partial | DFR1-015 (AI gateway), DFR1-005 (done) | AI platform (E06) | Gateway producers. Alert consumer. Dashboard breakdowns. Reconciliation (DFR1-053). |
| DFR1-050 | Partial | DFR1-028, DFR1-035, DFR1-036 | Voice, documents, settings | Retention enforcement. Deletion execution and anonymization. External deletion confirmation. Export artifacts. Coverage for messages, calls, transcripts and AI data. |
| DFR1-053 | Blocked | DFR1-017, DFR1-036, approved SIBVO ingestion contract | SIBVO and Dealsflo | Ingestion, reconciliation, lifecycle tests. |

## 11. Enforcement matrix (every execution entry point)

Columns: **Policy** = governance check location. **Entitlement** = SIBVO entitlement verified in this
path. **Enabled** = organization master and capability switches. **Resource** = rule or resource
activation. **Actor** = authorization of the initiating user. **Consent** = consent and channel policy.
**Budget** = usage budget. **Approval** = human approval. **Failure** = behaviour on denial or error.

| # | Entry point | Exists today? | Policy | Entitlement | Enabled | Resource | Actor | Consent | Budget | Approval | Failure |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Deal-created automation** (`execute_deal_created_automations`, called from `POST /deals`) | Yes | Enforced: `automation.deal_created_rules` | **NOT enforced** | Enforced (master and child) | Enforced: rule status ACTIVE | Deal creation requires `deals.create` at the API. Rules run as the system. | N/A: actions are internal (follow-up, in-app notification) | N/A: nothing is billable | None | Denial returns no executions. A per-rule error is recorded as a failed execution inside a savepoint. |
| 2 | **API-triggered execution** | Only via #1 | Same as #1 | Not enforced | Enforced via #1 | — | — | — | — | — | — |
| 2a | Rule activation (`POST /automation-rules/{id}/activate`) | Yes | Not applicable: changes status, executes nothing | — | Not checked. A rule can be activated while automation is off and simply will not run. | Changes rule status | Requires the automation permission | — | — | — |
| 3 | **AI gateway** | **No** | Not implemented | — | — | — | — | — | — | — | — |
| 4 | **Agent runtime** | **No** (DFR1-019) | Not implemented | — | — | — | — | — | — | — | — |
| 5 | **Workflow runtime** | **No executor.** `FOLLOW_UP_OVERDUE` trigger is named in a comment only | Not implemented | — | — | — | — | — | — | — | — |
| 6 | **Outbox consumers** | Worker exists; **no handler registered** in production | Not implemented. Any future handler must call the policy engine. | — | — | — | — | — | — | — | Events with no handler are refused and dead-letter. Threshold alerts currently stop here. |
| 7 | **Communication sending: transactional email** (email outbox worker: verification, password reset, team invitation) | Yes | **Not governed.** Classified as system transactional (account and security mail, not an optional capability). Requires approval in ADR-0029. | Not checked | Not applicable | Not applicable | Triggered by account actions | Not applicable (transactional) | Not applicable | Not applicable | Retries and dead-letter in the email outbox |
| 7a | Communication sending: WhatsApp, SMS, email campaigns, voice calls | **No** (channel gateway not built) | Not implemented; capabilities deny | — | — | — | — | Not implemented | — | — | — |
| 8 | **Voice operations** (inbound and outbound calls, transcription) | **No** (DFR1-027, DFR1-028) | Not implemented | — | — | — | — | — | — | — | — |
| 9 | **Background jobs** | Outbox worker; email worker; billing webhook reconciliation (writes reconciliation records) | Not applicable to optional execution. The billing and email jobs do not run AI or automation. | — | — | — | — | — | — | — | Retries and dead-letter, existing behaviour |
| 10 | **Scheduled execution** | **No scheduler in the repository.** `infrastructure/` contains only a README. | Not implemented | — | — | — | — | — | — | — | — |

**Conclusion.** Governance is enforced at exactly one execution entry point (#1). It is not universal.
Entries 3, 4, 5, 7a, 8 and 10 do not exist, and must enforce the complete gate set when they are built.
Entries 1 and 2 lack the entitlement gate. Entry 6 has no handler, so governance is moot until one
exists. Entry 7 is an explicit exemption that needs approval.

## 12. Story status

| Story | Status | Reason |
|---|---|---|
| DFR1-006 | **Partial** | Foundation and one enforcement point. ADR-0029 and DFR1-002 unresolved. Entitlement gate missing. |
| DFR1-017 | **Partial** | Ledger and budgets verified with tests. No production producer. No alert consumer. |
| DFR1-050 | **Partial** | Classification, legal holds, eligibility and request records. No deletion, anonymization, export artifacts, provider deletion, or retention enforcement. |
| DFR1-053 | **Blocked** | Dependencies not delivered. |

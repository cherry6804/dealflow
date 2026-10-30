# AI governance, usage controls and privacy (DFR1-E13)

**Status:** Partial. DFR1-006 and DFR1-017 have a dependency-independent foundation. DFR1-050 has a
foundation for retention, legal holds and request records. Consent and channel policy, the AI
gateway, provider connections and usage producers are not built. See section 10 for the matrix.

**Related:** ADR-0029 (disabled-by-default policy, status Proposed, approval pending),
ADR-0026 (outbox), ADR-0027 (SIBVO entitlement authority), `sibvo-dealsflo-entitlement-contract.md`.

## 1. Authority boundaries

- SIBVO remains the authority for identity, organizations, memberships, subscriptions, plans,
  entitlements, seats and billing. Dealsflo does not store a subscription or invoice.
- Dealsflo owns capability switches, retention policies, legal holds, privacy request records, the
  usage ledger and organization usage budgets, and the audit records of those changes.

## 2. Capability policy (DFR1-006)

### 2.1 Catalogue

`app/governance/capabilities.py` is code, so a new capability needs a reviewed gate set. Every
capability is disabled by default. Masters and children:

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
2. Walk the chain from the top master down. The first disabled switch denies:
   `master_disabled` above the capability, `capability_disabled` on the capability itself.
3. Provider required: denied (`provider_not_connected`). No provider integration exists, so these
   always deny.
4. Consent required: denied (`consent_not_configured`). No consent model exists, so these always deny.
5. Otherwise allowed (`allowed`).

Fail-closed: any gate whose infrastructure is missing denies. Gates not yet implemented, and
therefore not claimed: SIBVO entitlement (for these capabilities), provider health, resource
publication and activation, per-actor permission on the target, budget and rate gates, human approval.

### 2.3 Enforcement points

- `execute_deal_created_automations` (`app/automation_rules/execution_service.py`) evaluates
  `automation.deal_created_rules` before any rule runs. A denial returns an empty list and creates no
  execution. The deal is created normally, so manual CRM work is unaffected.
- No AI execution entry point exists yet. When one is added it must call the same engine.

### 2.4 In-flight policy

- Disabling a master or capability takes effect on the next evaluation. Tests show that an existing
  rule stops producing executions the moment its master is turned off.
- Work already started is not cancelled by this slice. The documented policy for cancelling or
  completing in-flight executions is part of the AI runtime (DFR1-019), which is not built.

### 2.5 Existing organizations

The migration `f3a7b9c1d2e4` writes an explicit `automation.master = enabled` row (policy version 1,
no actor) for every organization that exists when it runs, so deal-created automation keeps working
for them. Organizations created later have no row and start disabled. This is a deliberate
grandfathering choice and it is recorded in the migration docstring.

## 3. Settings API and permissions

| Method and path | Permission | Notes |
|---|---|---|
| `GET /api/v1/governance/access` | authenticated tenant member | Reports which governance permissions the caller holds. Shapes the UI only. |
| `GET /api/v1/governance/capabilities` | `governance.capabilities.read` | Stored switch plus effective decision. |
| `PATCH /api/v1/governance/capabilities/{key}` | `governance.capabilities.manage` (owner-only) | Body requires `confirm: true`. Writes an audit event. |
| `GET /api/v1/governance/usage/budgets` | `governance.usage.read` | Current UTC month, every unit with a budget. |
| `PUT /api/v1/governance/usage/budgets/{unit}` | `governance.budgets.manage` (owner-only) | Body requires `confirm: true`. Writes an audit event with before and after. |
| `GET /api/v1/governance/privacy/categories` | `governance.privacy.read` | Classification register, including `producer_exists`. |
| `GET /api/v1/governance/privacy/retention` | `governance.privacy.read` | Current retention per category. |
| `PUT /api/v1/governance/privacy/retention/{category}` | `governance.privacy.manage` (owner-only) | Versioned. Audited. |
| `GET /api/v1/governance/privacy/legal-holds` | `governance.privacy.read` | Organization-scoped. |
| `POST /api/v1/governance/privacy/legal-holds` | `governance.privacy.manage` (owner-only) | Reason required. Audited. |
| `POST /api/v1/governance/privacy/legal-holds/{id}/release` | `governance.privacy.manage` (owner-only) | Audited. |
| `GET /api/v1/governance/privacy/requests` | `governance.privacy.read` | Also expires ready exports whose window has passed. |
| `POST /api/v1/governance/privacy/requests` | `governance.privacy.manage` (owner-only) | Export or deletion. Body requires `confirm: true`. |
| `POST /api/v1/governance/privacy/requests/{id}/cancel` | `governance.privacy.manage` (owner-only) | Audited. |

Permissions are seeded by migrations `f3a7b9c1d2e4`, `g4b8c0d2e5f6` and `h5c9d1e3f6a7` for existing
organizations, and by the permission catalogue for new ones. Owner-only keys are in
`OWNER_ONLY_PERMISSION_KEYS`, so custom roles cannot be granted them.

Every organization is taken from the server-side tenant context. A request for another organization
is refused with 403 when the caller is not a member, and the tests cover that.

## 4. AI usage ledger and budgets (DFR1-017)

### 4.1 Schema

- `ai_usage_events`: one row per metered quantity. Unique on `(organization_id, idempotency_key)`.
  Columns: unit, reserved quantity, actual quantity, status, provider, model, task type, user, agent,
  workflow, execution, correlation ID, currency, occurred-at.
- `organization_usage_budgets`: one row per organization, unit and calendar period. Unique on
  `(organization_id, unit, period_start)`. Holds limit, reserved, consumed and the highest alert
  threshold already announced.

### 4.2 Units

`tokens_input`, `tokens_output`, `audio_ms`, `images`, `document_pages`, `provider_cost_minor`,
`customer_credits`. Every quantity is an integer in the unit's own terms. Provider cost is in minor
currency units and carries its currency. Provider cost and customer credits never share a budget.

### 4.3 Lifecycle and idempotency

| Operation | Effect on budget | Idempotent on repeat |
|---|---|---|
| `reserve` | `reserved += q`. Refused when the budget is missing (`BudgetNotConfiguredError`) or `q > remaining` (`BudgetExceededError`). | Returns the existing entry; no change. |
| `settle` | `reserved -= reserved_q`, `consumed += actual`. | Returns the recorded entry. |
| `release` | `reserved -= reserved_q`. | Returns the released entry. |
| `record` | `consumed += q`, even above the limit (overrun). | Returns the existing entry. |
| `reverse` | `consumed -= quantity`. The row stays, with status `reversed`. | Returns the reversed entry. |

Budget rows are locked with `SELECT ... FOR UPDATE` before any change, so concurrent reservations
cannot exceed the limit. `tests/test_usage_ledger.py` runs two reservations concurrently against one
budget and checks that exactly one is refused.

### 4.4 Alerts

Thresholds 70, 85 and 100 percent of the limit. Crossing a threshold enqueues one outbox event,
`ai.usage.threshold_reached`, with a per-threshold idempotency key. `last_alert_percent` ensures each
threshold fires once per period, including when a single change crosses several.

### 4.5 Period and units

Periods are calendar months in UTC (`budget_period_for`). An undefined unit is never treated as
currency or tokens: a unit must be one of the enumerated units.

### 4.6 Blocked

- No producer exists: the AI gateway (DFR1-015) is not built, so no usage is recorded in production.
  The ledger and budgets are tested with test data only.
- The usage dashboard breakdowns (by provider, model, capability, agent, workflow, user) need
  producers and are not built.
- SIBVO usage ingestion and reconciliation (DFR1-053) need the approved SIBVO contract (section 7 of
  `sibvo-dealsflo-entitlement-contract.md`) and are not built.

## 5. Privacy, retention and requests (DFR1-050)

### 5.1 Data classification

`app/governance/data_classification.py` lists every category with sensitivity, retention treatment
and `producer_exists`. The register is shown in the API so no category is reported as covered when
it has no producer. Categories with no producer today: conversations, voice call records, transcripts
and recordings, AI prompts and responses, embeddings, AI execution traces, and provider credentials.

Treatments:
- `organization_configurable`: may be removed on a deletion request, subject to legal holds.
- `mandatory_record`: audit events, billing records, the AI usage ledger. Never deleted by a customer
  request.
- `never_delete_by_customer`: secret references.

### 5.2 Retention

Versioned per category. `retention_days = null` keeps data until a request or hold changes that.
Changing retention creates a new version and an audit event. There is no automatic purge job; that
job is not built.

### 5.3 Legal holds

A hold blocks deletion of a category for the organization until it is released. Holds are scoped to
the organization, so one tenant's hold does not affect another. Placing and releasing are audited,
and releasing keeps the record.

### 5.4 Deletion eligibility

`evaluate_deletion` returns `eligible` with stable reason codes:
`not_customer_deletable`, `legal_hold_active`, `no_producer_yet`, `category_unknown`.

A deletion request records the per-category decision and never deletes data:
- all categories blocked: status `blocked`;
- some eligible: status `eligibility_recorded` (the words "no deletion performed" are shown in the UI).

Actual deletion or anonymization, deletion at external providers, and dependency discovery across
files, embeddings and transcripts are not built.

### 5.5 Export

An export request moves to `awaiting_artifact_generation`. Nothing becomes `ready` through the API. The
state machine accepts an artifact only for an export that is awaiting generation, and records an
expiry. A ready export whose window has passed becomes `expired`, with the artifact reference
cleared. Artifact generation and secure download are not built.

### 5.6 Blocked for DFR1-050

The acceptance criteria name messages, calls, transcripts, documents and AI data. Those producers
are blocked: voice (DFR1-027, DFR1-028), documents (DFR1-035) and organization AI settings (DFR1-036).
DFR1-050 is therefore not complete.

## 6. Frontend

Route `/settings/governance` (`frontend/src/app/routing/AppRouter.tsx`). Three sections, each shown
only when the server reports read access, with manage controls shown only when the server reports
manage access. The server still enforces every request.

- Capabilities: list grouped by category, with the stored switch and the effective decision and its
  reason. Turning a switch on or off needs confirmation.
- Usage and budgets: current-month status per unit with explicit unit labels. Provider cost is shown
  as currency and tokens are never shown as currency. Setting a limit needs confirmation.
- Privacy and retention: classification register, retention editor, legal holds (place and release),
  and export or deletion requests (create and cancel).

Frontend tests: `governanceLabels.test.ts` (labels and unit formatting) and
`pages/GovernancePage.test.tsx` (denied state, default-off display, confirmation before a change, and
cancel leaves state unchanged).

## 7. Migrations

| Revision | Adds |
|---|---|
| `f3a7b9c1d2e4` | `organization_capability_settings`; grandfathered `automation.master` for existing organizations; capability permissions |
| `g4b8c0d2e5f6` | `ai_usage_events`, `organization_usage_budgets`; usage permissions |
| `h5c9d1e3f6a7` | `privacy_retention_policies`, `privacy_legal_holds`, `privacy_data_requests`; privacy permissions |

Verified: the full chain (upgrade to head, downgrade to base, upgrade to head) passes in a disposable
schema inside `dealflow_test`. The public schema was not migrated in this pass. Operators apply it with
`alembic upgrade head`. The backfill inserts one row per existing organization. Downgrades drop the new
tables and their data, and remove only the permission rows they added.

## 8. Security and tenant isolation

Tested: cross-tenant policy reads and writes (`test_settings_of_one_organization_cannot_be_changed_with_another_tenant`,
`test_enablement_is_scoped_to_one_organization`), legal holds scoped per organization, privacy requests
not visible or changeable across organizations, idempotency keys scoped per organization, unauthorized
changes refused, confirmation required, unknown categories and capabilities refused, and concurrent
budget reservations.

Not yet tested or built: consent bypass and opt-out bypass (no consent model), approval bypass and stale
approvals (no approval model), replayed webhooks and outbox retry policy bypass (no AI outbox consumers),
export data leakage (no artifacts), and legal-hold bypass by external deletion (no external deletion).

## 9. Known limitations

- Consent, channel policy, approvals and the AI gateway are not built. Channel and voice capabilities
  deny until they are.
- Usage is never recorded in production because no producer exists.
- Export artifacts and deletion execution are not built.
- The governance audit trail is written to `audit_events` (event types `governance` and `privacy`).
  A UI for browsing that history is not built.

## 10. Dependency and blocker matrix

| Story | Status | Dependency | Owner | Remaining |
|---|---|---|---|---|
| DFR1-006 | Partial | DFR1-002 (ADR-0029 approval, pending), DFR1-005 (done) | Engineering and product approval | Entitlement gate, consent and channel policy (needs DFR1-028 and channel gateway), provider health (needs DFR1-015), publication and activation, actor permission on target, budget and rate gates, approval gate, AI runtime in-flight policy (DFR1-019) |
| DFR1-017 | Partial | DFR1-015 (AI gateway), DFR1-005 (done) | AI platform (E06) | Producers from the gateway, usage dashboard breakdowns, alerts delivery consumer, SIBVO contract for reconciliation (DFR1-053) |
| DFR1-050 | Partial | DFR1-028 (voice), DFR1-035 (documents), DFR1-036 (organization AI settings) | Voice, documents, settings owners | Export artifacts, deletion execution and external provider deletion, automatic retention purge, coverage for messages, calls, transcripts and AI data |
| DFR1-053 | Blocked (unchanged) | DFR1-017, DFR1-036, approved SIBVO ingestion contract | SIBVO and Dealsflo | Usage ingestion, reconciliation and lifecycle tests |

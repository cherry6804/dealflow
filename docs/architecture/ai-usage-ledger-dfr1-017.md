# AI usage ledger, provider cost, customer credits and budgets (DFR1-017)

- **Status:** Implemented on `feature/DFR1-017-ai-usage-ledger-budgets`. Provider cost is recorded independently. Customer credits are not recorded, because no authoritative conversion rule exists. Prices are configurable and versioned, but none are seeded: until a platform operator configures a price version, provider cost is recorded as **unpriced** and never as zero.
- **Owner:** governance (`app/governance/usage_ledger.py`, `app/governance/ai_pricing.py`). The reservation gate is `app/governance/execution_gate.py`.
- **Related:** `ai-governance-and-usage-controls.md`, `ai-usage-reservations.md`, `ai-usage-alert-thresholds.md`, `capability-policy-and-in-flight-behaviour.md` (DFR1-006).

## 1. Reused, not rebuilt

Usage entries, per-unit budgets, reserve, settle, release, reversal and expiry; the budget hard stop in the shared gate; per-organization idempotency keys and request fingerprints; the 70, 85 and 100 percent threshold alerts with once-per-crossing announcement; usage breakdown and budget and threshold API; the existing usage, reservation, alert, gateway, agent, workflow and OCR test suites.

## 2. Usage dimensions

| Dimension | Unit | Recorded by | Notes |
|---|---|---|---|
| Input tokens | `tokens_input` | Gateway, from provider usage | Settled to actual usage |
| Output tokens | `tokens_output` | Gateway, from provider usage | Settled to actual usage |
| Images | `images` | Gateway, from the request (multimodal) | Unchanged |
| Document pages | `document_pages` | Gateway, from `GatewayRequest.document_pages` | Separate unit. OCR reads one page per call and passes `document_pages=1` |
| Audio | `audio_ms` | Ledger contract only | No speech adapter exists, so no live audio is metered |
| Provider cost | `ai_provider_cost_entries` | Pricing module, after settlement | Separate table. Priced or unpriced |
| Customer credits | `customer_credits` | Nothing | Not recorded. See section 5 |

Attribution on every usage entry: organization, user, provider, model, task type, capability, agent, execution, workflow execution, workflow step, correlation identifier and timestamp.

## 3. Workflow and agent attribution

- A workflow step that runs an agent creates the agent execution with the workflow execution identifier and the step identifier. Both are stored on the agent execution (migration `c8e1f4a7b2d9`).
- Each model call made by that execution carries `workflow_id` (the workflow execution identifier), `workflow_step_id`, `agent_id` and `execution_id`. Agent and workflow attribution are distinct fields.
- **Retries and idempotency.** Each model call has a deterministic key, `agent:<execution>:<step index>:<attempt>`, used as the usage idempotency key. A call whose usage is already recorded is refused with `usage_already_recorded` and the provider is not called again. The workflow step itself is created with the key `workflow:<execution>:<step>`, so a retried step reuses the same agent execution.
- **Provider fallback.** The reservation records the planned route. Settlement replaces the provider and model with the ones that answered, so the usage entry and the cost entry name the fallback.
- Workflow usage in tests: `test_an_agent_run_started_by_a_workflow_step_is_attributed_to_the_execution_and_the_step`, `test_a_retried_workflow_step_reuses_its_agent_run_and_is_not_metered_twice`.

## 4. Provider cost and pricing versions

- **Registry.** `ai_provider_prices` holds versions per provider, model, usage unit and currency: the unit price in integer minor units, the quantity it applies to (`quantity_per_price`), the effective-from and effective-to times, the version number and a source reference.
- **No seeded rates.** The migration and the code contain no price. A price is created only by calling `create_price_version` from server-side code (for example an operator script run by the platform owner). No tenant API can change prices.
- **Versioning.** A new version closes the previous open version at its own effective-from time. Past versions are never edited, so historical costs keep the version they were calculated with. A database rule allows only one open version per provider, model and unit.
- **Pricing rule.** Price is looked up for the usage moment. The amount is `ceil(quantity × unit_price / quantity_per_price)` in minor units, so a partial unit is never free.
- **Cost entries.** Each settled usage unit produces one entry in `ai_provider_cost_entries`. A priced entry stores the provider, model, unit, quantity, price version, currency and amount. An unpriced entry stores the reason `no_price_version` and no amount. Entries are idempotent per organization and usage key.
- **Unknown is not zero.** Totals are reported per currency. Unpriced entries are counted and listed by unit, and never added as zero.
- **Currencies are never summed.** `provider_cost_totals` returns one total per currency.

## 5. Customer credits

- No customer credit conversion rate or contract is defined in any document reviewed. No credit rule is coded.
- Nothing writes a `customer_credits` usage entry, and no cost entry carries a credit value. A test proves that provider cost recording neither creates nor consumes customer credits.
- **Decision required:** the authoritative conversion rule from provider usage or cost to customer credits, and the billing currency it uses. This belongs to the SIBVO commercial contract (DFR1-005 external sign-off). Until it exists, customer credits are not charged.

## 6. Pages and audio

- **Pages.** OCR reads each scanned page as one gateway call with one image. The page is metered under `document_pages`, separately from `images`. Existing image metering is unchanged.
- **Behaviour change.** Page-by-page OCR now reserves the `document_pages` unit, so an organization must have a configured page budget before OCR runs. Without it, the call is refused with `budget_not_configured` (fail closed). This is the existing budget rule applied to a new unit. Tests that run OCR configure the page budget.
- **Audio.** The `audio_ms` unit and its pricing are accepted and preserved by the ledger. No speech adapter exists, so no live audio usage is recorded. This is deferred with the voice stories.

## 7. Budgets, idempotency and alerts (unchanged, re-verified)

- Server-side hard stop at the budget limit; concurrent reservations cannot exceed it.
- Settlement, release and reversal are idempotent and auditable. Repeated settlement with the same quantity changes nothing. A different quantity is a conflict.
- Alerts at 70, 85 and 100 percent by default, configurable per organization. One alert per crossing. Organization isolation holds.
- Existing tests: `test_usage_ledger`, `test_usage_ledger_hardening`, `test_usage_reservations`, `test_usage_reversal_audit`, `test_alert_thresholds`, `test_migration_alert_thresholds`, `test_usage_alert_delivery`, `test_migration_usage_reservation_hardening`.

## 8. Manual CRM

Manual CRM does not call the gateway. The budget gate applies only to AI and automation execution, so manual CRM keeps working when an AI budget is exhausted. This is verified for the capability layer by `test_capability_policy_gates.py`.

## 9. Tenant isolation and privacy

- Usage, cost entries and budgets are organization-scoped. Cost totals for one organization exclude another's entries (test: `test_provider_cost_totals_are_tenant_scoped`).
- Price versions are platform configuration. They hold no customer data.
- `ai_provider_cost_entries` is listed as not covered by export or deletion, pending DFR1-050. `ai_provider_prices` is configuration.
- Attribution fields hold identifiers only. No prompt, output, credential or secret is stored in usage or cost rows.

## 10. Database changes (migration `c8e1f4a7b2d9`)

- New table `ai_provider_prices` (platform configuration).
- New table `ai_provider_cost_entries` (organization-scoped cost ledger).
- New nullable column `ai_usage_events.workflow_step_id`.
- New nullable columns `agent_executions.workflow_execution_id` and `agent_executions.workflow_step_id`.
- Existing rows keep null in every new column. Downgrade refuses while price or cost rows exist.
- Validated on an isolated `dealflow` database on 127.0.0.1:5438: upgrade, downgrade and re-upgrade all exit 0.

## 11. Environment and external dependencies

- No new environment variables. No external provider is called. All tests use the scripted provider boundary.
- **External decisions still required:** (1) provider price source and price values, per provider, model and unit, with currency; (2) the customer credit conversion rule and billing currency (SIBVO commercial contract, DFR1-005 sign-off); (3) whether pages need a page budget as a configuration step before OCR is enabled for each organization.

# AI usage ledger and organization budgets (DFR1-017)

- **Status:** Partially complete. Acceptance criterion 1 (provider cost separated from customer credits) is structurally met, but no provider cost or customer credit is produced end to end. That needs a pricing and credit-conversion decision (section 4).
- **Owner:** governance (`app/governance/usage_ledger.py`). The reservation gate lives in `app/governance/execution_gate.py`.
- **Related:** `docs/architecture/ai-governance-and-usage-controls.md`, `docs/architecture/ai-usage-reservations.md`, `docs/architecture/ai-usage-alert-thresholds.md`, `docs/architecture/capability-policy-and-in-flight-behaviour.md` (DFR1-006).

## 1. What already existed and is reused

- Usage ledger (`AiUsageEvent`), per-unit budgets (`OrganizationUsageBudget`), alert settings (`OrganizationUsageAlertSettings`), and the reserve, settle, release, reverse and expire lifecycle in `usage_ledger.py`.
- Budget hard stop and reservation in the shared execution gate (gate 9), used by the AI gateway, AI tools, agents, multimodal extraction and knowledge.
- Idempotency keys per organization, request fingerprints, conflict detection, and the reservation reaper.
- Threshold alerts at 70, 85 and 100 percent by default, configurable per organization, announced once per crossing through the outbox (`ai.usage.threshold_reached`).
- Usage breakdown by capability, unit and provider, and the budget and alert-threshold API in `app/api/governance.py`.
- Test files: `test_usage_ledger.py`, `test_usage_ledger_hardening.py`, `test_usage_reservations.py`, `test_usage_reversal_audit.py`, `test_alert_thresholds.py`, `test_usage_alert_delivery.py`, `test_ai_gateway.py`, `test_execution_gates.py`.

## 2. Changes made in this story

- **Attribution on usage entries.** `UsageAttribution` (agent, workflow, execution, task type, provider, model) is carried from the caller to the reservation. Before this change, the gateway wrote usage with no provider, model, task type, agent or execution. Those fields were null on every AI usage row.
- **Provider and model at settlement.** Settlement records the provider and model that actually answered, replacing the planned route chosen at reservation. A fallback therefore appears correctly.
- **Agent attribution.** The agent runtime passes its agent and execution identifiers. Usage from agent model calls can be traced to the execution.
- **Test double update.** One existing gateway test replaces `settle_ticket` with a stub. The stub now accepts the new keyword arguments. Its assertions are unchanged.
- **New tests** (`backend/tests/test_usage_metering_attribution.py`, 5 tests): attribution persisted on the settled row; no agent recorded for plain calls; a provider answer with missing or partial usage metadata is not charged and its reservation is released; a settled call is counted once.

No migration was added. The new fields were already columns on `ai_usage_events`.

## 3. Acceptance criteria

| Criterion | Evidence | Status |
|---|---|---|
| Provider cost separated from customer credits | Separate units (`provider_cost_minor`, `customer_credits`) with separate budgets and breakdowns; no code sums units. Nothing yet writes either unit. | **Not met end to end** (section 4) |
| Budgets enforced server-side | Gate 9 hard stop; concurrent reservation tests; missing budget refuses | Met (existing tests) |
| Usage records idempotent | Repeat reservation, duplicate settlement, delayed duplicate report, duplicate reversal, idempotency conflict tests | Met (existing tests) |
| Configurable 70/85/100 alerts | Defaults 70, 85, 100; per-organization settings; once per crossing; organization isolation | Met (existing tests) |

## 4. Decisions required before criterion 1 can be met

1. **Provider pricing source.** No price table, pricing version or currency for providers exists. Without it, no `provider_cost_minor` entry can be computed honestly. Options are a configured price table per provider and model, or the provider's invoice reconciled later. This is a product and finance decision. No rates were invented.
2. **Customer credit conversion.** The contract that converts usage into customer credits is not defined in any document reviewed. Without it, no `customer_credits` entry can be produced. No conversion rate was invented.
3. **Document pages.** The `document_pages` unit exists but is never reserved or settled. Multimodal OCR currently meters each page as one image, because each page is a separate gateway call with one image. Reserving pages would add a new budget unit, and organizations without a configured page budget would be refused, which would change existing extraction behaviour. Decide whether pages get their own budget and whether existing organizations are configured first.
4. **Audio.** The `audio_ms` unit exists but no speech adapter exists. Audio metering is deferred with voice (DFR1-028).

## 5. Known gaps

- Provider cost and customer credits are not produced (section 4).
- Workflow attribution is not passed. Workflow steps that run agents do not carry a workflow identifier to the gateway, so `workflow_id` stays null on usage from workflows.
- Pages and audio are not metered (section 4).
- Provider usage that is missing or partial is refused and released, not estimated. This is the fail-safe behaviour, but it means a provider that omits usage is never charged.

## 6. Privacy and security

- `ai_usage_events` is in the export set (`table_inventory.py`). `organization_usage_budgets` and `organization_usage_alert_settings` are configuration. No new table was added.
- Attribution fields hold identifiers only: agent, workflow, execution, provider, model and task type. No prompt, output, credential or secret is stored in usage rows.
- Usage and budget reads are organization-scoped (tests: cross-tenant budget reads and changes refused).

## 7. Environment and external dependencies

- No new environment variables.
- No external provider was called. All tests use the scripted provider boundary from `test_ai_gateway.py`. Nothing here is evidence of live provider usage.

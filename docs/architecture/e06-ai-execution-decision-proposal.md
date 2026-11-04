# E06 AI execution architecture: decision proposal

Status: **PROPOSAL. Nothing in this file is approved.** Each recommendation names the owner who must approve it. Every
number marked "proposal" is a candidate for product approval and is not configuration. No production value is set by this
document.

Checked on `origin/develop` at `6eab89a`, and on the feature branches `feature/DFR1-E06-ai-gateway-core` (`17ce46a`) and
`feature/DFR1-E07-typed-tool-registry`.

Sources: ADR-0029 (AI execution and disabled-by-default policy), ADR-0032 (provider registry and lifecycle),
`e13-ai-actor-permission-proposal.md`, `ai-governance-and-usage-controls.md`, `sibvo-dealsflo-entitlement-contract.md`,
the execution gate (`app/governance/execution_gate.py`), the usage ledger (`app/governance/usage_ledger.py`), the provider
registry (`app/providers/registry.py`), and the Release 1 backlog.

---

## 1. Current state (facts from code)

| Gate or control | State today | Effect on AI |
|---|---|---|
| Entitlement (SIBVO snapshot, `ai_gateway`) | Implemented, signed, fail closed | Required; passes when SIBVO grants it |
| Organization switches (master and capability) | Implemented | Required; default off |
| Provider readiness | Implemented (ADR-0032); live verification never performed | No provider is ready in any environment today |
| Actor permission | Looks for `ai.execute`, which is not catalogued | Every AI request is refused (`permission_denied`) |
| Resource | AI capabilities always refused: no AI resource store exists | Every AI request is refused (`resource_required` or `resource_not_found`) |
| Consent | Implemented for channel capabilities | Not reached for AI today |
| Rate | No rate rule for any AI capability (`rate_limit_not_configured`) | Every AI request is refused |
| Budget and usage | Implemented: reserve, settle, release, reaper | Not reached today |
| Approval | Implemented for exact payloads | Not required by any capability today |

Consequence: **AI execution is closed in every environment**, by design. Three independent decisions must land before any
AI capability can execute: the actor key, the AI resource store with its publish state, and an approved AI rate rule. Each is
a product or architecture decision, not a code gap. This document proposes all three.

The DFR1-015 gateway (branch `feature/DFR1-E06-ai-gateway-core`) and the DFR1-018 tool registry (branch
`feature/DFR1-E07-typed-tool-registry`) both run through the same gate, so they are closed in the same way.

---

## 2. AI actor permission key and authorization model

**Recommendation (for approval by the release owner and security owner).**

- Key: `governance.ai.execute`. The `governance.` prefix matches every other governance key, and it avoids the `ai.` prefix
  that capability keys use.
- Two gates, both required for a human caller:
  1. The **target permission** that the action would need by hand (for example `contacts.read` for the contact tool, or
     `deals.create` for deal automation). This is ADR-0029 gate 5 and the existing automation precedent.
  2. The **AI key**, which decides who may start AI work at all.
- Grants: the Owner role receives it automatically. The Admin role receives it by default, because Admin already holds
  every non-owner-only key. Manager and Member do not receive it in the default templates. Adding it to Manager is a separate
  decision, and it requires a backfill for existing organizations.
- Owner-only status is the stricter alternative. The recommendation is not owner-only, so administrators can run AI when the
  organization has enabled it.
- Systems and agents: a system actor is refused, as today. An agent run has no grant of its own. It acts with the
  permissions of the user who started it, checked on each gated step. No agent may grant itself a permission.
- Default deny: a key missing from the catalogue, or from the user's roles, is refused. This is current behaviour.

The full model, with the test list, is in `e13-ai-actor-permission-proposal.md`. This document adopts it and changes one thing:
the production code must replace `ai.execute` with the approved key, and the test seam that grants a key in tests must be
removed once the key is catalogued.

**Owner:** release owner (scope and grants), security owner (permission model).

---

## 3. AI rate rules

No rate rule is approved. The gate refuses every AI capability until one exists, because a missing rule is a closed state by
design.

Proposal, requiring product approval. The numbers are placeholders for discussion. They are not configuration, and they are
not SIBVO limits. SIBVO's feature-limit table (contract section 6) states that no numeric limit is enforced for any feature.

| Rule | Scope | Proposed window | Proposed limit | Rationale |
|---|---|---|---|---|
| AI requests per user | per user per capability | 1 minute | 20 | Stops runaway loops from one person or agent |
| AI requests per organization | per organization per capability | 1 minute | 300 | Protects shared capacity |
| Concurrent AI calls | per organization | in flight | 8 | Bounds provider load and cost exposure |

Units other than requests (tokens, pages, images) are governed by the usage budget (DFR1-017), not by these rules. Each rule
needs an approved owner, an approved value, and a tested reset behaviour before it is registered.

**Owner:** product (values), security (abuse controls), infrastructure (capacity).

---

## 4. First provider and sandbox configuration

**Recommendation.** OpenAI as the first LLM provider, because it is the only adapter implemented (ADR-0032 D1). The
OpenAI adapter covers text and embedding tasks through a mock boundary in tests. Live use needs the following before any
non-test call:

- **Approved data-use terms** for the provider (E01 matrix, row 5). Without them, no customer data may be sent. This is the
  blocking item. Test prompts must contain no personal data.
- **A sandbox organization** in the non-production environment, with its own provider account and a spend cap set at the
  provider. The cap value is a product and finance decision, not an engineering default.
- **The credential** stored through the existing provider credential endpoint, encrypted with the environment keyring. The
  credential is never written to a file, a log, or a test.
- **`PROVIDER_LIVE_ADAPTERS_ENABLED=true` only in the named sandbox environment**, never in CI (ADR-0032 D6).
- **Routes** chosen by the organization owner through the route API (`PUT /api/v1/ai/gateway/routes/{task}`), starting with
  one text model and one embedding model that the owner names.
- **Recorded sandbox verification**: one successful verification, its date, the model names, and the key identifier, stored
  as evidence before DFR1-015 may be marked verified.

Until these exist, the adapter refuses with `live_adapter_disabled` and makes no network call, which is the state now.

**Owner:** infrastructure (environment, keyring), security (data-use review), product (provider choice and spend cap).

---

## 5. AI resource ownership and tenant isolation

An AI resource is the thing an agent or workflow executes, and the gate's resource check refers to it. This is the largest
missing piece, and it is owned by DFR1-019 (agent definitions, versioning and runtime).

Contract:

- **Ownership.** Every AI resource row carries `organization_id`. A resource belongs to one organization and can never be
  shared across organizations.
- **Publish state.** Only a published, active version can execute. Draft and paused versions are refused. Published versions
  are immutable (ADR-0029); an edit creates a draft.
- **Identity.** The resource identifier passed to the gate is the resource's own identifier. An identifier from another
  organization returns the same answer as a missing one (`resource_not_found`), so the gate reveals nothing across tenants.
- **Lookup.** The resource check reads the resource by `(organization_id, id)` and checks its publish state in the same query.
- **Tests.** Cross-tenant identifier, draft, paused, and archived resources are each refused, and each refusal is audited.

Until DFR1-019 exists, the resource gate refuses every AI execution by design. The DFR1-018 tool registry uses the resource
identifier `tool:<key>`, which the resource gate also refuses today.

**Owner:** product (resource model), security (isolation review).

---

## 6. How agents and workflows use DFR1-015 and DFR1-018

- **Model calls.** An agent step that needs a model calls `app.ai_gateway.service.execute` with the initiating user's
  context, the capability for that step, and the resource of the agent version. It never calls a provider directly.
- **Tools.** An agent step that needs data calls `app.ai_tools.service.invoke_tool` with a registered tool key and validated
  arguments. The agent cannot name a handler, a query, or code (ADR-0029: typed tools only).
- **Ordering.** For a model call that follows a tool call, each step passes the gate on its own. A later step is refused if an
  earlier permission or switch has since been revoked, because each gate reads current state.
- **Attribution.** Every model call and every tool call records the initiating user, the capability, the agent or workflow
  identifier, and the correlation identifier of the run.
- **Retries and timeouts.** Model calls retry only transient provider failures, within a bound. Tool calls do not retry.
  Both are bounded in time.

**Owner:** product (agent behaviour), architecture (run model), DFR1-019 implementation.

---

## 7. Usage reservation, settlement, failure handling and audit

Implemented on the DFR1-015 branch:

- Reservation happens inside the gate, before the provider call. The gateway passes the estimated output tokens and input
  tokens to the gate's budget units.
- Settlement uses the provider's reported usage. Units the provider did not report are released.
- A failed call with no usage releases the whole reservation.
- A provider answer whose usage cannot be settled is withheld (`usage_settlement_failed`). The caller must roll back, so no
  output is returned that was not metered.
- The reaper (`expire_stale_reservations`, run by the worker under `--serve`) releases reservations left open past expiry.

Required and not yet implemented:

- **Outcome audit for model calls.** Usage entries show settled and released amounts, and the gate records its decision. A
  requested and completed outcome record (the WP3 pattern) is not yet written for each model call. Required before DFR1-015 can
  be Done.
- **Tool audit.** Implemented on the DFR1-018 branch: requested and completed records, argument names only, and a denial record
  for every refusal, including attempts from outside the tenant.
- **Usage metering for tools.** Not applicable today. The read-only tool does not consume model tokens. A tool that calls a
  provider would be metered through the gateway, not the tool layer.
- **Budget thresholds and alerts.** Implemented for the usage ledger (70, 85 and 100 percent, in-app).
- **Worker dependency.** The reaper runs only under `--serve` (D7). Without a running worker, reservations stay open until
  the budget is exhausted. Recorded as a known limitation.

**Owner:** architecture (audit pattern), infrastructure (worker, D7).

---

## 8. Decisions and owners

| # | Decision | Recommendation | Owner | Blocks |
|---|---|---|---|---|
| 1 | AI actor key and grants | `governance.ai.execute`, two gates, Admin by default | Release owner, security owner | Every AI execution |
| 2 | AI rate rules | Proposal values in section 3, after product review | Product | Every AI execution |
| 3 | AI resource model and publish state | Org-owned, published-only, identical cross-tenant answers | Product, security | Every agent and workflow execution |
| 4 | First provider and data-use terms | OpenAI, after data-use approval | Security, product | Any live call |
| 5 | Sandbox spend cap and environment | Set by finance and infrastructure | Infrastructure, finance | Any live call |
| 6 | Maintenance worker deployment (D7) | Run `--serve` in each environment | Infrastructure | Reservation expiry |
| 7 | Outcome audit for model calls | WP3 requested and completed pattern | Architecture | DFR1-015 Done |

---

## 9. What this document does not change

- No permission key, rate rule, entitlement key, endpoint or configuration is added or changed here.
- No story status changes. DFR1-015 and DFR1-018 stay Partial until their open items are verified.
- E01 data-use approval remains open. No provider call is made.

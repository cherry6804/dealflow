# Rate Limits, Usage Budgets and Provider Quotas

**Status:** implemented for deal-created automation (E13 hardening). Not complete for AI execution, which is not built yet (DFR1-015, DFR1-016).
**Owner:** E13 governance. **Related:** ADR-0029, `docs/architecture/ai-governance-and-usage-controls.md`.

Three different limits govern executions. They answer different questions, are enforced in different places, and must not be merged into one counter.

| | Rate limit | Usage budget | Provider quota |
|---|---|---|---|
| Question | How many executions may start in a short window? | How much metered usage may an organization consume this month? | How much may this provider's account consume? |
| Unit | Executions (requests) per window | Tokens, pages, audio, cost, per unit and month | Provider-defined (requests per minute, tokens per minute, spend cap) |
| Enforced by | Dealsflo, server-side, before the execution | Dealsflo, server-side, through the E13 usage ledger | The provider. Dealsflo observes it and adapts. |
| Storage | `execution_rate_limit_windows` (counters only) | `ai_usage_events` and `organization_usage_budgets` (E13 ledger) | Not stored by Dealsflo, except the provider's response signals |
| Records usage | No | Yes, idempotently | Yes, through the ledger, as actual usage |
| Resets | At the end of each window (default 1 minute) | Monthly (UTC) | Provider-defined |
| Denial | 429 with `Retry-After` (or a denied decision internally) | Denied with a budget reason code | Provider error (429 or quota error), mapped to a safe, retryable error |

## Rate limits (this change)

- **Scopes:** each execution type has an organization limit and an actor limit. Both must allow the request. The actor scope is skipped when there is no acting user (internal execution).
- **Algorithm:** fixed window. Each attempt increments one counter row per scope with a single `INSERT ... ON CONFLICT DO UPDATE` on PostgreSQL. The row lock makes concurrent attempts serialize, so the count is exact.
- **Denied attempts count.** A denied request still increments both counters. Repeated attempts cannot slip past a window.
- **Tenant isolation:** every counter row carries `organization_id`, and the unique key includes it. Organizations have independent counters.
- **Defaults** (in `app/rate_limits/policy.py`): `automation.deal_created` allows 600 per minute per organization and 120 per minute per actor. These are starting points. Per-organization overrides are not part of this change.
- **Retention:** counters older than two days are removed for the organization being updated. They are operational state.
- **No usage is recorded here.** The limiter never writes to the usage ledger, so a rate-limited attempt is not counted as usage and an allowed attempt is not double-counted as usage.

### Enforcement points

| Entry point | Gate order | Status |
|---|---|---|
| Deal-created automation (`execute_deal_created_automations`) | Entitlement, organization and child switches, active rule, actor permission, **rate limit** | Enforced |
| AI gateway, agent runtime, workflow runtime, voice, channel sending | Not built | Not enforced. Each must include the rate-limit gate when built. |

The rate limit runs after the policy gate and only when the organization has active rules. A request denied by policy uses no rate budget. A rate-limited deal-created event creates no executions, the deal is still saved, and an audit event (`rate_limit.denied`) records the scope, limit and retry time. Manual CRM work is never blocked.

### Failure behavior (fail closed for the protected execution)

- If the counter store raises a database error, or the rule is not configured, the decision is "unavailable". The protected execution does not run. The error is caught inside a savepoint, so the surrounding transaction stays usable.
- The unavailable decision is not audited, because the audit write may depend on the same failing store. This is a known limitation.
- Non-PostgreSQL databases fail closed, because the atomic upsert is PostgreSQL-specific.

### Structured responses

`app/rate_limits/responses.py` builds the application's standard error envelope:

- Rate limited: HTTP 429, `Retry-After` header, code `RATE_LIMITED`, details with execution type, scope, limit and retry seconds.
- Unavailable: HTTP 503, `Retry-After: 30`, code `RATE_LIMIT_UNAVAILABLE`, which does not claim that a limit was exceeded.

No public endpoint uses this response yet. The automation path records the denial as an audit event instead of returning an error, because the deal creation must still succeed.

## Usage budgets (E13, unchanged)

Budgets are monthly limits on metered usage per organization and unit. They are enforced through `app/governance/usage_ledger.py`:

- `reserve` before a metered call and `settle` with actual usage after it, keyed by an idempotency key, so retries never double-count.
- Thresholds at 70, 85 and 100 percent produce in-app alerts, delivered by the outbox worker when it runs.
- No production producer exists yet. Budget enforcement for AI calls will be exercised by the AI gateway (DFR1-015).

Rate limits never replace budgets. A request can pass the rate limit and still be denied by a budget, and the reverse is also true.

## Provider quotas (external)

Providers enforce their own limits. Dealsflo cannot raise them.

- The provider adapter must map provider rate-limit and quota responses to normalized, retryable or non-retryable errors.
- Retries use bounded backoff and respect the provider's `Retry-After` when present. The gateway must not retry a quota error in a tight loop.
- Provider quotas do not replace Dealsflo's limits. A provider may allow a call that Dealsflo's budget forbids, and the reverse.
- Provider health monitoring is a separate prerequisite (ADR-0029 gate 3) and is not implemented in this change.

## Limitations of this change

- Per-organization overrides of the default limits are not configurable yet.
- Counters are per execution type. Adding an execution type requires a rule in `policy.py`.
- The unavailable path is not audited (see above).
- The concurrency guarantee is verified by a 40-attempt concurrent test (exactly the configured limit is allowed). It is not a load test.
- Clock-based windows assume the application servers' clocks are reasonably synchronized (within seconds).

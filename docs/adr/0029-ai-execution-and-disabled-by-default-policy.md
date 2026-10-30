# ADR-0029: AI Execution and Disabled-by-Default Enablement Policy

- **Status:** Proposed
- **Date:** 2026-10-30
- **Decision Owners:** DealFlow Engineering (approval pending)
- **Jira:** DFR1-006, DFR1-036

## Context

Dealsflo's Release 1 scope includes AI agents, workflows, voice, predictions and generative features. Those capabilities can contact customers, change CRM records and spend money. They must be governed, and manual CRM use must not depend on them.

## Decision

No optional AI or automation capability executes unless every applicable gate passes. The gates come from the Release 1 policy sheet:

1. SIBVO entitlement allows the capability.
2. The organization has enabled it explicitly. A master switch is not a substitute for the individual setting.
3. The required provider is connected, verified and healthy.
4. The agent or workflow is configured, tested, published and active. Draft and paused resources never execute.
5. The initiating user or service identity has permission on the target.
6. The tool or action is allowlisted, typed, validated, and scoped to the tenant.
7. Consent, opt-out, DND, messaging-window and calling-hour policies pass.
8. Usage budgets, rate limits, concurrency and step or time limits pass.
9. Required human approval exists for the exact payload and version.
10. Disabling a capability blocks new executions immediately. In-flight work is cancelled or finished according to policy.

Rules that follow:

- The frontend never enforces anything. Every gate is checked on the server.
- Manual CRM operations and inbound event storage keep working when AI is off.
- Published agent and workflow versions are immutable. Edits create drafts.
- Simulation and dry runs produce no external side effects.
- Agents call domain services through typed tools only. No arbitrary SQL, shell, code execution or self-granted permissions.

E01 records the policy. E06, E07, E08, E11 and E13 implement it.

## Alternatives Considered

- **Allow AI by default and let admins opt out:** rejected. It violates the locked product decision.
- **Treat a UI toggle as authorization:** rejected.

## Consequences

- Every AI action has an auditable reason for being allowed or denied.
- Gate failures produce user-visible reasons (entitlement, enablement, consent, budget, approval) instead of silent no-ops.

## Security Considerations

- External content (messages, documents, web pages) is untrusted input.
- Approvals bind the exact payload, target, version and approver, and they expire.
- Prompt injection is tested against tool allowlists and output validation.

## Operational Considerations

- Budgets are enforced server-side with threshold alerts.
- A kill switch must take effect within one request cycle.

## Compatibility Considerations

No AI capability exists today, so nothing is migrated. Any future AI setting must default to disabled.

## Related Decisions

ADR-0027 (entitlement), ADR-0026 (outbox), ADR-0028 (channels).

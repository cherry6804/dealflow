# ADR-0029: AI Execution and Disabled-by-Default Enablement Policy

- **Status:** Accepted
- **Date:** 2026-10-30 (proposed and accepted on this date, with amendments A to E below)
- **Decision Owners:** DealFlow Engineering, approved by the product owner on 2026-10-30
- **Jira:** DFR1-006, DFR1-036

## Context

Dealsflo's Release 1 scope includes AI agents, workflows, voice, predictions and generative features. Those capabilities can contact customers, change CRM records and spend money. They must be governed, and manual CRM use must not depend on them.

Existing organizations already had deal-created automation rules before this decision. The database records who last updated a rule, but not which action or interface enabled it. Nothing in the existing data proves an explicit opt-in, so no existing organization may be treated as having opted in.

## Decision

### Amendment A. Default policy

All optional AI and automation capabilities are disabled by default, for new and existing organizations alike. An organization can use one only after an authorized organization administrator explicitly enables it.

No optional AI or automation capability executes unless every applicable gate passes. The gates come from the Release 1 policy sheet:

1. SIBVO entitlement allows the capability (verified from SIBVO's access snapshot, failing closed).
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

### Amendment B. Existing organization migration

No automatic enablement is based on active rule status, on a recorded last-updating user, or on any other inferred signal. Existing organizations require an explicit opt-in recorded under the policy.

Concretely:

- The migration sets no capability to enabled for any organization.
- Existing automation rules are preserved with their configuration. They do not execute until the organization's administrator enables the capability.
- The migration executes no rule and creates no notification.
- Rolling the migration back never re-enables a capability. A rollback refuses to run if an administrator has changed a switch, so no administrator change is discarded.

### Amendment C. Transactional email exemption

The following essential account communications remain operational independently of optional AI and automation capabilities:

- Email verification.
- Password reset.
- Necessary account invitations.
- Essential account security notifications.

This exemption is narrow. It does not bypass:

- Authentication.
- Tenant authorization.
- Rate limiting and abuse protection.
- Audit logging.
- Email delivery security.
- Applicable legal requirements.

Marketing, promotional, AI-generated and automated customer communications are not covered by this exemption. They remain subject to the applicable capability, consent, channel and policy checks.

### Amendment D. Compatibility

- **Existing rules.** Preserved with their configuration, status, creator and history. Not deleted, not rewritten, not executed by migration.
- **Historical records.** Execution history is kept as written. The migration does not read or change it.
- **Existing organizations.** Start with every optional capability disabled. Their CRM work is unchanged.
- **New organizations.** Start disabled.
- **Enablement.** Recorded on each change with the organization, actor, capability, previous state, new state, timestamp, policy version, source, and correlation ID. Disablement and revocation are recorded the same way.
- **Migration history.** Migration `f3a7b9c1d2e4` once enabled automation for every organization. Migration `i7f2c9d4e1a8` removes those unevidenced grants and leaves nothing enabled.

Any future AI setting must default to disabled.

### Amendment E. Enforcement

**Enforced now:**

| Entry point | Gates enforced |
|---|---|
| Deal-created automation, called from the deal creation API | 1 (SIBVO entitlement for `workflow_automation`, fail closed), 2 (organization master and child switches), 4 (rule is ACTIVE), 5 (deal creation requires `deals.create`, checked by the API before automation runs) |

Gates 3, 6 (for internal actions), 7 (for internal actions), 8 (no billable action), and 9 (no approval configured) are not applicable to deal-created automation, whose actions are internal follow-ups and in-app notifications.

**Not yet implemented, and not claimed:**

- AI gateway (DFR1-015), agent runtime (DFR1-019), workflow runtime, voice operations (DFR1-027, DFR1-028), channel sending (WhatsApp, SMS, outbound email campaigns), scheduled execution, and outbox handlers that perform optional work.
- Gate 3 (provider health), gate 7 (consent and channel policy) and gate 9 (approval) for every capability.
- Gate 8 (budget enforcement before billable execution) for AI capabilities.

Each unimplemented entry point must enforce the complete gate set when it is built. Until then it does not run.

## Alternatives Considered

- **Allow AI by default and let admins opt out:** rejected. It violates the locked product decision.
- **Treat a UI toggle as authorization:** rejected.
- **Treat an active rule with a recorded last-updating user as opt-in:** rejected. The recorded user does not show which action or interface enabled the rule.

## Consequences

- Every AI action has an auditable reason for being allowed or denied.
- Gate failures produce user-visible reasons (entitlement, enablement, consent, budget, approval) instead of silent no-ops.
- Existing organizations stop running deal-created automation until an administrator enables it. This is a deliberate behaviour change that must be communicated to customers before release.

## Security Considerations

- External content (messages, documents, web pages) is untrusted input.
- Approvals bind the exact payload, target, version and approver, and they expire.
- Prompt injection is tested against tool allowlists and output validation.
- SIBVO entitlement is read from the attested session snapshot. An unavailable or unverifiable snapshot denies the capability.

## Operational Considerations

- Budgets are enforced server-side with threshold alerts.
- A kill switch must take effect within one request cycle. Turning a master switch off takes effect on the next evaluation.

## Compatibility Considerations

See Amendment D.

## Related Decisions

ADR-0027 (entitlement; still Proposed), ADR-0026 (outbox; still Proposed), ADR-0028 (channels; still Proposed).

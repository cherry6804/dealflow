# Governance execution controls (WS6, WP6–WP8)

This document describes what is enforced today on AI and automation execution paths, what is not, and what
must exist before AI can run in production. It is written against the code on this branch. Where a control is
not implemented, the text says so.

## 1. Execution gate lifecycle

Every AI entry point calls `require_ai_execution` (`app/governance/ai_execution.py`). Deal-created automation
calls `evaluate_execution` directly (`app/automation_rules/execution_service.py`). Both reach the same
function, `evaluate_execution` in `app/governance/execution_gate.py`, so sync and background callers are checked
identically. Gates run in this order, and the first failure decides:

| # | Gate | Source of truth | State today |
|---|---|---|---|
| 1 | Entitlement (SIBVO plan) | SIBVO organization snapshot (AI); session plan (automation) | Enforced. See section 2. |
| 2 | Organization master and capability switches | `organization_capability_settings` | Enforced. See section 3. |
| 3 | Provider configuration and health | provider connections | Enforced for capabilities that require a provider. |
| 4 | Actor permission (or refusal of a system actor) | membership roles | Enforced. See section 4. |
| 5 | Resource | AI resource store | Fail closed: no store exists, so AI resources are refused. |
| 6 | Consent | consent store | Fail closed: no store exists. See section 7. |
| 7 | Approval (payload-bound) | approval store | Fail closed: no store exists. See section 7. |
| 8 | Rate limit | `app/rate_limits` | Enforced for deal-created automation. AI has no approved limit. See section 5. |
| 9 | Budget reservation | `app/governance/usage_ledger.py` | Enforced: reserved before execution, settled or released after. |
| 10 | Audit | `app/audit/independent.py` | Every decision is written in its own transaction before work runs. |

A denial at any gate raises `AiExecutionDenied` (AI) or returns no executions (automation). Nothing runs. A denial
is recorded durably. If the record cannot be written, the decision fails closed: nothing runs and no reservation is
kept.

No AI capability can pass the gate today. This is intended. Gates 5 to 7 refuse until their stores exist, and the
`ai.execute` permission is not in the catalogue.

## 2. Entitlement refresh and expiry (WP6)

Authority for AI entitlement is SIBVO's signed organization snapshot (`app/governance/org_entitlement.py`).

- **Validity.** A snapshot is valid for at most 30 seconds (`MAX_SNAPSHOT_LIFETIME`). It is never valid at or after
  its `expires_at`. There is no grace period on expiry.
- **Revalidation.** A stored snapshot is served from the cache until it is due, which is
  `sibvo_org_entitlement_revalidation_seconds` after its last fetch. The default is 30 seconds. The setting is
  validated at startup and must be between 1 and 30. It cannot exceed the snapshot lifetime.
- **Refresh failure.** When a due snapshot cannot be refreshed, the stored snapshot still authorizes while it has not
  expired. After expiry, the decision is a denial, with reason `snapshot_expired` or `snapshot_unavailable`.
- **Backoff.** A failed refresh opens a backoff window: 5 seconds, doubling, capped at 300 seconds. Backoff limits how
  often SIBVO is asked. It never extends authorization. 300 seconds is a retry ceiling, not a grace period.
- **Stale answers.** A SIBVO answer older than the stored snapshot never replaces it (`snapshot_stale`).
- **Clock skew.** A snapshot issued up to 5 seconds ahead of this process is accepted. A later issue time is refused
  (`not_yet_valid`). Expiry is strict.
- **Binding.** Organization, product, signature (HMAC-SHA256 with the shared key and key identifier), `attested`, and
  snapshot version are all checked. A failure is never stored.
- **Concurrency.** Refreshes run under a per-organization, per-product advisory lock. Concurrent decisions produce one
  SIBVO call.
- **SIBVO denial.** An explicit `active: false` removes any grant held from an earlier snapshot.

The `ai_gateway` key and the commercial plan mapping are unchanged.

**Automation** entitlement (`workflow_automation`) is read from the attested session context captured when the request
starts. This is a known limitation: a plan change made during one request is not observed until the next request. See
section 6.

## 3. Organization and capability switches

- Every capability is off until an organization turns it on (`CapabilityDefinition.default_enabled` is always False).
  Existing organizations are disabled too. Nothing is enabled by a deploy or a migration.
- The organization AI master switch and the automation master switch sit above their capabilities. A capability runs
  only if its master and its own switch are on.
- Turning a switch on does not make a capability run. The UI shows the effective decision for each capability, and
  "Running" appears only when every gate passes.
- Changing a switch requires `governance.capabilities.manage`, which is owner-only. Each change is audited.
- The frontend shows the switches, the plan verification state, and the reason each capability cannot run. The
  backend enforces everything on every request. The frontend never decides.

## 4. Permission and target-owner authorization (WP5)

Automation actions run with the authority of people, not of the event:

- **Activation.** The activator needs `automation.update` and the permission of every action in the rule. A denial
  returns 403 with a stable reason and the rule stays a draft.
- **Execution.** For each action, the rule's activator and the deal owner must each hold the action's permission,
  read from the database at that step. The user who created the deal does not authorize the action.
- **Action mapping.** `ACTION_PERMISSIONS` in `app/automation_rules/authority.py` is the only mapping. Unknown action
  types are refused.
- **Tenant boundary.** Rules, deals and permissions are checked against the organization. A permission held in another
  organization does not count.
- **Initiating user.** The user who triggers the event must hold `deals.create`, re-checked at each step (section 6).

## 5. Budget, rate and concurrency

- **Budget.** Usage is reserved before execution, settled with actual usage afterwards, and released if work stops
  early. A reservation that would exceed the budget is refused, so the budget is a hard stop at 100 percent. Reservations
  expire after 15 minutes if never settled (the outbox worker reaps them).
- **Rate.** Deal-created automation uses the existing organization and actor rate limits. A denial creates no
  executions and is recorded. AI has no approved rate rule, so an AI capability with no rule is refused.
- **Concurrency.** Not implemented. No concurrency limit has been approved. Budget and rate counters serialize through
  row locks, which is the only serialization today.

## 6. In-flight revocation (WP8)

For automation, each step is preceded by a re-check of the governing gates against the database: the organization and
capability switches, the provider, the initiator's permission, and the resource. The re-check also runs before the first
step, in addition to the initial gate.

- If a re-check fails, that step is not started, and no later step or later rule for the same event is started.
- The stop is recorded in its own transaction (`execution.stopped`, decision denied, with the gate, the reason, the rule,
  the deal and the step index) before anything is skipped. If that record cannot be written, the step does not run.
- The execution is marked `FAILED` with the reason. Completed steps keep their results. The stop record survives a
  rollback of the work it stopped.
- A replayed event does not create a second execution (the event and rule uniqueness constraint).
- Authority is read again for each step. A target-owner or activator permission removed mid-run is refused at the
  next step as an authority denial, which is a step failure, not a stop.

**Not covered by in-flight revocation:**

- **Session-attested plan.** A plan change for `workflow_automation` during one request is not seen. It is picked up on
  the next request. Closing this requires re-reading the plan per step from a verified source, which does not exist yet.
- **External actions already submitted.** None exist on the automation path. Follow-ups are internal records. If an
  external action is added, a submitted request cannot be recalled, and the system must say so rather than claim a
  recall.
- **Budget, consent and approval.** The automation path has no reservation, consent or approval step boundary, so there
  is nothing to revoke mid-run. These controls apply to AI execution once the AI path has steps and stores.

## 7. Consent and approval limitations

- **Consent.** A capability that requires consent is refused with `consent_not_configured`. No consent store exists, so
  no consent can be recorded or revoked.
- **Approval.** Customer-facing capabilities (voice and channels) require an approval bound to the exact payload. No
  approval store exists. Approval expiry and revocation are not implemented, because there is nothing to expire.
- Neither control is a production capability today.

## 8. Worker operating requirements

- The outbox worker (`app/outbox/runtime.py`) runs reservation expiry and verification scheduling. It must be running
  for expired reservations to be released.
- Background execution follows the same gates. A system actor is refused at the actor gate, because no trusted service
  identity exists. Background AI execution is therefore not available.
- Workers must not hold a principal from another request. Attribution for a system actor requires a registered
  capability, and no service identity is registered for AI.

## 9. Operational diagnostics and recovery

- `GET /api/v1/ai/governance/entitlement-status` (also under the legacy `/api/v1/governance/...` path) reports the
  snapshot state (`valid`, `due_for_revalidation`, `expired`, `missing`), the last fetch and expiry instants, the failure
  count, whether backoff is active, the revalidation interval, and whether the signing key is configured. It never returns
  the snapshot body, a signature, or the key. It requires `governance.capabilities.read`.
- **Recovery after a SIBVO outage.** Nothing needs to be done. The next decision after backoff asks SIBVO again. Access
  returns when SIBVO answers with a valid, attested snapshot for the organization.
- **Recovery after a missing signing key.** Configure the shared key and restart. Until then, the state is `missing` and
  AI stays off.
- **Recovery after a stop.** The stopped execution is `FAILED` with its reason. Replaying the event does not re-run it.
  The organization or the person must restore the condition, and a new event is needed to run the rule again.

## 10. Remaining external dependencies and production activation

AI execution must not be enabled in production until each of these exists and is verified:

1. A live cross-repository run of the SIBVO organization entitlement contract. Fixture tests prove only Dealsflo's
   reactions. The live contract run is recorded separately.
2. A trusted service identity for background execution, with a verified entitlement path. None is invented here.
3. An AI resource store, with lifecycle (activation, deactivation, deletion).
4. A consent store, with capture, revocation and per-contact channel policy.
5. An approval store, with payload binding, expiry and revocation.
6. An `ai.execute` (or per-capability) permission defined in the catalogue and granted through roles.
7. Approved AI rate limits and concurrency limits.
8. A verified provider connection and health check for each provider-backed capability.
9. A live (non-fixture) check of the revalidation and backoff behaviour against SIBVO in a staging environment.

Out of scope for WS6: DFR1-050, DFR1-053, the model gateway, the agent runtime, voice and channel integrations, and
pricing.

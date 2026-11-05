# Capability policy, default-off behaviour and in-flight revocation (DFR1-006)

- **Status:** Implemented on `feature/DFR1-006-capability-policy`. Gates 1 to 4, 8, 9 and 10 are enforced today. Gates 5 to 7 are enforced as fail-closed checks where the owning store is incomplete. See the gate table.
- **Owners:** governance (`app/governance/`). Entitlement is owned by SIBVO (ADR-0027). This document does not change that ownership.
- **Related:** ADR-0028 (channel gateway), ADR-0029 (AI disabled by default), ADR-0032 (provider connections), `docs/architecture/ai-governance-and-usage-controls.md`.

## 1. Principle

No optional AI or automation capability runs unless every applicable gate passes. A denial stops work, records a reason and never falls back to another path. Manual CRM operations are not capabilities. They are governed by ordinary tenant scope and permissions, and they keep working when every optional capability is off.

## 2. Where the policy lives (one engine)

| Component | Role |
|---|---|
| `app/governance/capabilities.py` | The catalogue. Every capability is listed, defaults to disabled, and declares its parent, provider, consent, approval and entitlement requirements. |
| `app/governance/policy.py` (`evaluate_capability`) | Gates 1 to 3 and the provider and consent declarations. Reads switches with a fresh read on every check. |
| `app/governance/execution_gate.py` (`evaluate_execution`, `revalidate_ticket`) | The shared gate for every AI and customer-impacting execution. Runs gates 1 to 10 in fixed order. Used by the AI gateway, AI tools, agents, automation rules, workflows (through the policy engine) and AI execution. |
| `app/api/governance.py` | Reads and changes switches. Requires `governance.capabilities.read` or `governance.capabilities.manage`, and the manage path is owner-only. Every change is audited and versioned. |

No module defines its own capability check. Callers go through these functions.

## 3. Default-off behaviour

- Every capability returns `default_enabled = False`. A missing switch row is treated as disabled. A new organization has no rows and therefore nothing enabled.
- An unknown or invalid capability key returns `unknown_capability` and is denied. Through the API it returns not found and creates no row.
- A missing or invalid SIBVO entitlement snapshot denies. A null or empty entitlement feature denies (`entitlement_not_defined`).
- A missing provider connection denies (`provider_not_connected`). A stale or revoked connection denies at the gate boundary.
- A capability that requires consent, or approval, or a resource, is refused when the owning store is missing or the subject is absent.

## 4. Gate table

| # | Gate | Where enforced | Implemented | Fail-closed behaviour | Tests (existing) |
|---|---|---|---|---|---|
| 1 | Platform entitlement | `policy.py` (AI: `org_entitlement`, automation: session feature) | Yes | Missing, expired, revoked or unverified denies | `test_org_entitlement_client_and_gate.py`, `test_governance_policy.py` |
| 2 | Organization enablement (master and child switches) | `policy.py` | Yes | Default off; a disabled master denies all children | `test_governance_policy.py`, `test_governance_execution_gate.py`, `test_governance_api.py` |
| 3 | Provider connection and readiness | `policy.py` (`best_provider_readiness`) | Yes | Unknown or stale health denies | `test_provider_health.py` |
| 4 | Actor permission | `execution_gate.py` (`actor_permission_granted`) | Yes | Denies a user without the permission; denies every system actor (no system permission exists) | `test_execution_gates.py`, `test_governance_execution_gate.py` |
| 5 | Resource configuration and publication | `execution_gate.py` (resource gate); agents: published version check in `agents/service.py` and `agents/runtime.py` | Partial by design | AI capabilities require a resource and are refused (`resource_not_found`) until an AI resource store exists. Automation rules must be active. Agents must be published. | `test_execution_gates.py`, `test_agents_runtime.py` |
| 6 | Consent | `execution_gate.py` (consent gate) with `app/governance/consent.py` | Yes for channel capabilities. For AI capabilities that require consent (`ai.voice`), a consent subject is required and refused otherwise | Missing, revoked, expired or channel-mismatched consent denies | `test_consent.py` |
| 7 | Budget | `execution_gate.py` (budget gate) with the usage ledger and reservations | Yes as a hard stop at 100 percent. Full ledger and budget features belong to DFR1-017 | Missing budget configuration denies (`budget_not_configured`). Exhausted budget denies. An unavailable budget store denies | `test_usage_reservations.py`, `test_budget_*` in `test_execution_gates.py` |
| 8 | Rate limits | `execution_gate.py` | Yes | A type with no approved rule denies | `test_execution_rate_limits.py` |
| 9 | Approval for customer-facing actions | `execution_gate.py` and `approvals.py` | Yes (DFR1-025 approvals) | Customer-facing capabilities require an approval bound to the exact payload | `test_approvals_and_channel_policy.py` |
| 10 | Audit | `execution_gate.py` (independent audit write) | Yes | If the decision cannot be audited, the reservation is released and nothing runs | `test_governance_execution_gate.py` |

Gates 5 to 7 are listed in the brief as applicable gates. Gate 5 is complete for agents and automation. For AI capabilities it is intentionally closed until an AI resource store and its publication lifecycle exist. Gate 6 is complete for channel capabilities. Gate 7's full budget feature belongs to DFR1-017, which is still partial; the gate itself is enforced now.

## 5. In-flight behaviour

Two kinds of work exist. A **queued** execution has been accepted but has not yet performed any step. A **running** execution has started and is between steps or waiting on a provider.

Every gate is re-checked at each boundary, not only when work is accepted. `revalidate_ticket` re-runs gates 1 to 5 before each later step. The workflow runtime (`app/workflows/runtime.py`, `_revalidate`) and the agent runtime (`app/agents/runtime.py`, `_revalidate`) call the same policy before each step. Rule execution (`app/automation_rules/execution_service.py`) revalidates before every action.

| Event | Queued (not started) | Running, between steps | Running, external call already dispatched |
|---|---|---|---|
| Organization disables AI or automation | Refused at the first boundary. The run stops with `automation_disabled` (workflow status `stopped`). No step runs. | The next boundary denies. Remaining steps do not run. The stop is audited. | The call completes. It is not recalled. Its usage is settled to actual usage, and the stop is recorded. |
| SIBVO entitlement revoked or expired | Refused at the first boundary (gate 1). | Refused at the next boundary. | Completes as above. |
| Provider connection unavailable or stale | Refused at the gate (gate 3). | Next model call is refused. Bounded retries do not bypass the gate. | Completes or fails by the provider. A failure is recorded; nothing is retried past the bound. |
| Actor permission revoked | Refused at the actor gate (gate 4). | Next boundary refuses (`permission_removed`). | Completes as above. |
| Consent withdrawn | Refused at the consent gate before a channel action. | Next channel action is refused. | Not applicable to model calls. |
| Budget exhausted | Refused by the budget reservation (gate 9). | The next reservation is refused. Reservations already held are settled or released by their own lifecycle. | Settled to actual usage. No over-reservation is possible. |

Rules that hold in every row:

1. Nothing is silently terminated. Each stop writes a reason code and an audit record.
2. Reservations are never left dangling. A reservation is settled to actual usage on success or released on failure or denial. An audit failure releases the reservation and prevents execution.
3. A run is not failed because a capability was switched off. It stops with the gate reason so that the operator can see why, and so that it can be retried as a new run after re-enablement.
4. A dispatched external call is not recalled. The system records its outcome. This is the only point at which work finishes after a disable.

The workflow runtime and the agent runtime store the reason on the run or execution. Retrying a stopped run creates a new run and is checked again by every gate.

## 6. Manual CRM with optional capabilities off

Leads, contacts, follow-ups, site visits, properties, requirements, deals and commissions do not pass through the capability engine. They are governed by tenant scope and ordinary permissions. Test `test_manual_crm_work_is_unaffected_when_every_optional_capability_is_off` (in `backend/tests/test_capability_policy_gates.py`) runs the manual journey with every capability denied.

## 7. Settings and authorization

- Reading capability states requires `governance.capabilities.read`.
- Changing a capability requires `governance.capabilities.manage`, which is owner-only. An admin without it is refused (`test_owner_only_authorization.py`, `test_governance_api.py`).
- A change requires an explicit confirmation field and is versioned (`policy_version`) and audited.
- Enabling a capability does not grant any user permission to execute it. Execution still needs the actor gate (gate 4) and the action's own permission.
- Another organization's settings cannot be changed or read (`test_settings_of_one_organization_cannot_be_changed_with_another_tenant`).

## 8. Known limits (not closed by DFR1-006)

- Gate 5 for AI capabilities is closed by design until an AI resource store exists.
- Gate 7 (budget) integrates with DFR1-017. Provider cost separation from customer credits belongs to DFR1-017.
- Entitlement revocation during a running execution is enforced by gate 1 in revalidation. A dedicated mid-run entitlement test was not added in this story.
- Live provider behaviour is not verified. Tests use mocked provider boundaries. No API key is required or committed. Live validation belongs to production readiness (DFR1-052).

# E13 AI actor execution permission: proposal for approval

Status: **PROPOSAL. NOT APPROVED.** This file records the current authorization behaviour, the findings, and a proposed
permission design for the release owner and the security owner to approve or reject. No permission key has been added,
no role grant has changed, and no application code has changed. Every item under "Proposed" is a candidate for approval,
and each candidate name is a placeholder until approved.

Sources checked on `origin/develop` at `22a4c54` (PR #152 merge; it includes `84d5d11`):

- `backend/app/authz/permissions.py` (catalogue, owner-only keys, owner role)
- `backend/app/authz/dependencies.py` (`permission_granted`, `enforce_permission`)
- `backend/app/team/service.py` (`DEFAULT_ROLE_TEMPLATES`, `provision_default_organization_roles`)
- `backend/app/governance/execution_gate.py` (`evaluate_execution`, `_gate_static`, `_gate_actor`, `REQUIRED_PERMISSION`,
  `DEFAULT_AI_PERMISSION`, `actor_permission_granted`)
- `backend/app/automation_rules/execution_service.py` (the deal-created automation path)
- `docs/adr/0029-ai-execution-and-disabled-by-default-policy.md`
- `docs/architecture/e13-decision-readiness.md` (the "AI actor permission key" entry)
- `docs/architecture/e13-decision-resolution-plan.md`

---

## 1. Summary for the approver

1. **Today, no one can run AI.** The gate's actor check looks for `ai.execute`. That key is not in the 62-key catalogue, so
   no role holds it, and owners are refused as well (a test confirms this).
2. **There is an existing precedent that the readiness file did not weigh.** Deal-created automation already runs through the
   same gate, and its actor check requires the initiating user to hold the CRM permission for the target action
   (`deals.create`). That is ADR-0029 gate 5 ("permission on the target") in code. The readiness file's recommended option
   (a new catalogued key) does not follow this precedent. This proposal reconciles the two in section 4.
3. **Recommended design (for approval):** keep the target-permission rule for every action that writes a CRM record, and
   add one catalogued governance key for AI execution as an *additional* gate. The name below is a candidate. The key is
   granted to Admin and to no other role by default, and every decision is audited.
4. **Nothing in this proposal is approved.** The approval the release owner and security owner must give is listed in
   section 10.

---

## 2. Existing behaviour (what the code does today)

| Topic | Current behaviour | Evidence |
|---|---|---|
| Catalogue | 62 keys. Owner-only subset of 9 keys. | `permissions.py` |
| Owner role | System role "DealFlow Owner" holds every catalogued key. Owner-only keys count only through this role. | `OWNER_ROLE_PERMISSION_KEYS`; `permission_granted` adds `Role.is_system` and `Role.name` conditions |
| Admin role | Holds every catalogued key except the owner-only set. | `DEFAULT_ROLE_TEMPLATES["Admin"]` |
| Manager role | CRM keys, automation read/create/update, documents, and `organization.members.read`. No governance key. | `DEFAULT_ROLE_TEMPLATES["Manager"]` |
| Member role | CRM create/read/update, documents, notification preferences. No automation key and no governance key. | `DEFAULT_ROLE_TEMPLATES["Member"]` |
| Viewer role | Read-only CRM and documents. | `DEFAULT_ROLE_TEMPLATES["Viewer"]` |
| Permission check | Database query per request. Requires an active membership, an active role and an active permission. Membership deactivation and role-permission removal take effect at the next check. | `permission_granted`; `actor_permission_granted` |
| Gate order | Static gates (entitlement snapshot, organization switch, provider readiness) run first, then actor, resource, consent, channel, approval, rate, budget and audit. | `evaluate_execution`, `_gate_static` |
| Actor check, AI | Looks for `DEFAULT_AI_PERMISSION = "ai.execute"`. Not in the catalogue, so every AI request is refused with `permission_denied`. | `execution_gate.py:155`, `_gate_actor` |
| Actor check, automation | `REQUIRED_PERMISSION["automation.deal_created_rules"] = "deals.create"`. The initiating user needs `deals.create`. | `execution_gate.py:152` |
| System actor | Refused for every gated capability with `system_actor_not_permitted`. No system permission exists. | `_gate_actor` |
| Human approval | `governance.approvals.request` is held by Admin only. `governance.approvals.decide` is owner-only. | `permissions.py`, `DEFAULT_ROLE_TEMPLATES` |
| Enabling a capability | `governance.capabilities.manage` is owner-only. `governance.capabilities.read` is held by Admin. | `permissions.py` |

### 2.1 Current tests that protect this behaviour

- `tests/test_channel_send_authorization.py`: the default key is not in the catalogue; an owner and a member without a send
  permission are refused; a test-only grant passes the actor gate only.
- `tests/test_owner_only_authorization.py`: owner-only keys are refused to non-owner roles.
- `tests/test_governance_execution_gate.py` and `tests/test_execution_gates.py`: gate order and denial reasons.

---

## 3. Findings and conflicts

| # | Finding | Type | Consequence if unaddressed |
|---|---|---|---|
| F1 | `ai.execute` is referenced in code but not catalogued. | Conflict with the catalogue | Any change to the key must update `DEFAULT_AI_PERMISSION` and the test seams (`tests/governance_helpers.py`, `test_channel_send_authorization.py`). |
| F2 | The readiness file recommends a new key (its Option A). The automation precedent reuses the target permission (`deals.create`). | Design conflict | Two AI paths could follow different rules. Must be reconciled before approval (section 4). |
| F3 | Capability keys use the `ai.` prefix (`ai.assistant`, `ai.master`). A permission named `ai.execute` shares that prefix. | Naming collision (different tables) | Easy to confuse a capability with a permission in review. Recommend a `governance.` prefix. |
| F4 | Adding a key to the catalogue grants it to the owner automatically, and to Admin unless the key is owner-only. | Grant side effect | The approver must choose the Admin grant explicitly. |
| F5 | The role templates are applied when `provision_default_organization_roles` runs. Existing organizations keep their current role-permission rows unless a backfill runs. | Migration consequence | Changing the Manager template does not change existing organizations. A backfill is a separate, approved change. |
| F6 | ADR-0029 gate 5 says "the initiating user or service identity has permission on the target". The gate has no service-identity permission, and system actors are always refused. | Gap in ADR wording | Agents and workflows have no defined identity. Needs the delegation rule in section 6. |
| F7 | Exact-payload approval requires `governance.approvals.request`, which only Admin holds. | Dependency | A Manager who must request an approval cannot do so unless Manager is granted the request key. |
| F8 | A channel send key reusing `governance.channels.manage` (owner-only) would mix configuration and sending. | Segregation risk | Use a separate channel send key (decision item 9 in the resolution plan). |

No existing permission key is misnamed, and no existing role grant is contradicted by the code. The conflicts above are between
the proposal options and the existing precedent, and between the placeholder `ai.execute` and the catalogue.

---

## 4. Reconciling the two designs

The two existing designs can coexist. The proposal uses each for a different purpose:

- **Target permission (existing precedent, ADR-0029 gate 5).** For any AI or automation action that writes a CRM record, the
  initiating user must hold the CRM permission for that record action (for example `deals.create`, `deals.update`). This
  stops AI from doing what the user could not do by hand.
- **AI execution key (new, candidate).** For any AI execution, the initiating user must also hold one governance key. This
  is the switch that decides who may start AI work at all, separate from CRM rights. It is required in addition to the target
  permission, not instead of it.

Under this design, a user must hold both, and the static gates (entitlement, organization switch, provider readiness) must
pass before either is consulted. The readiness file's Option A (key alone) is therefore narrowed: the key is necessary but
not sufficient.

---

## 5. Proposed permission design (for approval)

### 5.1 Exact proposed key

**Candidate name:** `governance.ai.execute`

Reasons: it follows the `governance.<area>.<action>` pattern of every other governance key; it avoids the `ai.` prefix used
by capability keys (F3); and it reads as an action, like `deals.create`. The name is a placeholder until the approver accepts it.

Description (candidate): "Start AI execution for an organization, in addition to the permission the target action requires."

### 5.2 Which roles may receive it

| Role | Proposed grant | Mechanism | Notes |
|---|---|---|---|
| DealFlow Owner | Yes, automatically | Owner role holds every catalogued key | Automatic, no change needed |
| Admin | Yes, automatically (unless the key is made owner-only) | Admin receives every non-owner-only key | Approver decides whether Admin receives it (F4) |
| Manager | Candidate only | Requires a new template entry, plus a backfill decision (F5) | Not proposed for default grant |
| Member | No | Not in template | Member keeps CRM rights only |
| Viewer | No | Not in template | Read only |

**Candidate for approval:** the key is *not* owner-only, granted to Admin, and not added to Manager or Member. The owner
retains it through the owner role. Owner-only status is the stricter option (section 10, question 2).

### 5.3 Organization-owner and administrator authority

- **Owner.** Holds the key. Can enable or disable AI for the organization through `governance.capabilities.manage` (owner-only,
  unchanged). Owner-only keys stay effective only through the system Owner role (unchanged).
- **Administrator.** Holds the key by default under the candidate design. Cannot change the Owner role or its keys. Cannot
  enable a capability that is owner-only.
- **Holding the key does not enable AI.** Enablement remains with the organization switches and the SIBVO entitlement.
  The key only answers "may this person start AI work", which is one of several gates.

### 5.4 Human versus system or agent execution

- **Human, interactive.** The initiating user's membership is checked at the time of the request. The key and the target
  permission are both checked by the actor gate.
- **System actor.** Refused (current behaviour, unchanged). No system actor is granted the AI key. A later system path needs
  its own approved design and is not part of this proposal.
- **Agent or workflow run.** An agent does not hold a permission of its own. It acts with the permissions of the user who
  started the run, checked at each gated step. The run records both the user and the agent identity.
- **Scheduled or background run.** Treated as a system actor and refused, unless a later design gives it a user on whose
  behalf it runs. A scheduled run started by a user counts as that user's run only if the design says so (section 10, question 4).

### 5.5 Delegated execution and actor attribution

- Every AI execution record carries `user_id` (the initiating user), `capability_key`, `agent_id` or `workflow_id` where
  applicable, `correlation_id`, and the decision of each gate. The existing usage ledger already has `user_id`, `agent_id`,
  `workflow_id` and `execution_id` columns (PR #148).
- A delegated run is attributed to the initiating user for audit. It is not attributed to the agent as if the agent had its
  own grant.
- An agent cannot grant or request a permission, and cannot widen its own scope. This matches ADR-0029 ("no self-granted
  permissions").

### 5.6 Default-deny behaviour

- A key not in the catalogue is refused (current behaviour, unchanged).
- A user without the key, or without the target permission, is refused with `permission_denied` (current reason code).
- A missing or inactive permission, role or membership is refused (current database checks, unchanged).
- A capability with no entry in the required-permission map falls back to the AI key, so an unmapped AI capability is still
  gated. This fallback must stay (see section 9 test list).

### 5.7 Capability and entitlement checks

Order is unchanged. Static gates run first and deny before the actor check is consulted:

1. SIBVO entitlement for the capability (snapshot, fail closed; `ai_gateway` today).
2. Organization switches (master and capability, both required).
3. Provider connected, verified and healthy (readiness, PR #149).
4. Then the actor gate: the AI key and the target permission.

The new key adds only step 4. It does not reach past steps 1 to 3.

### 5.8 Consent, provider readiness and usage budget

- **Consent.** The consent gate runs after the actor gate, as today. The key does not bypass consent or do-not-disturb.
- **Provider readiness.** Checked in the static gates, before the actor gate. The key does not make an unhealthy provider usable.
- **Usage budget and rate.** Checked in the rate and budget gates, after the actor gate. The key does not exempt a request from
  budgets. A budget denial still produces the existing audit record.
- **Approval.** Where a capability requires an approval for the exact payload, the requester needs
  `governance.approvals.request` (F7), and the approver needs `governance.approvals.decide` (owner-only, unchanged).

### 5.9 Revocation

- **Remove the key from a role.** Takes effect at the next gate evaluation. The gate reads permissions from the database for
  each request, so there is no cache to clear. A test must prove this (section 8).
- **Deactivate a membership.** Takes effect at the next evaluation (`Membership.is_active` is checked).
- **Disable a capability.** Blocks new executions immediately. In-flight work follows the policy in ADR-0029 gate 10, which
  the revalidation tests already exercise.
- **Remove an agent or workflow's user.** The agent's next gated step is refused, because the initiating user's membership
  is checked each time.

### 5.10 Audit

- Every actor decision (allowed or denied) is recorded with the organization, user, capability, permission key, decision and
  reason code. Denials already produce audit rows through `enforce_permission` and the gate's denial path.
- A grant or revocation of the AI key is an administrative change and must be audited through the existing role-change path.
- No audit row may contain a secret, a provider response, or a permission check's internal query.

### 5.11 Tenant isolation

- The key is checked against the organization of the request (`actor_permission_granted` filters `Membership.organization_id`
  and `Role.organization_id`).
- A user who holds the key in organization A is refused in organization B, unless they hold it there too.
- A role of organization A cannot be attached to a membership of organization B.

---

## 6. Required tests (for the approved design)

| Test | Proves |
|---|---|
| Catalogue contains the key exactly once | No duplicate or missing key |
| Owner holds the key; Admin holds it (or not, per the approved answer) | Role grants match the approval |
| Manager, Member and Viewer are refused without the key | Default deny |
| A user with the key but without the target permission is refused | Both gates are required (section 4) |
| A user with the target permission but without the key is refused | The key is not optional |
| Unmapped AI capability falls back to the key and is refused without it | No unmapped path opens |
| System actor refused | Existing behaviour preserved |
| Removing the key from a role denies the next request | Revocation is immediate |
| Deactivating the membership denies the next request | Revocation is immediate |
| Agent run attributed to the initiating user; agent holds no grant | Delegation is correct |
| Cross-organization: key in organization A does not apply in organization B | Tenant isolation |
| Denial writes an audit row with the reason | Auditability |
| Frontend role list cannot grant the key | The frontend is not the enforcement point |
| Default `DEFAULT_AI_PERMISSION` points at the approved key, not `ai.execute` | F1 resolved |

---

## 7. Migration and backfill consequences

- Adding a catalogue key requires a migration to insert the `permissions` row for existing databases (the signup path creates
  it for new organizations only, through `provision_default_organization_roles`). The approval must say whether existing
  organizations receive the key, and to which roles (F5).
- If the key is granted to Admin in existing organizations, that grant is a data migration and must be reversible.
- No migration is proposed in this document. It is listed here so the approver sees the consequence.

---

## 8. Rollout and safe default

- **Safe default:** the key is in the catalogue but granted to no role until the owner approves the grant. Until then, AI
  stays refused, which is the current behaviour.
- **Enablement order:** (1) approve the key and its grants; (2) add it to the catalogue with tests; (3) enable AI for a test
  organization; (4) only then consider Manager or Member grants.

---

## 9. Items that must not change without a new approval

- The owner-only status of `governance.capabilities.manage`, `governance.approvals.decide`, `governance.channels.manage`,
  `governance.budgets.manage`, `governance.privacy.manage`, `governance.consent.manage` and `provider_credentials.manage`.
- The rule that system actors are refused for gated capabilities.
- The static gates running before the actor gate.
- The `deals.create` requirement for deal-created automation.

---

## 10. Approval required from the release owner and security owner

The approval below is **requested, not given**. It consists of six answers. Each answer can be recorded as "approved",
"changed to…", or "rejected", with the approver's name and date.

1. **Key name.** Approve `governance.ai.execute`, or name a different key. The name must not start with `ai.`.
2. **Owner-only or not.** Recommended: not owner-only, so Admin can run AI. Alternative: owner-only, so only owners can run
   AI.
3. **Initial grants.** Recommended: Admin receives it in new organizations, and no other role. Confirm whether existing
   organizations receive it through a backfill, and whether Manager receives it.
4. **Scheduled and background runs.** Recommended: refused until a separate design is approved. Alternative: a background run
   is allowed when a user who holds the key started it, and the run is attributed to that user.
5. **Target permission reconciliation.** Recommended: keep both gates, as section 4 describes. Alternative: rely only on the
   key, which would require changing the automation precedent and ADR-0029 gate 5.
6. **Test seam removal.** Approve the replacement of `DEFAULT_AI_PERMISSION` and the test seams in section 6, which is required
   before any AI path can be tested without a test-only grant.

**Who approves:** the release owner (scope and grants) and the security owner (permission model). The repository names no
individual for either role, so the release owner must name the person before this can be recorded as approved.

---

## 11. What this proposal does not change

- No permission key is added, and no role grant changes.
- No application code, migration, endpoint or configuration changes.
- No decision is approved. No story status changes: DFR1-006 remains Partial, DFR1-015 and DFR1-017 are untouched, and E13
  is not Done.
- E02 and E06 are untouched.

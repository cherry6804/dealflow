# ADR-0011: Lead Next Action and Outcome Management

- **Status:** Accepted
- **Date:** 2026-10-01
- **Decision Owners:** DealFlow Engineering
- **Related Epic:** DF-E04 — Lead Management
- **Related Story:** DF-46 — Lead Next Action & Outcome Management
- **Related ADRs:** ADR-0008 Lead Domain Architecture and Lifecycle, ADR-0009 Lead Update and Lifecycle Management, ADR-0010 Lead Assignment and Ownership

## 1. Context

DealFlow Lead Management already provides the foundational Lead lifecycle, ownership, and update behavior.

A Lead currently contains lifecycle status, interest, outcome, owner, next action, next action timing, active/inactive state, tenant ownership, and timestamps.

DF-44 established update and lifecycle rules for these fields, including the distinction between lifecycle status, outcome, ownership, next action, and active state.

DF-45 strengthened lead ownership validation so that an assigned owner must belong to the same organization through an active membership.

DF-46 formalizes the operational behavior of `next_action`, `next_action_at`, and `outcome` so these fields can safely support future follow-up, attention, automation, reporting, and AI capabilities.

The objective is not to introduce another Lead workflow or duplicate existing lifecycle behavior. The objective is to make the existing Lead fields operationally precise, independently updateable, tenant-safe, permission-controlled, and backward compatible.

## 2. Problem Statement

A Lead is not operationally useful merely because it has a lifecycle status.

A business user needs to know:

1. what should happen next;
2. when that action should happen;
3. whether the opportunity has an outcome;
4. whether those values can be changed independently;
5. whether clearing one value accidentally changes another;
6. whether lifecycle changes accidentally overwrite operational information.

Without explicit rules, future features could introduce inconsistent behavior such as clearing `next_action` automatically clearing `next_action_at`, changing `outcome` automatically changing lifecycle status, or changing lifecycle status automatically removing an existing next action.

DF-46 therefore defines these behaviors before further automation or intelligence is built.

## 3. Decision

DealFlow will treat the following Lead concepts as independent business dimensions:

### 3.1 Lifecycle Status

`status` represents where the Lead currently sits in the business lifecycle.

Allowed statuses remain:

- `NEW`
- `CONTACTED`
- `QUALIFIED`
- `MATCHING`
- `VISIT`
- `NEGOTIATION`
- `WON`
- `LOST`
- `ON_HOLD`

DF-46 does not redefine these statuses. The lifecycle transition rules established by DF-44 remain authoritative.

### 3.2 Outcome

`outcome` represents the current recorded business outcome of the Lead.

Allowed outcomes remain:

- `SUCCESSFUL`
- `UNSUCCESSFUL`
- `NULL`

Outcome is independent from lifecycle status except for the terminal-state consistency rules defined by DF-44.

The following rules remain mandatory:

| Lead Status | Required Outcome |
|---|---|
| `WON` | `SUCCESSFUL` |
| `LOST` | `UNSUCCESSFUL` |
| Any other status | Optional |

An outcome update must not implicitly change Lead status. A status update must not silently change an existing outcome unless required by existing DF-44 validation rules.

The system must reject contradictory terminal combinations:

- `WON + UNSUCCESSFUL` → rejected
- `LOST + SUCCESSFUL` → rejected

## 4. Next Action

`next_action` represents the explicit action that should be performed next for the Lead.

Examples:

- Call customer
- Send property options
- Schedule site visit
- Follow up on negotiation
- Collect documents
- Confirm booking

The value is optional and its maximum length remains **500 characters**.

The system must not infer or automatically generate a next action merely because another Lead field changed.

## 5. Next Action Timing

`next_action_at` represents the intended date/time associated with the next action.

The field is optional and independent from `next_action`.

Therefore all of these states are valid:

| next_action | next_action_at | Valid |
|---|---|---|
| null | null | Yes |
| value | null | Yes |
| null | value | Yes |
| value | value | Yes |

This allows partially known operational information. DF-46 does not make both values mandatory.

## 6. Independent Update Semantics

`next_action` and `next_action_at` must be independently updateable.

If a request contains only `next_action`, the existing `next_action_at` remains unchanged.

If a request contains only `next_action_at`, the existing `next_action` remains unchanged.

An explicit `{"next_action": null}` clears only `next_action`.

An explicit `{"next_action_at": null}` clears only `next_action_at`.

An empty update payload remains a no-op, consistent with DF-44.

## 7. Outcome Update Semantics

Outcome must be independently updateable from next-action fields.

Changing `outcome` must not modify `next_action`, `next_action_at`, `owner_user_id`, or `interest`.

Changing `next_action` or `next_action_at` must not modify `outcome`.

## 8. Lifecycle Interaction

DF-46 does not introduce new lifecycle transitions. The DF-44 lifecycle transition matrix remains authoritative.

For non-terminal statuses (`NEW`, `CONTACTED`, `QUALIFIED`, `MATCHING`, `VISIT`, `NEGOTIATION`, `ON_HOLD`), next-action fields may be created, updated, cleared, or left unchanged according to the request.

`WON` remains terminal and requires `outcome = SUCCESSFUL`.

`LOST` remains terminal and requires `outcome = UNSUCCESSFUL`.

DF-46 does not create new transitions out of either terminal state.

Existing next-action data is not silently destroyed solely because a Lead becomes `WON` or `LOST`.

## 9. Active State Interaction

`is_active` remains independent from `status`, `outcome`, `next_action`, `next_action_at`, and `owner_user_id`.

Changing `is_active` must not automatically clear next action, timing, outcome, owner, or lifecycle status.

Changing next-action or outcome fields must not automatically change `is_active`.

## 10. Authorization

DF-46 continues to use the existing Lead permission model.

Reading Lead operational fields requires `leads.read`.

Changing outcome, next action, or next-action timing requires `leads.update`.

Authorization remains tenant-scoped. No DF-46 operation may bypass the existing authorization dependency.

## 11. Tenant Isolation

All DF-46 operations remain organization-scoped.

A Lead belonging to Organization A must never be readable or mutable through Organization B.

Organization context continues to be derived from the authenticated user's authorized membership.

Cross-tenant Lead access continues to return the established not-found behavior:

`Lead not found.`

## 12. API Compatibility

DF-46 must remain backward compatible with DF-42, DF-43, DF-44, and DF-45.

Existing request and response structures must not be unnecessarily broken.

No database migration is required because the required Lead fields already exist.

No silent data rewrite is permitted.

## 13. Validation Rules

The following validations remain mandatory:

- `next_action` must not exceed 500 characters.
- Nullable fields may be explicitly cleared using `null`.
- Omitted fields remain unchanged during PATCH.
- Only `SUCCESSFUL`, `UNSUCCESSFUL`, or `null` are valid outcomes.
- Existing DF-44 terminal-state rules remain mandatory.
- Updating one operational field must not silently modify unrelated operational fields.

## 14. Error Handling

DF-46 follows established API error conventions.

### 400 Bad Request

Used for business-rule violations such as invalid terminal outcome combinations or invalid lifecycle transitions.

### 403 Forbidden

Used when the authenticated user lacks the required permission.

### 404 Not Found

Used when the Lead is not accessible within the authenticated organization.

### 422 Unprocessable Entity

Used for malformed request data rejected by request validation.

## 15. Transaction and Atomicity Requirements

Lead operational updates must remain atomic.

A request that fails business validation must not partially update next action, timing, outcome, status, ownership, or active state.

The database transaction must either persist the complete valid update or persist none of it.

Existing DF-44 transaction behavior remains authoritative.

## 16. History and Audit Compatibility

DF-46 must preserve the platform's future ability to record operational history.

The implementation must retain the ability to determine who changed a Lead, which organization it belonged to, what operational fields changed, and when the change occurred.

DF-46 does not introduce a separate Lead history system unless explicitly required by a later story.

## 17. API Design Direction

DF-46 will continue using the existing Lead APIs:

```text
POST  /api/v1/leads
GET   /api/v1/leads/{lead_id}
GET   /api/v1/leads
PATCH /api/v1/leads/{lead_id}
```

The existing PATCH operation remains the primary mechanism for changing outcome, next action, and next-action timing.

## 18. Service-Layer Requirements

Business rules remain in the service/domain layer rather than being implemented only inside HTTP route handlers.

The service layer must:

1. load the tenant-scoped Lead;
2. determine requested changes;
3. validate lifecycle rules where applicable;
4. validate outcome consistency;
5. apply only explicitly supplied fields;
6. preserve omitted fields;
7. flush atomically;
8. return the resulting Lead.

The API layer should translate service validation errors into established HTTP responses.

## 19. Testing Requirements

DF-46 must include automated coverage for:

### Next action
- create with next action;
- update next action;
- clear next action;
- preserve next action when omitted;
- maximum length validation.

### Next action timing
- create with timing;
- update timing;
- clear timing;
- preserve timing when omitted.

### Independence
- action without timing;
- timing without action;
- clear action while preserving timing;
- clear timing while preserving action.

### Outcome
- successful outcome;
- unsuccessful outcome;
- clear outcome where allowed;
- preserve outcome when omitted;
- reject contradictory terminal outcomes.

### Lifecycle interaction
- next action does not change status;
- outcome does not silently change status;
- valid WON behavior;
- valid LOST behavior;
- terminal-state restrictions remain intact.

### Active state
- deactivation preserves operational data;
- reactivation preserves operational data.

### Security
- missing `leads.update`;
- missing `leads.read`;
- cross-tenant access;
- unauthorized update;
- authorized update.

### Regression
The complete existing test suite must remain green.

## 20. Backward Compatibility

Existing Leads created before DF-46 remain valid.

The implementation must not require existing Leads to have a next action, next-action timing, or outcome.

Existing null values remain valid.

No destructive migration is required.

## 21. Future Compatibility

DF-46 is designed to support future capabilities including:

- Follow-Up Intelligence;
- Today's Attention;
- reminders;
- task generation;
- workflow automation;
- notifications;
- calendar integration;
- property matching workflows;
- site-visit workflows;
- deal operations;
- AI-assisted next-action suggestions.

Future automation or AI may propose a next action, but it must not bypass tenant boundaries, identity, permissions, business rules, approval requirements, or audit requirements.

AI-generated actions must not silently mutate Lead state without appropriate authorization and workflow rules.

## 22. Non-Goals

DF-46 does not implement:

- automated reminders;
- background jobs;
- notifications;
- calendar synchronization;
- task management;
- AI next-action generation;
- lead history UI;
- activity timeline;
- follow-up scheduling engine;
- SLA management;
- escalation engine;
- new lifecycle statuses;
- new database schema for existing next-action/outcome fields.

## 23. Implementation Order

Implementation should follow this sequence:

1. Review current DF-44 Lead update behavior.
2. Review current DF-45 ownership validation.
3. Confirm existing schema is sufficient.
4. Refine reusable business validation where necessary.
5. Update service behavior only where DF-46 rules require it.
6. Update API behavior only where required.
7. Add focused DF-46 tests.
8. Run the Lead lifecycle test suite.
9. Run the complete backend regression suite.
10. Review the final diff.
11. Commit the implementation.
12. Push the feature branch.
13. Create a Pull Request against `develop`.
14. Merge only after checks pass.
15. Delete the feature branch after merge.

## 24. Decision Summary

DealFlow will treat Lead outcome, next action, and next-action timing as explicit operational fields with independent semantics.

The system will:

- preserve omitted values during PATCH;
- allow explicit clearing through `null`;
- keep next action and timing independent;
- keep outcome independent from next-action fields;
- preserve DF-44 lifecycle rules;
- preserve DF-45 ownership rules;
- maintain tenant isolation;
- enforce existing permissions;
- avoid destructive implicit mutations;
- remain backward compatible;
- require no database migration for DF-46;
- prepare the Lead model for future follow-up, automation, reporting, and AI capabilities.

This provides a stable operational foundation for the next Lead Management capabilities without prematurely introducing automation or additional workflow complexity.

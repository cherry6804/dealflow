# ADR-0009: Lead Update and Lifecycle Management

- Status: Accepted
- Date: 2026-10-01
- Sprint: S04
- Story: DF-44
- Decision owners: DealFlow Product & Engineering
- Related ADR: ADR-0008 Lead Domain Architecture and Lifecycle

## 1. Context

DealFlow Leads represent actively managed real-estate business opportunities.

DF-39 established the Lead as a tenant-scoped business entity associated with an existing Contact. It also established that Lead status, interest, outcome, ownership, and next action are separate concepts.

DF-42 introduced Lead creation and retrieval.

DF-43 introduced Lead listing, search, pagination, and filtering.

DF-44 introduces controlled Lead updates and lifecycle management.

A generic unrestricted PATCH operation would allow inconsistent business states such as:

- moving a new Lead directly to a terminal state;
- changing a WON Lead back into an active lifecycle;
- assigning a Lead to a user from another organization;
- combining WON with an unsuccessful outcome;
- combining LOST with a successful outcome;
- changing the Contact associated with a Lead without an explicit business operation.

Therefore Lead updates must distinguish between ordinary editable fields and lifecycle transitions.

## 2. Decision

DealFlow will implement Lead updates as tenant-scoped, permission-controlled business operations.

The Lead update capability will:

1. enforce authentication;
2. derive tenant context from authenticated membership;
3. require the `leads.update` permission;
4. retrieve the Lead only within the authorized organization;
5. validate all supplied fields;
6. validate lifecycle transitions;
7. validate terminal-state outcome consistency;
8. validate owner membership within the same organization;
9. preserve immutable server-controlled fields;
10. persist the update atomically.

The generic update operation will not allow modification of `contact_id` or `organization_id`.

## 3. Editable Fields

DF-44 permits updates to:

- `status`
- `interest`
- `outcome`
- `owner_user_id`
- `next_action`
- `next_action_at`
- `is_active`

The following fields remain server-controlled:

- `id`
- `organization_id`
- `contact_id`
- `created_at`
- `updated_at`

Changing the Contact associated with a Lead is outside the DF-44 update contract and requires a future explicit domain operation if the business requires it.

## 4. Lead Lifecycle

The supported Lead statuses are:

- `NEW`
- `CONTACTED`
- `QUALIFIED`
- `MATCHING`
- `VISIT`
- `NEGOTIATION`
- `WON`
- `LOST`
- `ON_HOLD`

These values remain compatible with the Lead domain established by ADR-0008.

## 5. Lifecycle Transition Rules

The following transitions are allowed.

### NEW

Allowed destinations:

- CONTACTED
- QUALIFIED
- ON_HOLD

### CONTACTED

Allowed destinations:

- QUALIFIED
- MATCHING
- ON_HOLD

### QUALIFIED

Allowed destinations:

- MATCHING
- VISIT
- ON_HOLD

### MATCHING

Allowed destinations:

- VISIT
- QUALIFIED
- ON_HOLD

### VISIT

Allowed destinations:

- MATCHING
- NEGOTIATION
- QUALIFIED
- ON_HOLD

### NEGOTIATION

Allowed destinations:

- WON
- LOST
- VISIT
- ON_HOLD

### ON_HOLD

Allowed destinations:

- CONTACTED
- QUALIFIED
- MATCHING
- VISIT
- NEGOTIATION

### WON

WON is terminal.

No lifecycle transition away from WON is allowed by DF-44.

### LOST

LOST is terminal.

No lifecycle transition away from LOST is allowed by DF-44.

## 6. Same-State Updates

An update that supplies the current status is allowed when the remaining supplied fields are valid.

For example:

`QUALIFIED -> QUALIFIED`

may update:

- interest;
- owner;
- next action;
- next action time;
- active state;
- outcome when valid.

Same-state updates do not constitute lifecycle transitions.

## 7. Status and Outcome

Status and outcome remain separate concepts.

Outcome values are:

- `SUCCESSFUL`
- `UNSUCCESSFUL`

Terminal-state consistency is required.

### WON

A Lead with status `WON` must have:

`outcome = SUCCESSFUL`

### LOST

A Lead with status `LOST` must have:

`outcome = UNSUCCESSFUL`

The following combinations are invalid:

- `WON + UNSUCCESSFUL`
- `LOST + SUCCESSFUL`

For non-terminal statuses, outcome remains optional.

DF-44 does not automatically assign an outcome merely because a Lead changes to a non-terminal status.

## 8. Interest

Interest remains independent of lifecycle status.

Supported values:

- `LOW`
- `MEDIUM`
- `HIGH`

Updating interest does not itself perform a lifecycle transition.

## 9. Ownership

A Lead may be assigned to:

- an active user membership within the same organization; or
- no owner (`null`).

Cross-tenant ownership assignment is prohibited.

The server must validate ownership using the Lead organization context and organization membership.

Clients must not be able to select or override the Lead organization through the update operation.

## 10. Next Action

`next_action` and `next_action_at` remain independent fields.

An update may:

- set a next action;
- change a next action;
- clear a next action;
- set or change its scheduled time;
- clear the scheduled time.

DF-44 does not automatically generate a next action from a status change.

Future automation capabilities may introduce such behavior explicitly.

## 11. Active Record State

`is_active` is separate from Lead lifecycle status.

Deactivating a Lead does not automatically change its business status.

Likewise, `LOST` does not automatically mean `is_active = false`.

Historical business records must remain representable without destroying their lifecycle state.

## 12. ON_HOLD

`ON_HOLD` is a reversible lifecycle state.

A Lead may enter ON_HOLD from an active non-terminal lifecycle state.

A Lead may resume from ON_HOLD into an appropriate active lifecycle state.

ON_HOLD is not equivalent to:

- LOST;
- WON;
- inactive.

The product must preserve this distinction.

## 13. Terminal States

WON and LOST are terminal states in DF-44.

DF-44 does not support reopening terminal Leads.

If future product requirements require reopening, that behavior must be introduced as an explicit business operation with its own rules, permissions, audit semantics, and history requirements.

Terminal behavior must not be weakened by adding unrestricted PATCH semantics.

## 14. Tenant Isolation

Every Lead update must be scoped to the tenant derived from the authenticated user's authorized membership.

The client cannot select the organization to which the update applies.

Cross-tenant Lead access must not be permitted.

A Lead belonging to another organization must produce the same external not-found behavior as a Lead that does not exist:

`404 Lead not found.`

## 15. Authorization

DF-44 requires:

`leads.update`

Permission checks must occur before business mutation.

Authorization remains separate from authentication.

The existing tenant and authorization dependency architecture remains the enforcement boundary.

## 16. Atomicity

A Lead update must be atomic.

If any validation fails:

- no Lead fields are partially updated;
- no invalid lifecycle state is persisted;
- no cross-tenant assignment is persisted.

The database transaction must either commit the complete valid update or roll back the mutation.

## 17. API Boundary

The update API will use an explicit Pydantic request schema.

The request schema must:

- distinguish omitted fields from explicitly supplied null values;
- validate UUID values;
- validate status values;
- validate interest values;
- validate outcome values;
- enforce maximum field lengths;
- prevent unsupported fields from changing the Lead.

The response remains the existing `LeadResponse` representation.

## 18. Error Semantics

DF-44 will use predictable HTTP behavior.

Expected categories include:

- `400` for invalid business state or lifecycle transition;
- `403` for missing update permission;
- `404` for missing or cross-tenant Lead;
- `422` for malformed request data.

The exact error messages should remain stable and deterministic where practical.

## 19. Business Validation Order

The implementation should conceptually follow:

Authenticate
    ↓
Resolve tenant
    ↓
Check leads.update permission
    ↓
Load tenant-scoped Lead
    ↓
Validate request
    ↓
Validate owner membership
    ↓
Validate lifecycle transition
    ↓
Validate status/outcome consistency
    ↓
Apply complete mutation
    ↓
Persist atomically
    ↓
Return updated Lead

## 20. History and Audit

Lead updates represent meaningful business activity.

DF-44 must preserve sufficient information for future audit and timeline capabilities.

At minimum, the update operation must remain attributable to:

- actor;
- organization;
- Lead;
- operation;
- timestamp.

The existing authorization audit mechanism remains responsible for authorization decisions.

A richer user-facing Lead timeline/history is a future capability and must not be duplicated unnecessarily inside DF-44.

## 21. Backward Compatibility

Existing Lead records must remain valid after DF-44.

The update capability must not require destructive data migration.

Existing values for:

- status;
- interest;
- outcome;
- owner;
- next action;
- active state

must remain readable.

DF-44 must preserve the existing DF-42 and DF-43 API contracts.

## 22. Future Compatibility

The lifecycle design must support future capabilities including:

- customer requirements;
- property matching;
- site visits;
- negotiation;
- documents;
- booking;
- payments;
- commissions;
- automation;
- notifications;
- AI-assisted recommendations.

Future automation and AI capabilities must not bypass the same tenant, identity, permission, policy, validation, and audit boundaries used by human users.

## 23. Security Constraints

The implementation must prevent:

- cross-tenant Lead updates;
- cross-tenant owner assignment;
- unauthorized lifecycle changes;
- modification of organization ownership;
- modification of Contact association through generic update;
- invalid terminal states;
- invalid lifecycle transitions;
- partial mutation on validation failure.

Security validation must include both positive and negative tests.

## 24. Testing Requirements

DF-44 must test at minimum:

### Update

- successful update;
- partial update;
- empty update;
- explicit null clearing;
- immutable field protection.

### Lifecycle

- every allowed transition;
- every prohibited transition;
- same-state update;
- WON terminal behavior;
- LOST terminal behavior;
- ON_HOLD resume behavior.

### Outcome

- valid WON outcome;
- valid LOST outcome;
- invalid WON outcome;
- invalid LOST outcome;
- non-terminal outcome behavior.

### Ownership

- assign same-tenant owner;
- clear owner;
- reject cross-tenant owner;
- reject invalid owner.

### Security

- unauthenticated access;
- missing tenant context;
- missing permission;
- cross-tenant Lead;
- cross-tenant owner assignment.

### Regression

- existing Lead creation;
- Lead retrieval;
- Lead listing;
- Lead search;
- Lead filtering;
- pagination;
- existing tenant isolation.

## 25. Implementation Order

DF-44 implementation should follow:

1. lifecycle/domain validation helpers;
2. update request schema;
3. service-layer update operation;
4. API endpoint;
5. authorization integration;
6. ownership validation;
7. lifecycle validation;
8. outcome validation;
9. regression tests;
10. compile and quality checks;
11. commit;
12. PR review;
13. merge to develop;
14. branch cleanup.

## 26. Consequences

### Positive

- Lead lifecycle becomes predictable.
- Invalid business states are prevented.
- Terminal records remain stable.
- Tenant isolation is preserved.
- Ownership remains tenant-safe.
- Future automation can rely on a defined lifecycle.
- Future AI capabilities can operate against explicit business-state rules.
- Existing Lead APIs remain compatible.

### Trade-offs

- Updates are more restrictive than generic CRUD.
- Future lifecycle changes require deliberate domain changes.
- Some user-requested transitions may require explicit future business operations.
- More validation and testing are required.

These trade-offs are intentional because Lead status is a business state rather than a free-form field.

## 27. Final Decision

DealFlow will implement DF-44 as a controlled Lead update and lifecycle-management capability.

Generic field updates are permitted only for explicitly editable fields.

Lifecycle status changes must follow the defined transition rules.

WON and LOST are terminal.

ON_HOLD is reversible.

Ownership must remain within the current tenant.

Status and outcome remain separate but must be mutually consistent for terminal states.

All operations remain authenticated, authorized, tenant-scoped, atomic, auditable, backward-compatible, and future-compatible.

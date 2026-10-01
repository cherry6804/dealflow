# ADR-0010: Lead Assignment and Ownership

- Status: Accepted
- Date: 2026-10-01
- Sprint: S04
- Story: DF-45
- Related Stories: DF-39, DF-40, DF-42, DF-43, DF-44, DF-46, DF-47

## 1. Context

DealFlow Lead Management requires an explicit and reliable ownership model.

A Lead represents an actively managed business opportunity within an Organization. A Lead may be worked by different users over its lifecycle, but the system must always be able to determine the current responsible owner when ownership is assigned.

DF-44 introduced `owner_user_id` on the Lead entity and established basic ownership validation during Lead updates.

DF-45 formalizes ownership as a first-class business capability and defines the rules governing:

- assignment;
- reassignment;
- unassignment;
- ownership validation;
- tenant isolation;
- active membership requirements;
- authorization;
- persistence;
- API behavior;
- future ownership history;
- compatibility with automation and AI.

The ownership model must remain consistent with DealFlow's tenant architecture.

A Lead belongs to exactly one Organization.

A User may belong to multiple Organizations through Membership records.

Therefore, a User identity alone is not sufficient to establish whether that User is eligible to own a Lead. Ownership eligibility must be evaluated through the User's active Membership in the Lead's Organization.

The system must not allow a client to bypass tenant boundaries by supplying an arbitrary Organization identifier or by assigning a Lead to a User from another Organization.

---

# 2. Decision

DealFlow will use `Lead.owner_user_id` as the canonical current ownership field.

Ownership will be represented as:

```text
Lead
 ├── organization_id
 └── owner_user_id
        ↓
      User
        ↓
Organization Membership
        ↓
    Organization

The Lead's organization_id remains the authoritative tenant boundary.
A Lead owner is eligible only when:
1. the referenced User exists;
2. the User has an active Membership in the Lead's Organization;
3. the Membership belongs to the same Organization as the Lead.
Ownership is optional.
Therefore:
owner_user_id = NULL

means the Lead is currently unassigned.
The system will support:
- assigning an unassigned Lead;
- reassigning an owned Lead;
- unassigning a Lead.
DF-45 will build upon the existing DF-44 Lead update mechanism instead of introducing a second ownership field or competing ownership model.
3. Ownership Model
3.1 Lead
The Lead remains the business object being assigned.
Relevant fields:
id
organization_id
contact_id
owner_user_id
status
interest
outcome
next_action
next_action_at
is_active
created_at
updated_at

owner_user_id represents the current responsible User.
It does not represent ownership of the Organization, Contact, Customer, Property, or Deal.
3.2 User
A User represents an identity in DealFlow.
A User may belong to multiple Organizations.
Therefore:
User ≠ Organization Membership

A User's existence does not by itself grant access to a Lead.
3.3 Membership
Membership establishes a User's participation in an Organization.
Ownership eligibility is therefore evaluated using Membership.
The effective rule is:
Lead.organization_id
        ==
Membership.organization_id

AND

Lead.owner_user_id
        ==
Membership.user_id

AND

Membership.is_active
        ==
true

4. Assignment Rules
4.1 Assign Lead
An unassigned Lead may be assigned to an eligible User.
Example:
Lead.owner_user_id = NULL

        ↓ assignment

Lead.owner_user_id = User A

User A must have an active Membership in the Lead's Organization.
4.2 Reassign Lead
An already-owned Lead may be reassigned.
Example:
Lead.owner_user_id = User A

        ↓ reassignment

Lead.owner_user_id = User B

User B must satisfy the same organization and active-membership requirements.
The previous owner does not need to remain active for reassignment to a different eligible owner.
4.3 Unassign Lead
Ownership may be removed:
Lead.owner_user_id = User A

        ↓ unassignment

Lead.owner_user_id = NULL

Unassignment does not delete the Lead.
It does not change the Lead status.
It does not change Lead outcome.
It does not deactivate the Lead.
It only removes the current owner.
5. Ownership and Lead Lifecycle
Ownership is independent from Lead lifecycle status.
For example:
status = QUALIFIED
owner = User A

and:
status = QUALIFIED
owner = NULL

are both valid states.
Ownership must not automatically change because the Lead status changes.
Examples:
QUALIFIED → MATCHING

does not automatically change ownership.
NEGOTIATION → WON

does not automatically remove ownership.
NEGOTIATION → LOST

does not automatically remove ownership.
Lifecycle and ownership remain separate concepts.
6. Ownership and Active State
Ownership is independent from Lead.is_active.
The following states are therefore possible:
is_active = true
owner_user_id = NULL

and:
is_active = false
owner_user_id = User A

Changing is_active must not silently assign or remove an owner.
Likewise, assigning or unassigning an owner must not automatically change is_active.
7. Tenant Isolation
Tenant isolation is mandatory.
A Lead belonging to Organization A must not be assigned to a User whose active Membership exists only in Organization B.
Invalid example:
Lead
organization_id = A

User B
membership.organization_id = B

This assignment must be rejected.
The client must not be able to override this rule by providing:
organization_id = B

The Organization context comes from the authenticated tenant context.
The client does not choose the tenant used for authorization or ownership validation.
8. Multi-Tenant User Membership
A User may legitimately belong to multiple Organizations.
Example:
User X
 ├── Membership → Organization A
 └── Membership → Organization B

User X may therefore own:
Lead A → Organization A → User X

and:
Lead B → Organization B → User X

This is valid because ownership is evaluated against the Lead's Organization.
The same User identity may therefore be an eligible owner in multiple tenants without weakening tenant isolation.
9. Active Membership Requirement
Only an active Membership may receive ownership.
Example:
User X
Membership A
is_active = false

User X must not be assignable to a Lead belonging to Organization A.
This rule prevents inactive tenant participants from receiving new ownership.
Existing ownership records are not automatically rewritten merely because membership state changes.
Membership lifecycle and Lead ownership are separate domains.
If an existing owner becomes inactive, the Lead remains historically associated with that User through owner_user_id until an authorized business operation changes the ownership.
Future automation or ownership-health workflows may identify such records for reassignment.
DF-45 does not introduce automatic reassignment.
10. Non-Existent Owner
A Lead must not reference a non-existent User.
If an assignment request contains an unknown User ID, the operation must fail without modifying the Lead.
The system must not create Users as a side effect of Lead assignment.
11. Cross-Tenant Owner
A User existing in the database is not automatically an eligible owner.
The following is invalid:
Lead.organization_id = Organization A

User.id = User B

User B has no active Membership in Organization A

The assignment must fail.
The Lead must remain unchanged.
12. Authorization
Ownership changes are protected by the Lead update authorization boundary established by DF-44.
The existing permission:
leads.update

controls modification of Lead ownership through the Lead update API.
DF-45 does not introduce an independent authorization mechanism that could bypass the established Lead authorization model.
Authorization evaluation remains:
Authenticated User
        ↓
Tenant Context
        ↓
Permission
        ↓
Lead Ownership Operation

Permission checks must occur before the business operation is allowed to mutate the Lead.
Unauthorized requests must not modify ownership.
13. Tenant Context
Ownership operations must use the existing tenant-context mechanism.
Tenant context is derived from:
Authenticated User
+
Authorized Membership

It must not be trusted from arbitrary client input.
The ownership service receives the resolved Organization ID from the authorized tenant context.
14. API Boundary
DF-45 builds on the existing Lead update endpoint:
PATCH /api/v1/leads/{lead_id}

Ownership is represented through:
{
  "owner_user_id": "USER_UUID"
}

Assignment:
{
  "owner_user_id": "USER_UUID"
}

Unassignment:
{
  "owner_user_id": null
}

The response continues to expose:
{
  "owner_user_id": "USER_UUID"
}

or:
{
  "owner_user_id": null
}

A separate ownership endpoint will not be introduced unless a future requirement establishes behavior that cannot be represented safely through the existing Lead update contract.
This avoids duplicate mutation paths.
15. PATCH Semantics
The existing PATCH semantics remain important.
An omitted field:
{}

means:
Do not modify ownership.

An explicit value:
{
  "owner_user_id": "USER_UUID"
}

means:
Assign or reassign ownership.

An explicit null:
{
  "owner_user_id": null
}

means:
Remove ownership.

This distinction must remain preserved.
16. Atomicity
Ownership validation and mutation must be atomic.
An invalid assignment must not leave the Lead partially updated.
For example, if:
owner_user_id

is invalid because the target User is not an active member of the Organization, the Lead must retain its previous owner.
The transaction must not persist the invalid ownership.
17. Existing Owner Preservation
When reassignment validation fails, the existing owner must remain unchanged.
Example:
Current owner = User A

Attempt:
assign User B

User B is invalid

Result:
Current owner = User A

The failed request must not produce:
Current owner = NULL

or any other unintended state.
18. Ownership Does Not Imply Other Permissions
Being the owner of a Lead does not automatically grant additional system permissions.
Ownership:
Lead.owner_user_id

and authorization:
Permission
Role
MembershipRole

remain separate concepts.
A User may own a Lead while still requiring appropriate permissions to perform protected operations.
Likewise, having a permission does not automatically make a User an owner.
19. Ownership Does Not Transfer Contact Ownership
Assigning a Lead does not change:
Contact

ownership or identity.
A Contact may have multiple Leads.
Example:
Contact X
 ├── Lead A → User A
 └── Lead B → User B

This remains valid.
Lead ownership is therefore scoped to the Lead rather than the Contact.
20. Ownership and Future DealFlow Domains
The ownership model is designed to support future domains including:
- Requirements;
- Property matching;
- Site visits;
- Negotiation;
- Deals;
- Follow-ups;
- Automation;
- Notifications;
- Reporting;
- AI assistance.
Future capabilities may use Lead ownership as an input.
For example:
Lead
  ↓
Owner
  ↓
Follow-up
  ↓
Notification

or:
Lead
  ↓
Owner
  ↓
AI recommendation

Such future capabilities must not reinterpret owner_user_id as unrestricted authorization.
21. Ownership History
DF-45 defines the current owner.
It does not replace the need for historical ownership records.
Future versions may introduce a dedicated ownership history model such as:
LeadOwnershipHistory

with information including:
lead_id
organization_id
previous_owner_user_id
new_owner_user_id
changed_by_user_id
changed_at
reason

This is intentionally not introduced in DF-45 unless required by the current implementation.
The current Lead record remains the source of truth for current ownership.
Future historical functionality must remain backward compatible with the current model.
22. Auditability
Ownership changes are security-sensitive business operations.
The architecture must support attribution of:
who changed ownership
when it changed
which tenant it occurred in
which Lead was affected

The existing authorization audit mechanism records authorization decisions.
Future business audit/history capabilities may separately record successful ownership changes.
DF-45 must not weaken existing authorization auditing.
23. Error Handling
Expected ownership validation failures use predictable API behavior.
Lead not found
HTTP 404
Lead not found.

Invalid owner
HTTP 400

with a stable business-validation message.
Owner not in organization
HTTP 400

Owner membership inactive
HTTP 400

Unauthorized operation
HTTP 403
Permission denied.

Malformed request
HTTP 422

Cross-tenant Lead lookup remains protected by the existing tenant-safe Lead retrieval behavior.
24. Database Integrity
The existing Lead model contains:
organization_id
owner_user_id

and the ownership relationship is constrained through the tenant membership relationship.
The database relationship must not permit arbitrary organization membership references that violate the Lead tenant boundary.
Application-level validation remains required because relational integrity alone does not establish the business authorization decision.
25. Service Layer
Ownership validation belongs in the Lead service/domain operation rather than being implemented only inside the HTTP route.
The service layer must:
1. load the Lead within the authorized Organization;
2. determine whether ownership was supplied;
3. validate the target User/Membership;
4. reject invalid ownership;
5. apply the ownership change;
6. flush the transaction;
7. return the updated Lead.
This keeps business rules reusable by future non-HTTP workflows.
26. Determinism
Ownership operations must produce deterministic behavior.
For the same:
organization
lead
owner
authorization state

the same validation result must be produced.
No implicit owner selection is introduced by DF-45.
The system must not randomly or automatically choose a User when owner_user_id is omitted.
27. No Silent Assignment
The system must not automatically assign a Lead merely because:
- a User created the Lead;
- a User imported the Contact;
- a User performed a search;
- a User created a Requirement;
- a User viewed the Lead;
- a User modified another Lead;
- a Contact belongs to a particular employee.
Assignment must be explicit unless a future documented automation policy deliberately introduces automatic assignment.
28. Import Compatibility
Imported Contacts and historical records must not automatically acquire Lead ownership.
If an imported dataset explicitly contains an owner and a future import workflow supports owner mapping, the owner must still be validated against the target Organization.
Invalid owner references must not silently create ownership.
DF-45 does not change the existing principle that imported historical data must not silently become active operational ownership.
29. AI Compatibility
Future AI capabilities may recommend:
"Assign this Lead to User X."

However, AI recommendations do not constitute authorization.
An AI-generated assignment must pass the same:
Identity
→ Tenant
→ Permission
→ Membership
→ Ownership validation
→ Audit

boundaries as a human-triggered operation.
AI must not bypass tenant or membership restrictions.
30. Security Requirements
The following are mandatory:
- Tenant isolation.
- Authenticated user context.
- Authorized tenant membership.
- Permission enforcement.
- Active membership validation.
- No arbitrary organization selection.
- No cross-tenant ownership.
- No automatic user creation.
- Atomic mutation.
- Predictable error handling.
- Existing authorization audit preservation.
31. Testing Requirements
DF-45 must include dedicated tests covering at minimum:
Assignment
- assign an unassigned Lead;
- assign to an active same-tenant member;
- verify returned owner;
- verify persisted owner.
Reassignment
- reassign from User A to User B;
- verify previous owner is replaced;
- verify invalid reassignment preserves previous owner.
Unassignment
- explicitly set owner to null;
- verify Lead becomes unassigned.
Validation
- non-existent User;
- User without Membership;
- User with inactive Membership;
- User belonging only to another Organization;
- User belonging to multiple Organizations but active in the Lead's Organization.
Authorization
- missing permission;
- denied permission;
- authorization audit;
- allowed authorization behavior.
Tenant isolation
- cross-tenant Lead;
- cross-tenant owner;
- organization context mismatch.
Regression
All existing Lead tests must remain green.
The full backend suite must pass.
32. Compatibility
DF-45 must remain backward compatible with:
- DF-42 Lead create/retrieve;
- DF-43 Lead list/search/filtering;
- DF-44 Lead update/lifecycle;
- existing Lead response schemas;
- existing tenant dependencies;
- existing authorization dependencies.
Existing API clients that do not provide:
owner_user_id

must continue to work.
Existing Leads with:
owner_user_id = NULL

remain valid.
33. Implementation Boundaries
DF-45 includes:
- formal ownership rules;
- ownership validation;
- assignment;
- reassignment;
- unassignment;
- ownership-specific tests;
- tenant/security regression coverage.
DF-45 does not include:
- automatic round-robin assignment;
- territory assignment;
- workload balancing;
- ownership history UI;
- notifications;
- reminders;
- AI assignment;
- commission ownership;
- team hierarchy;
- sales forecasting.
Those capabilities may be addressed by future stories.
34. Relationship to DF-46
DF-46 addresses:
Lead Next Action & Outcome Management

Ownership and next-action management remain separate concepts.
Example:
Lead
 ├── owner_user_id
 ├── next_action
 └── next_action_at

Ownership identifies responsibility.
Next action identifies what needs to happen next.
DF-45 must not automatically create or modify next actions.
35. Relationship to DF-47
DF-47 provides the broader Lead API security and regression coverage.
DF-45 must therefore implement ownership with the security architecture already established rather than relying on DF-47 to repair security gaps later.
DF-47 may consolidate cross-story regression coverage.
36. Decision Summary
DealFlow will treat:
Lead.owner_user_id

as the canonical current owner.
An owner must:
Exist
+
Have an active Membership
+
Belong to the Lead's Organization

Ownership is:
Optional
Tenant-scoped
Explicit
Authorization-controlled
Atomic
Independent of lifecycle status
Independent of Lead active state

The existing Lead PATCH operation remains the primary ownership mutation boundary.
No duplicate ownership model or unnecessary ownership endpoint will be introduced.
Future automation and AI must use the same tenant, identity, authorization and ownership validation boundaries.
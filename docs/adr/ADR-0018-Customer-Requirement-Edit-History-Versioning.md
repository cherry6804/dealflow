# ADR-0018: Customer Requirement Edit History & Versioning

-   **Status:** Proposed
-   **Date:** 2026-10-06
-   **Decision Owners:** DealFlow Engineering
-   **Related Sprint:** DF-S06
-   **Related Story:** DF-56 --- Edit Requirement While Preserving
    History
-   **Related Epic:** DF-E05 --- Customer Requirements
-   **Depends On:** ADR-0012, ADR-0013, ADR-0014, ADR-0015, ADR-0016,
    ADR-0017

------------------------------------------------------------------------

## 1. Context

DealFlow Customer Requirements represent the overall real-estate needs
and preferences of a customer.

The Customer Requirement domain currently supports:

-   budget preferences
-   location preferences
-   property type / BHK preferences
-   possession / parking preferences
-   Lead association
-   Customer Profile association
-   lifecycle state

The Customer Requirement is intentionally maintained as a stable
business entity. Normal edits must modify the current state without
replacing the requirement identity.

DF-56 introduces the requirement to edit a Customer Requirement while
preserving sufficient historical information to understand how the
requirement changed over time.

The existing authorization audit architecture is responsible for
security and authorization events. It must not be repurposed as the
primary business-history store for Customer Requirement versions.

The design must therefore provide a dedicated, tenant-safe, immutable
business-history mechanism.

------------------------------------------------------------------------

## 2. Decision

DealFlow will introduce a dedicated immutable Customer Requirement
history/version entity:

`CustomerRequirementHistory`

The history entity will store versioned snapshots of the Customer
Requirement aggregate.

The current Customer Requirement remains the authoritative current
state.

Historical versions will be append-only and must not be modified or
deleted through normal Customer Requirement lifecycle operations.

The relationship will be:

``` text
CustomerRequirement
        |
        | 1:N
        v
CustomerRequirementHistory
```

Each successful business change that requires historical preservation
will create a new immutable history version in the same database
transaction as the current-state change.

The history mechanism will preserve the Customer Requirement identity:

``` text
CustomerRequirement.id
CustomerRequirement.organization_id
```

Normal edits must never replace these values.

------------------------------------------------------------------------

## 3. Goals

DF-56 must provide:

-   editable Customer Requirements
-   stable Customer Requirement identity
-   tenant-safe history
-   immutable historical versions
-   version ordering
-   actor attribution
-   change timestamp
-   sufficient state reconstruction
-   preservation of historical business information
-   transaction-safe history creation
-   backward compatibility with existing requirements
-   compatibility with future audit and AI capabilities

------------------------------------------------------------------------

## 4. Non-Goals

DF-56 does not introduce:

-   property matching
-   property ranking
-   property recommendations
-   property availability
-   property inventory
-   workflow automation
-   lead scoring
-   customer scoring
-   AI-generated requirement changes
-   arbitrary historical data editing
-   historical version deletion APIs
-   historical version restoration APIs
-   complete organization-wide audit redesign
-   replacement of the existing authorization audit architecture

Future capabilities must be introduced through explicit stories and
architectural decisions.

------------------------------------------------------------------------

## 5. Domain Responsibility

### 5.1 Customer Requirement

`CustomerRequirement` remains the current business representation of the
customer's requirement.

Conceptually:

``` text
Customer Requirement
├── Core requirement state
│   ├── status
│   ├── is_active
│   ├── budget
│   ├── Lead association
│   └── Customer Profile association
│
├── Location preferences
│
├── Property / BHK preferences
│
└── Possession / Parking preferences
```

### 5.2 Customer Requirement History

`CustomerRequirementHistory` represents an immutable historical version
of the Customer Requirement aggregate.

A historical version must be sufficient to understand the requirement
state represented by that version.

The history record is not the current Customer Requirement.

It is a historical record of the state that existed at a particular
version.

------------------------------------------------------------------------

## 6. Current Requirement Identity

The following values must remain stable during normal edits:

-   Customer Requirement `id`
-   owning `organization_id`
-   creation identity
-   historical identity of the requirement

An edit must update the existing requirement rather than delete and
recreate it.

The system must never implement requirement editing as:

``` text
DELETE old requirement
CREATE new requirement
```

Instead:

``` text
UPDATE existing requirement
CREATE immutable history version
```

------------------------------------------------------------------------

## 7. History Storage Model

The initial implementation will use one dedicated history table with an
immutable aggregate snapshot.

Conceptually:

``` text
customer_requirement_history

id
customer_requirement_id
organization_id
version
actor_id
occurred_at
change_type
snapshot
```

### 7.1 Identity

`id`

-   UUID
-   unique identity for the history record

### 7.2 Customer Requirement

`customer_requirement_id`

-   identifies the Customer Requirement represented by the history
    version
-   must be tenant-safe

### 7.3 Organization

`organization_id`

-   identifies the owning tenant
-   must be derived from verified tenant context
-   must not be supplied as authoritative ownership by the client

### 7.4 Version

`version`

-   positive integer
-   monotonically increasing for a Customer Requirement
-   unique within a tenant-owned Customer Requirement

The intended invariant is:

``` text
(customer_requirement_id, organization_id, version)
```

must be unique.

### 7.5 Actor

`actor_id`

Identifies the authenticated application user responsible for the
business change when an authenticated user is available.

The actor value must be derived from trusted application context.

The client must not be allowed to impersonate another actor by supplying
an arbitrary actor identifier.

### 7.6 Occurred At

`occurred_at`

Records when the historical version was created.

The timestamp is generated by the server/database.

### 7.7 Change Type

`change_type`

Identifies the reason or category of the history entry.

The initial implementation should support an explicit controlled value
for requirement edits.

Future change categories must be introduced explicitly rather than
allowing uncontrolled arbitrary values.

### 7.8 Snapshot

`snapshot`

Stores the immutable historical representation of the Customer
Requirement aggregate.

The snapshot must contain the relevant state required to understand the
requirement at that version.

------------------------------------------------------------------------

## 8. Snapshot Contents

The snapshot must cover the Customer Requirement aggregate rather than
only the parent scalar fields.

The initial snapshot structure should contain:

``` text
{
  "requirement": {
    "id": "...",
    "organization_id": "...",
    "status": "...",
    "is_active": true,
    "budget_min": "...",
    "budget_max": "...",
    "budget_currency": "...",
    "lead_id": "...",
    "customer_profile_id": "...",
    "created_at": "...",
    "updated_at": "..."
  },

  "locations": [
    {
      "id": "...",
      "organization_id": "...",
      "customer_requirement_id": "...",
      "city": "...",
      "locality": "...",
      "is_active": true,
      "created_at": "...",
      "updated_at": "..."
    }
  ],

  "property_preferences": [
    {
      "id": "...",
      "organization_id": "...",
      "customer_requirement_id": "...",
      "property_type": "...",
      "bhk_min": 2,
      "bhk_max": 3,
      "is_active": true,
      "created_at": "...",
      "updated_at": "..."
    }
  ],

  "possession_parking_preference": {
    "id": "...",
    "organization_id": "...",
    "customer_requirement_id": "...",
    "possession_preference": "...",
    "parking_preference": "...",
    "parking_spaces_min": 1,
    "is_active": true,
    "created_at": "...",
    "updated_at": "..."
  }
}
```

Nullable associations and optional child records must be represented
explicitly.

The snapshot format is an internal historical representation and is not
the primary relational representation of the live Customer Requirement
domain.

------------------------------------------------------------------------

## 9. Snapshot Immutability

Once a history version is persisted:

-   its snapshot must not be changed
-   its version must not be changed
-   its actor must not be changed
-   its timestamp must not be changed
-   its Customer Requirement identity must not be changed
-   its organization ownership must not be changed

Normal Customer Requirement update APIs must never modify existing
history rows.

------------------------------------------------------------------------

## 10. Version Semantics

A Customer Requirement history sequence will use monotonically
increasing versions.

Example:

``` text
Requirement
    |
    +-- Version 1
    +-- Version 2
    +-- Version 3
    +-- Version 4
```

A new successful edit creates the next version.

The version must belong to exactly one Customer Requirement within its
tenant.

Version numbers must not be reused.

The implementation must avoid creating duplicate versions for a single
successful operation.

------------------------------------------------------------------------

## 11. Initial Version

The initial implementation will create a baseline history version when a
Customer Requirement is first created.

Therefore a newly created requirement can have:

``` text
Version 1 = initial requirement state
```

Later successful edits create:

``` text
Version 2
Version 3
Version 4
...
```

This provides a complete history starting from the requirement's initial
persisted state.

The creation and initial history record must be committed atomically.

------------------------------------------------------------------------

## 12. Edit Semantics

A normal edit follows this sequence:

``` text
Authenticated request
        |
        v
Tenant context verification
        |
        v
Permission verification
        |
        v
Load Customer Requirement
        |
        v
Validate requested changes
        |
        v
Apply current-state changes
        |
        v
Build complete aggregate snapshot
        |
        v
Create next history version
        |
        v
Commit transaction
```

If validation fails:

``` text
No current-state change
No history version
```

If history persistence fails:

``` text
Current-state change must not be committed
```

This prevents the current requirement from becoming inconsistent with
its historical record.

------------------------------------------------------------------------

## 13. Partial Update Semantics

Existing PATCH semantics must be preserved.

For update requests:

-   omitted fields remain unchanged
-   explicitly supplied nullable fields may be cleared when the domain
    permits clearing
-   validation applies to the final resulting state
-   unchanged fields must remain unchanged

The history snapshot represents the complete resulting aggregate state
after the successful edit.

For example:

``` text
Existing:
budget_min = 50L
budget_max = 80L
currency = INR

PATCH:
budget_max = 90L
```

Result:

``` text
Current:
budget_min = 50L
budget_max = 90L
currency = INR

History:
contains complete post-edit state
```

------------------------------------------------------------------------

## 14. Child Entity Changes

Customer Requirement child entities are part of the requirement
aggregate for historical purposes.

This includes:

-   location changes
-   property/BHK preference changes
-   possession/parking preference changes
-   relevant Lead/Customer association changes

When a child change is considered a Customer Requirement business
change, the history snapshot must represent the resulting complete
aggregate state.

The implementation must avoid recording an incomplete snapshot.

For example, a location update must not create a history snapshot that
omits the existing budget or property preferences.

------------------------------------------------------------------------

## 15. Transaction Boundary

The current-state modification and corresponding history creation must
occur in the same transaction.

Required behavior:

``` text
BEGIN
    update current requirement
    create history version
COMMIT
```

If either operation fails:

``` text
ROLLBACK
```

No partial business state may remain committed.

This is required to preserve historical integrity.

------------------------------------------------------------------------

## 16. Tenant Isolation

All history operations must be tenant-scoped.

Required controls include:

-   authenticated tenant context
-   server-controlled organization ownership
-   tenant-safe Customer Requirement lookup
-   tenant-safe history lookup
-   tenant-safe version creation
-   no client-controlled organization ownership
-   cross-tenant access denial

A history record belonging to organization A must never be returned to a
request operating under organization B.

A Customer Requirement from organization A must never be used to create
or retrieve history under organization B.

------------------------------------------------------------------------

## 17. Authorization

Requirement history retrieval and requirement editing must use the
existing requirement permissions.

Initial direction:

``` text
Read requirement/history
    -> requirements.read

Modify requirement
    -> requirements.update
```

The history endpoint must not create a new permission unless a future
authorization decision requires a separate permission.

The authorization layer remains responsible for access decisions.

The business-history layer remains responsible for historical state.

------------------------------------------------------------------------

## 18. Authorization Audit Compatibility

Customer Requirement history and authorization auditing are separate
concerns.

The existing authorization audit architecture remains responsible for
recording security decisions such as:

-   allowed authorization
-   denied authorization
-   permission checks
-   actor
-   resource
-   action

The new `CustomerRequirementHistory` entity is responsible for
business-state history.

Conceptually:

``` text
Security authorization
        |
        v
AuditEvent
```

and:

``` text
Customer Requirement business change
        |
        v
CustomerRequirementHistory
```

A single request may therefore produce both:

``` text
Authorization audit event
+
Business history version
```

These records must not be treated as interchangeable.

------------------------------------------------------------------------

## 19. History Retrieval API

DF-56 will expose tenant-scoped history retrieval.

Initial API direction:

``` text
GET /api/v1/customer-requirements/{requirement_id}/history
```

The endpoint must:

-   require `requirements.read`
-   verify tenant ownership
-   return history belonging only to the requested requirement
-   order versions deterministically
-   avoid exposing another tenant's history
-   return immutable historical information

The exact pagination strategy may be introduced when history volume
requires it, but the initial implementation should establish
deterministic ordering.

------------------------------------------------------------------------

## 20. History Version Retrieval

The design should support retrieving an individual version through the
history domain.

Initial direction:

``` text
GET /api/v1/customer-requirements/{requirement_id}/history/{version}
```

The endpoint must verify:

``` text
requirement_id
+
organization_id
+
version
```

before returning a historical record.

No client-supplied organization identifier may override tenant context.

------------------------------------------------------------------------

## 21. No History Mutation API

DF-56 will not expose APIs that modify or delete history.

There will be no:

``` text
PATCH /history/...
PUT /history/...
DELETE /history/...
```

through the Customer Requirement business API.

History is append-only.

Any future legal, compliance, retention, or administrative deletion
capability must be introduced through a separate explicit architectural
decision.

------------------------------------------------------------------------

## 22. Requirement Restoration

DF-56 does not introduce restoration from history.

Historical versions are for:

-   understanding previous states
-   change tracking
-   future audit/reporting
-   future comparison
-   future AI/context capabilities

Restoring an old version would itself be a new business change and
requires a separate future decision.

------------------------------------------------------------------------

## 23. Concurrency

The history implementation must protect version sequencing when multiple
updates occur concurrently.

The implementation must ensure that two successful edits cannot both
persist the same version number.

The preferred implementation should use database-backed uniqueness plus
safe version allocation/transaction handling.

The system must treat version conflicts as transactional failures rather
than silently overwriting historical information.

------------------------------------------------------------------------

## 24. Data Validation

History persistence must not bypass normal domain validation.

The sequence must be:

``` text
Request validation
        |
        v
Domain validation
        |
        v
Current-state update
        |
        v
Snapshot generation
        |
        v
History persistence
```

A history row must never be created for a state that could not
legitimately exist as a Customer Requirement state.

------------------------------------------------------------------------

## 25. Backward Compatibility

Existing Customer Requirements remain valid.

Existing records must not require manual migration of business data.

The history migration must:

-   be additive
-   be tenant-safe
-   avoid destructive changes
-   preserve existing requirement identities
-   preserve existing requirement data

For existing Customer Requirements created before DF-56, the
implementation must not fabricate historical events that did not
actually occur.

The system may establish history going forward from DF-56 rather than
inventing unknown historical states.

------------------------------------------------------------------------

## 26. Future Compatibility

The design must support future capabilities such as:

-   requirement comparison
-   requirement change summaries
-   customer-facing change timelines
-   approval workflows
-   AI-assisted requirement editing
-   AI-generated change explanations
-   analytics
-   compliance reporting
-   advanced audit
-   restoration through an explicit future workflow

Future capabilities must use the same tenant, identity, permission,
policy, and audit boundaries.

AI must not directly modify history rows.

AI-generated requirement changes must use authorized application/service
paths.

------------------------------------------------------------------------

## 27. AI Boundaries

DF-56 does not introduce AI functionality.

However, the history design must be compatible with future AI
capabilities.

Future AI may use requirement history to understand:

``` text
what the customer wanted originally
what changed
when it changed
who changed it
what the current requirement is
```

AI must not:

-   directly edit history
-   bypass requirement permissions
-   bypass tenant isolation
-   impersonate actors
-   silently modify Customer Requirements
-   create uncontrolled historical records

All AI-generated changes must pass through authorized DealFlow service
paths.

------------------------------------------------------------------------

## 28. Security Requirements

Required controls include:

-   authentication
-   tenant isolation
-   permission enforcement
-   server-controlled organization ownership
-   tenant-safe foreign keys
-   immutable history
-   actor attribution
-   controlled resource lookup
-   transaction-safe history creation
-   no uncontrolled history mutation
-   no cross-tenant history access

Security authorization events remain under the existing audit
architecture.

Business history remains under the Customer Requirement history
architecture.

------------------------------------------------------------------------

## 29. Performance Considerations

Initial DF-56 implementation should optimize for correctness and
integrity rather than premature history optimization.

Indexes should support tenant-scoped history access by:

-   organization_id
-   customer_requirement_id
-   version
-   occurred_at

The common retrieval pattern is expected to be:

``` text
organization
+
customer_requirement
+
ordered history
```

Future pagination and archival strategies may be introduced if history
volume becomes significant.

------------------------------------------------------------------------

## 30. Testing Requirements

### 30.1 Model Tests

Verify:

-   history model identity
-   UUID generation
-   required fields
-   tenant ownership
-   Customer Requirement relationship
-   version uniqueness
-   version ordering constraints
-   actor attribution
-   timestamp generation
-   snapshot persistence

### 30.2 Creation Tests

Verify:

-   new requirement creation
-   initial history version creation
-   version starts at the expected baseline
-   history contains the initial state
-   history and requirement are committed together
-   failed creation does not create orphan history

### 30.3 Update Tests

Verify:

-   successful requirement edit
-   budget change
-   lifecycle change
-   association change
-   location-related change
-   property/BHK-related change
-   possession/parking-related change
-   multiple changes
-   omitted fields remain unchanged
-   explicit nullable values behave according to domain rules
-   each successful change creates a new version
-   history contains complete resulting state

### 30.4 History Retrieval Tests

Verify:

-   authenticated history retrieval
-   permission enforcement
-   tenant isolation
-   requirement isolation
-   deterministic version ordering
-   individual version retrieval
-   missing requirement behavior
-   missing version behavior
-   invalid UUID behavior

### 30.5 Immutability Tests

Verify:

-   normal APIs cannot modify history
-   normal APIs cannot delete history
-   historical snapshots remain unchanged after later requirement edits

### 30.6 Transaction Tests

Verify:

-   failed validation creates no history
-   failed current-state update creates no history
-   failed history persistence does not commit current-state changes
-   successful current-state change and history version commit
    atomically

### 30.7 Concurrency Tests

Verify:

-   concurrent edits do not silently reuse a version
-   version uniqueness is enforced
-   failed version allocation does not corrupt current state

### 30.8 Regression

All existing DealFlow backend tests must continue to pass, including:

-   authentication
-   authorization
-   tenant isolation
-   contacts
-   leads
-   customer requirements
-   budget
-   location preferences
-   property preferences
-   possession / parking preferences
-   Lead / Customer Profile associations
-   existing APIs

------------------------------------------------------------------------

## 31. Migration Requirements

The DF-56 migration must:

-   create the history table
-   create tenant-safe Customer Requirement relationship
-   create required uniqueness constraints
-   create required indexes
-   be additive
-   be reversible
-   avoid modifying existing Customer Requirement rows
-   avoid fabricating historical business events

The migration must be verified with:

``` text
alembic upgrade
alembic current
alembic heads
alembic check
```

Any known pre-existing Alembic drift unrelated to DF-56 must remain
outside this story unless explicitly required by the DF-56
implementation.

------------------------------------------------------------------------

## 32. Service Layer Responsibility

The service layer owns:

-   tenant-scoped requirement retrieval
-   requirement update validation
-   aggregate state loading
-   aggregate snapshot generation
-   version allocation
-   immutable history creation
-   transaction-safe persistence
-   history retrieval
-   history version retrieval
-   relationship validation
-   future lifecycle validation

The API layer owns:

-   HTTP routing
-   request parsing
-   dependency injection
-   permission dependencies
-   HTTP error translation
-   response serialization

The API must not implement history persistence directly.

------------------------------------------------------------------------

## 33. API Responsibility

The API must:

-   obtain verified tenant context
-   enforce existing requirement permissions
-   pass authenticated actor context to the service layer
-   invoke tenant-scoped service methods
-   translate domain/service errors into HTTP responses
-   return immutable history representations

The API must not trust client-supplied:

-   organization ownership
-   historical actor identity
-   history version
-   history timestamp
-   history identity

where those values are server-controlled.

------------------------------------------------------------------------

## 34. Data Ownership

The Customer Requirement owns the business meaning of its history.

The history record is subordinate to the Customer Requirement domain but
must retain sufficient identity and tenant information to support safe
historical retrieval.

Historical data must remain attributable to:

``` text
Customer Requirement
+
Organization
+
Actor
+
Version
+
Timestamp
```

------------------------------------------------------------------------

## 35. Consequences

### Positive consequences

This decision provides:

-   stable Customer Requirement identity
-   immutable business history
-   complete aggregate snapshots
-   tenant-safe historical access
-   actor attribution
-   deterministic versions
-   transaction-safe state changes
-   future comparison capability
-   future AI context capability
-   clean separation between security audit and business history
-   compatibility with existing Customer Requirement architecture

### Trade-offs

This decision introduces:

-   an additional database table
-   snapshot serialization
-   additional service logic
-   version allocation logic
-   additional API endpoints
-   additional tests
-   additional storage over time
-   concurrency considerations

These costs are intentional because preserving Customer Requirement
history is a business integrity requirement.

------------------------------------------------------------------------

## 36. Implementation Order

``` text
ADR-0018
    |
    v
CustomerRequirementHistory model
    |
    v
Alembic migration
    |
    v
History snapshot builder
    |
    v
Requirement creation history
    |
    v
Requirement update integration
    |
    v
History retrieval service
    |
    v
History API
    |
    v
Authorization verification
    |
    v
Tenant isolation verification
    |
    v
Focused DF-56 tests
    |
    v
Full regression
    |
    v
git diff --check
    |
    v
Commit
    |
    v
Push
    |
    v
Single complete PR
    |
    v
Merge
    |
    v
Develop verification
    |
    v
Feature branch cleanup
```

------------------------------------------------------------------------

## 37. Acceptance Criteria

DF-56 is complete when:

-   [ ] ADR-0018 is committed
-   [ ] CustomerRequirementHistory model exists
-   [ ] History is tenant-scoped
-   [ ] History is linked safely to Customer Requirement
-   [ ] History versions are unique per requirement
-   [ ] History versions are immutable
-   [ ] Actor attribution exists
-   [ ] Server-controlled timestamp exists
-   [ ] Aggregate snapshot is persisted
-   [ ] Initial requirement history is created
-   [ ] Requirement edits create new history versions
-   [ ] Existing requirement identity remains unchanged
-   [ ] Current and historical state are transactionally consistent
-   [ ] History includes the complete relevant requirement aggregate
-   [ ] Existing PATCH semantics remain compatible
-   [ ] History retrieval is tenant-scoped
-   [ ] Individual version retrieval is tenant-scoped
-   [ ] `requirements.read` is enforced for history reads
-   [ ] `requirements.update` is enforced for requirement changes
-   [ ] Cross-tenant history access is denied
-   [ ] History mutation APIs do not exist
-   [ ] History deletion APIs do not exist
-   [ ] Concurrency cannot silently duplicate versions
-   [ ] Existing requirements are not destructively migrated
-   [ ] No historical events are fabricated for existing records
-   [ ] Focused DF-56 tests pass
-   [ ] Full backend regression passes
-   [ ] Alembic validation passes
-   [ ] `git diff --check` passes
-   [ ] No unrelated changes exist
-   [ ] One complete PR is created
-   [ ] PR is reviewed and merged
-   [ ] `develop` is verified after merge
-   [ ] Feature branch is deleted
-   [ ] Jira DF-56 is marked Done

------------------------------------------------------------------------

## 38. Final Decision Summary

DF-56 will preserve Customer Requirement history through a dedicated
immutable `CustomerRequirementHistory` entity.

The live Customer Requirement remains the current source of truth.

Each successful business change produces a new immutable aggregate
snapshot in the same transaction as the current-state change.

Tenant context, identity, permissions, actor attribution, and
transaction boundaries remain foundational controls.

The existing authorization `AuditEvent` architecture remains dedicated
to authorization/security auditing and is not replaced by, or merged
with, the Customer Requirement business-history subsystem.

This design preserves backward compatibility while establishing a
foundation for future requirement comparison, audit reporting, AI
context, and controlled historical capabilities.

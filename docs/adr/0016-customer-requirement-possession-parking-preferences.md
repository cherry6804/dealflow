# ADR-0016: Customer Requirement Possession & Parking Preferences

- **Status:** Accepted
- **Date:** 2026-10-05
- **Decision Owners:** DealFlow Engineering
- **Related Sprint:** DF-S05
- **Related Story:** DF-54 — Capture Possession / Parking Preferences
- **Related Epic:** DF-E05 — Customer Requirements
- **Depends On:** ADR-0012, ADR-0013, ADR-0014, ADR-0015

---

## 1. Context

DealFlow Customer Requirements represent the real-estate needs and preferences of a customer.

The Customer Requirement domain already supports:

- budget preferences
- location preferences
- property type / BHK preferences

DF-54 introduces the ability to capture customer preferences regarding:

- expected possession timing
- parking requirement

These preferences describe what the customer expects from a suitable property. They do not represent actual property inventory, availability, possession schedules, or parking inventory.

The design must remain compatible with future capabilities such as:

- Property Management
- Property Search
- Property Matching
- Property Availability
- Property Ranking
- AI-assisted matching

However, DF-54 must remain intentionally small and must not introduce those capabilities prematurely.

---

## 2. Decision

DealFlow will represent possession and parking preferences as a separate tenant-scoped child entity:

`CustomerRequirementPossessionParkingPreference`

The relationship will be:

```text
CustomerRequirement
        |
        | 1:0..1
        |
        v
CustomerRequirementPossessionParkingPreference
```

A Customer Requirement may therefore contain zero or one preference record.

Unlike DF-53 property-type/BHK preferences, DF-54 does not require multiple alternative configurations because possession and parking are treated as overall requirement attributes.

---

## 3. Domain Responsibility

### 3.1 Customer Requirement

The Customer Requirement represents the customer's overall real-estate need.

Conceptually:

```text
Customer Requirement
├── Budget
├── Location Preferences
├── Property Type / BHK Preferences
├── Possession / Parking Preferences
└── Lead / Customer Association
```

### 3.2 Possession / Parking Preference

The preference entity represents:

- possession timing
- parking requirement
- minimum parking spaces when applicable

It does not determine property availability, actual possession dates, parking inventory, allocation, ranking, recommendations, or pricing suitability.

---

## 4. Persistence Model

| Field | Type | Required | Purpose |
|---|---|---:|---|
| id | UUID | Yes | Preference identity |
| organization_id | UUID | Yes | Tenant ownership |
| customer_requirement_id | UUID | Yes | Parent requirement |
| possession_preference | String | Yes | Desired possession timing |
| parking_preference | String | Yes | Desired parking requirement |
| parking_spaces_min | Integer | No | Minimum desired parking spaces |
| is_active | Boolean | Yes | Preference lifecycle |
| created_at | DateTime | Yes | Creation timestamp |
| updated_at | DateTime | Yes | Modification timestamp |

---

## 5. Possession Preference Vocabulary

Initial controlled vocabulary:

```text
READY_TO_MOVE
WITHIN_3_MONTHS
WITHIN_6_MONTHS
WITHIN_12_MONTHS
AFTER_12_MONTHS
ANY
```

| Value | Meaning |
|---|---|
| READY_TO_MOVE | Customer prefers a property that is ready to move into |
| WITHIN_3_MONTHS | Customer prefers possession within three months |
| WITHIN_6_MONTHS | Customer prefers possession within six months |
| WITHIN_12_MONTHS | Customer prefers possession within twelve months |
| AFTER_12_MONTHS | Customer accepts possession after twelve months |
| ANY | No specific possession timing preference |

Future vocabulary expansion must be an explicit domain change.

---

## 6. Parking Preference Vocabulary

Initial controlled vocabulary:

```text
REQUIRED
PREFERRED
NOT_REQUIRED
ANY
```

| Value | Meaning |
|---|---|
| REQUIRED | Customer requires parking |
| PREFERRED | Customer would prefer parking but it is not mandatory |
| NOT_REQUIRED | Customer does not require parking |
| ANY | Customer has no specific parking preference |

This describes customer intent, not property inventory.

---

## 7. Parking Spaces

`parking_spaces_min` represents the minimum number of parking spaces desired.

When supplied:

- it must be a positive whole number
- zero is invalid
- negative values are invalid
- fractional values are invalid

DF-54 does not calculate or verify parking availability.

---

## 8. Possession Date Semantics

DF-54 will not introduce exact possession dates or date ranges.

The following are outside this story:

```text
possession_date_from
possession_date_to
exact_possession_date
```

If required later, they must be introduced through an explicit future story and domain decision.

---

## 9. Tenant Ownership

The preference is tenant-scoped.

The organization is derived from authenticated tenant context. The client must not determine authoritative organization ownership.

The relationship will use:

```text
(customer_requirement_id, organization_id)
```

referencing:

```text
(customer_requirements.id, organization_id)
```

This prevents attachment to another organization's Customer Requirement.

---

## 10. Tenant Isolation

All DF-54 operations must enforce tenant isolation.

Cross-tenant resources must not be exposed.

Application authorization and database-level tenant-safe relationships must work together.

---

## 11. Lifecycle

The preference uses:

```text
ACTIVE
INACTIVE
```

through:

```text
is_active
```

Inactive preferences are retained rather than physically deleted.

---

## 12. Update Semantics

Updates follow established DealFlow PATCH semantics:

```text
omitted field
    → unchanged

supplied valid value
    → replaced

explicit null
    → cleared when nullable

invalid value
    → rejected
```

`possession_preference` and `parking_preference` remain required for a persisted preference.

`parking_spaces_min` may be explicitly cleared.

`is_active` is independently editable.

Final-state validation must be applied during updates.

---

## 13. Delete Semantics

DF-54 does not introduce destructive deletion as a normal business operation.

The normal business operation is:

```text
is_active = false
```

---

## 14. API Boundaries

### Create

```text
POST /api/v1/customer-requirements/{requirement_id}/possession-parking-preference
```

Permission:

```text
requirements.update
```

### Retrieve

```text
GET /api/v1/customer-requirements/{requirement_id}/possession-parking-preference
```

Permission:

```text
requirements.read
```

### Update

```text
PATCH /api/v1/customer-requirements/{requirement_id}/possession-parking-preference
```

Permission:

```text
requirements.update
```

The preference must belong to the authenticated tenant and requested Customer Requirement.

---

## 15. Authorization

DF-54 follows the existing DealFlow authorization architecture.

Read operations require:

```text
requirements.read
```

Create/update operations require:

```text
requirements.update
```

No client-supplied organization identifier may bypass authorization.

---

## 16. Authentication and Tenant Context

DF-54 APIs require:

1. authenticated user
2. valid tenant context
3. active organization membership
4. required permission

The existing DealFlow tenant-context dependency must be used.

---

## 17. Error Semantics

Expected behavior:

```text
Unauthenticated
    → authentication failure

Missing tenant context
    → tenant-context failure

Permission missing
    → 403

Customer Requirement missing
    → 404

Cross-tenant Customer Requirement
    → 404

Preference missing
    → 404

Cross-tenant Preference
    → 404

Invalid request payload
    → 422

Business validation failure
    → 400
```

Cross-tenant requests must not disclose another tenant's resources.

---

## 18. Database Design

New table:

```text
customer_requirement_possession_parking_preferences
```

Fields:

```text
id
organization_id
customer_requirement_id
possession_preference
parking_preference
parking_spaces_min
is_active
created_at
updated_at
```

The table will have a tenant-safe foreign key to `customer_requirements`.

The migration must be:

- additive
- reversible
- tenant-safe
- backward-compatible
- non-destructive

Existing Customer Requirements remain valid and simply have no DF-54 preference until one is added.

---

## 19. Uniqueness

A Customer Requirement may have at most one DF-54 preference record.

The database should enforce:

```text
UNIQUE (customer_requirement_id, organization_id)
```

This protects the intended 1:0..1 relationship at the persistence layer.

---

## 20. Indexing

Indexes should support efficient tenant-scoped access for:

- organization_id
- customer_requirement_id
- is_active
- possession_preference
- parking_preference

No specialized matching indexes are required.

---

## 21. Future Property Management

DF-54 provides structured requirement input for future Property Management.

Conceptually:

```text
Customer Requirement
        |
        +── Property Preferences
        +── Budget
        +── Locations
        +── Possession / Parking Preferences
                |
                v
        Future Matching Engine
                |
                v
             Properties
```

DF-54 does not create Property records or establish a requirement-to-property relationship.

---

## 22. Future Property Availability

Possession preference may eventually participate in availability matching, but DF-54 does not perform that comparison.

No availability engine, date calculation, ranking, or recommendation is introduced.

---

## 23. AI Boundaries

DF-54 does not introduce AI functionality.

Future AI may assist with interpreting natural-language possession or parking requirements, but must operate within DealFlow identity, permission, tenant, policy, and audit boundaries.

AI must not silently modify customer preferences.

---

## 24. Security Requirements

Required controls include:

- authentication
- tenant isolation
- permission enforcement
- tenant-safe foreign keys
- server-controlled organization ownership
- cross-tenant protection
- controlled resource lookup
- audit compatibility
- no uncontrolled client ownership assignment

There must be no path allowing association with another organization's Customer Requirement.

---

## 25. Performance Considerations

The number of preference records is expected to remain proportional to Customer Requirements.

The initial implementation should prioritize:

- simple queries
- tenant-scoped access
- deterministic behavior
- correct ownership
- maintainability

No specialized search, matching, or recommendation engine is required.

---

## 26. Observability

DF-54 remains compatible with existing DealFlow observability.

Future telemetry should identify:

- preference creation
- preference update
- lifecycle changes
- authorization decisions
- failures

No separate observability subsystem is introduced.

---

## 27. Audit Compatibility

Future audit capabilities should be able to attribute:

- who created the preference
- who changed it
- when it changed
- affected resource
- owning organization

A complete business-history subsystem remains outside DF-54.

---

## 28. Non-Goals

DF-54 does not introduce:

- property matching
- property ranking
- property recommendations
- property availability
- property inventory
- parking inventory
- parking allocation
- property pricing
- affordability calculation
- exact possession dates
- possession date ranges
- furnishing preferences
- floor preferences
- facing preferences
- amenity preferences
- maps
- GPS
- geocoding
- geographic intelligence
- external property APIs
- AI property recommendations
- automatic property inference
- complete history/versioning
- lead association changes
- customer association changes
- property association changes

These require future stories or architectural decisions.

---

## 29. Testing Requirements

### 29.1 Model Tests

Verify:

- model identity
- UUID generation
- required fields
- possession vocabulary
- parking vocabulary
- parking spaces field
- lifecycle default
- timestamps
- tenant ownership
- Customer Requirement relationship
- one-preference-per-requirement constraint

### 29.2 Create API Tests

Verify:

- authenticated creation
- permission enforcement
- valid possession preference
- valid parking preference
- valid parking spaces
- invalid possession preference
- invalid parking preference
- non-positive parking spaces
- missing requirement
- cross-tenant requirement
- malformed payload
- server-controlled organization ownership
- duplicate preference prevention

### 29.3 Retrieve API Tests

Verify:

- authenticated retrieval
- permission enforcement
- correct requirement scoping
- tenant isolation
- missing preference behavior

### 29.4 Update API Tests

Verify:

- possession update
- parking update
- parking spaces update
- independent field updates
- lifecycle updates
- explicit null handling
- invalid payload
- invalid final state
- cross-tenant access
- requirement/preference mismatch
- authorization

### 29.5 Regression

All existing DealFlow backend tests must continue to pass, including authentication, authorization, tenant isolation, contacts, leads, customer requirements, budget, location preferences, property preferences, and existing APIs.

---

## 30. Backward Compatibility

Existing Customer Requirements remain valid.

A requirement without a DF-54 preference remains valid.

The migration must not:

- fabricate preferences
- modify existing requirements
- require possession preferences
- require parking preferences
- perform destructive transformations

---

## 31. Future Compatibility

Future capabilities may introduce:

- exact possession dates
- possession date ranges
- additional possession semantics
- structured parking requirements
- property availability integration
- matching rules
- property metadata

These must be introduced progressively through explicit stories and domain decisions.

Existing records must remain valid as the Property domain evolves.

---

## 32. Implementation Order

```text
ADR-0016
    |
    v
CustomerRequirementPossessionParkingPreference model
    |
    v
CustomerRequirement relationship
    |
    v
Alembic migration
    |
    v
API schemas
    |
    v
Service layer
    |
    v
Create API
    |
    v
Retrieve API
    |
    v
Update API
    |
    v
Authorization
    |
    v
Tenant isolation verification
    |
    v
Focused tests
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
Branch cleanup
```

---

## 33. Acceptance Criteria

DF-54 is complete when:

- [ ] ADR-0016 is committed
- [ ] Possession/parking preference model exists
- [ ] Preference belongs to Customer Requirement
- [ ] Preference is tenant-scoped
- [ ] Tenant-safe foreign key exists
- [ ] One-preference-per-requirement constraint exists
- [ ] Migration succeeds
- [ ] Migration downgrade succeeds
- [ ] Existing Customer Requirements remain valid
- [ ] Possession preference is captured
- [ ] Parking preference is captured
- [ ] Minimum parking spaces can be captured
- [ ] Possession vocabulary is validated
- [ ] Parking vocabulary is validated
- [ ] Parking spaces validation works
- [ ] Preference can be created
- [ ] Preference can be retrieved
- [ ] Preference can be updated
- [ ] Preference lifecycle can be managed
- [ ] requirements.read is enforced for reads
- [ ] requirements.update is enforced for changes
- [ ] Cross-tenant access is denied
- [ ] Invalid requests are rejected
- [ ] Focused DF-54 tests pass
- [ ] Full backend regression passes
- [ ] git diff --check passes
- [ ] No unrelated changes exist
- [ ] One complete PR is created
- [ ] PR is reviewed and merged
- [ ] develop is verified after merge
- [ ] Feature branch is deleted
- [ ] Jira DF-54 is marked Done

---

## 34. Consequences

### Positive consequences

This decision provides:

- structured possession preference
- structured parking preference
- optional minimum parking requirement
- clean separation from Customer Requirement
- tenant-safe ownership
- future availability/matching compatibility
- simple initial implementation
- progressive extensibility
- preservation of existing Customer Requirements

### Trade-offs

The separate entity introduces:

- an additional database table
- additional API endpoints
- additional service logic
- additional tests
- slightly greater implementation complexity than direct columns

This complexity is intentional because possession and parking are business requirements that may participate in future Property Management and Matching capabilities.

---

## 35. Final Decision Summary

DealFlow will represent possession and parking preferences as a separate tenant-scoped child entity:

```text
CustomerRequirement
        |
        +-- CustomerRequirementPossessionParkingPreference
```

Each preference contains:

```text
id
organization_id
customer_requirement_id
possession_preference
parking_preference
parking_spaces_min
is_active
created_at
updated_at
```

Initial possession types:

```text
READY_TO_MOVE
WITHIN_3_MONTHS
WITHIN_6_MONTHS
WITHIN_12_MONTHS
AFTER_12_MONTHS
ANY
```

Initial parking types:

```text
REQUIRED
PREFERRED
NOT_REQUIRED
ANY
```

The preference is tenant-safe, lifecycle-managed, authorization-protected, and intentionally limited to customer requirement capture.

Exact possession dates, property availability, parking inventory, matching, ranking, recommendations, and AI remain future capabilities.

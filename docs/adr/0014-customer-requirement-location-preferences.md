# ADR-0014: Customer Requirement Location Preferences

- **Status:** Accepted
- **Date:** 2026-10-04
- **Decision Owners:** DealFlow Engineering
- **Related Sprint:** DF-S05
- **Related Story:** DF-52 — Capture Location Preferences
- **Related Epic:** DF-E05 — Customer Requirements
- **Depends On:** ADR-0012, ADR-0013

---

## 1. Context

DealFlow Customer Requirements represent the real-estate needs and preferences of a customer.

A customer requirement may include a preferred budget, preferred property type, BHK requirements, possession preferences, parking preferences, and preferred locations.

DF-52 introduces the ability to capture one or more preferred locations for a Customer Requirement.

A customer may prefer multiple locations. For example:

- Tambaram
- Medavakkam
- Pallavaram

Therefore, location preference should not be represented as a single free-form field directly on the `customer_requirements` table.

The location model must also remain compatible with future DealFlow capabilities such as:

- property management
- property matching
- property search
- geographic filtering
- location ranking
- location intelligence
- AI-assisted matching

However, DF-52 must remain intentionally small and must not introduce geographic intelligence prematurely.

---

## 2. Decision

DealFlow will represent Customer Requirement location preferences as a separate tenant-scoped child entity.

The relationship will be:

```text
CustomerRequirement
        |
        | 1:N
        |
        v
CustomerRequirementLocation

A Customer Requirement may therefore have zero, one, or multiple location preferences.
The Customer Requirement remains the owner of the overall business requirement.
Each CustomerRequirementLocation represents one preferred geographic location supplied as part of that requirement.
3. Domain Responsibility
3.1 Customer Requirement
The Customer Requirement represents the customer's overall real-estate need.
Conceptually:
Customer Requirement
├── Budget
├── Location Preferences
├── Property Type
├── BHK Preferences
├── Possession Preferences
├── Parking Preferences
└── Lead / Customer Association

The Customer Requirement owns the business context.
3.2 Customer Requirement Location
A Customer Requirement Location represents one geographic preference associated with a Customer Requirement.
Its responsibility is limited to storing the customer's preferred location.
It does not determine:
- which property is best
- whether a property is available
- whether a property matches the requirement
- location ranking
- distance
- geographic suitability
- property recommendations
Those responsibilities belong to future capabilities.
4. Multiple Location Preferences
A Customer Requirement may contain multiple location preferences.
Example:
Customer Requirement
    |
    +-- Location: Tambaram
    |
    +-- Location: Medavakkam
    |
    +-- Location: Pallavaram

This is preferable to storing multiple locations in a single text field.
For example, the following approach is intentionally rejected:
location = "Tambaram, Medavakkam, Pallavaram"

A structured child entity provides better future compatibility and allows each location to have its own lifecycle and future attributes.
5. Zero Location Preferences
A Customer Requirement does not require a location at creation time.
A requirement may initially exist without any location preference:
Customer Requirement
    Budget: ₹50L - ₹70L
    Locations: none

Location preferences may be added later.
This allows the requirement to evolve progressively as the business user gathers more information from the customer.
6. Persistence Model
The minimum DF-52 persistence model will contain:
Field	Type	Required	Purpose
id	UUID	Yes	Location preference identity
organization_id	UUID	Yes	Tenant ownership
customer_requirement_id	UUID	Yes	Parent requirement
city	String	Yes	Preferred city
locality	String	Yes	Preferred locality or area
is_active	Boolean	Yes	Location preference lifecycle
created_at	DateTime	Yes	Creation timestamp
updated_at	DateTime	Yes	Modification timestamp


The implementation will follow the existing DealFlow model conventions.
7. Tenant Ownership
CustomerRequirementLocation is tenant-scoped.
Every location preference must belong to exactly one organization.
The organization is derived from the authenticated tenant context and must not be trusted from arbitrary client input.
The API must not allow the client to select or override the organization_id ownership boundary.
The relationship between the location preference and Customer Requirement must be tenant-safe.
Conceptually:
(customer_requirement_id, organization_id)
                |
                v
(customer_requirements.id, organization_id)

This ensures that a location preference cannot be attached to a Customer Requirement belonging to another organization.
8. Tenant Isolation
All DF-52 operations must enforce tenant isolation.
For a request operating under organization A:
Organization A
    |
    +-- Requirement A
          |
          +-- Location A

The request must never be able to access:
Organization B
    |
    +-- Requirement B
          |
          +-- Location B

Cross-tenant resources must not be exposed.
The application and database design must work together to maintain this boundary.
9. Location Representation
DF-52 will initially represent a location using:
city
locality

Example:
city = "Chennai"
locality = "Tambaram"

This provides a structured representation without introducing a complex geographic master-data system.
The system will perform basic input normalization such as trimming surrounding whitespace.
The system will not perform geographic interpretation or automatic geographic correction.
10. Geographic Normalization
DF-52 will not introduce geographic normalization.
For example, the system will not automatically transform:
"Tambaram"

into a predefined geographic hierarchy or automatically determine:
Tambaram East
Tambaram West
Chennai Metropolitan Area

Such behavior would require a dedicated geographic domain or external geographic authority.
That capability is outside the scope of DF-52.
11. City and Locality Master Data
DF-52 will not introduce master tables for:
- countries
- states
- cities
- localities
- neighborhoods
- postal codes
City and locality will initially be captured as customer/business-entered structured text.
A future geographic master-data system can be introduced if required.
Such a future system must be introduced through an explicit architectural decision rather than implicitly coupling DF-52 to an external provider.
12. Duplicate Location Preferences
DF-52 will not silently merge duplicate location preferences.
For example:
Tambaram
Tambaram

will not automatically result in a hidden merge.
The system must preserve explicit user actions.
If duplicate prevention becomes necessary in the future, it should be introduced as an explicit business rule with defined normalization and uniqueness semantics.
13. Lifecycle
Location preferences will use an active/inactive lifecycle.
The initial lifecycle representation is:
ACTIVE
INACTIVE

implemented through:
is_active

An inactive location preference is retained rather than physically deleted.
For example:
Requirement
    |
    +-- Tambaram       ACTIVE
    |
    +-- Medavakkam     INACTIVE

This allows future history and audit capabilities to understand that the location was previously associated with the requirement.
DF-52 does not introduce the complete historical versioning system.
14. Update Semantics
Location preference fields may be updated through the API.
The update semantics follow DealFlow's established PATCH conventions:
- omitted field → unchanged
- supplied valid value → replaced
- invalid value → rejected
- is_active → independently editable
Because city and locality define the minimum valid location representation, they are required values for an active location preference.
The API must not allow an active location preference to be persisted without the required location information.
15. Customer Requirement Relationship
Every Customer Requirement Location must belong to one Customer Requirement.
A location preference cannot exist independently without a parent Customer Requirement.
The relationship is:
CustomerRequirement
        |
        +---- CustomerRequirementLocation
        |
        +---- CustomerRequirementLocation
        |
        +---- CustomerRequirementLocation

The parent requirement remains the business owner of the location preferences.
16. Delete Semantics
DF-52 does not introduce destructive deletion as a normal business operation.
Location preferences should be retained and deactivated through is_active.
The database relationship should still define appropriate referential behavior if a Customer Requirement is removed at the persistence level.
The application must prefer lifecycle changes over destructive deletion for normal business operations.
17. API Boundaries
DF-52 will expose location preferences under the Customer Requirement resource hierarchy.
17.1 Create Location
POST /api/v1/customer-requirements/{requirement_id}/locations

Required permission:
requirements.update

The organization must come from the authenticated tenant context.
17.2 List Locations
GET /api/v1/customer-requirements/{requirement_id}/locations

Required permission:
requirements.read

The response must contain only location preferences belonging to the requested Customer Requirement within the current tenant.
17.3 Update Location
PATCH /api/v1/customer-requirements/{requirement_id}/locations/{location_id}

Required permission:
requirements.update

The location must belong to both:
current tenant

and:
requested Customer Requirement

18. Authorization
DF-52 follows the existing DealFlow authorization architecture.
Read operations
requirements.read

Create/update operations
requirements.update

Authorization is evaluated using the authenticated user's tenant membership and role permissions.
The client cannot bypass authorization by supplying an organization identifier.
19. Authentication and Tenant Context
DF-52 APIs require:
1. authenticated user
2. valid tenant context
3. active organization membership
4. required permission
Tenant context is established through the existing DealFlow tenant-context dependency.
The location preference API must not implement an independent tenant-resolution mechanism.
20. Error Semantics
DF-52 will follow existing DealFlow API error conventions.
Expected behavior:
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

Location missing
    → 404

Cross-tenant Location
    → 404

Invalid request payload
    → 422

Business validation failure
    → 400

Cross-tenant requests must not disclose the existence of another tenant's resources.
21. Database Design
A new table will be introduced:
customer_requirement_locations

The table will contain:
id
organization_id
customer_requirement_id
city
locality
is_active
created_at
updated_at

The table will have the necessary foreign-key relationship to:
customer_requirements

with tenant-safe ownership.
The migration must be:
- additive
- reversible
- tenant-safe
- backward-compatible
- non-destructive
Existing Customer Requirement records will remain valid after the migration.
Existing requirements will simply have zero location preferences until locations are added.
22. Migration Strategy
DF-52 will introduce the location table through an Alembic migration.
The migration must:
- create the new table
- create required foreign keys
- create required indexes
- preserve existing Customer Requirement data
- provide a working downgrade
- avoid destructive changes to existing tables
No existing Customer Requirement data should be fabricated or transformed.
23. Indexing
At minimum, the database should support efficient tenant-scoped access to location preferences.
Indexes should be considered for:
organization_id
customer_requirement_id
is_active

Composite indexing should only be introduced where justified by the expected query pattern.
DF-52 will not introduce speculative geographic indexes.
24. Future Property Matching
DF-52 provides structured input for future property matching.
Conceptually:
Customer Requirement
        |
        +-- Location Preferences
        |
        +-- Budget
        |
        +-- Property Preferences
        |
        v
Future Matching Engine
        |
        v
Properties

DF-52 itself does not implement matching.
The location preference should therefore remain independent from Property records.
This prevents premature coupling between the Customer Requirement domain and the Property domain.
25. Future Geographic Capabilities
Future versions may introduce additional geographic information, such as:
state
postal_code
landmark
latitude
longitude
radius
location_type
priority
geographic hierarchy

These capabilities must be introduced progressively.
They must not make the initial DF-52 model unnecessarily complex.
Future additions must preserve backward compatibility with existing location preferences.
26. AI Boundaries
DF-52 does not introduce AI functionality.
Future AI capabilities may assist with:
- interpreting customer location input
- suggesting normalized locations
- recommending additional locations
- matching requirements with properties
However, AI must operate within DealFlow's established:
- identity boundaries
- permission boundaries
- tenant boundaries
- policy boundaries
- audit requirements
AI must not silently change customer requirement location preferences.
Any future automated modification must have explicit product and governance rules.
27. Security Requirements
DF-52 must preserve DealFlow's security principles.
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
The implementation must not introduce a path where a user can associate a location with another organization's Customer Requirement.
28. Performance Considerations
DF-52 is expected to operate on relatively small sets of location preferences per requirement.
The initial implementation should prioritize:
- simple queries
- tenant-scoped access
- deterministic results
- correct ownership
- maintainability
No specialized geographic search engine is required.
No geospatial database extension is required.
No external mapping provider is required.
29. Observability
DF-52 must remain compatible with the existing DealFlow observability architecture.
Future operational telemetry should be able to identify:
- location preference creation
- location preference update
- lifecycle changes
- authorization decisions
- failures
DF-52 does not require a separate observability subsystem.
30. Audit Compatibility
DF-52 should be implemented so that future audit/history capabilities can attribute:
- who created the location preference
- who changed it
- when it changed
- what resource was affected
- which organization owned it
A complete business-history subsystem is not part of DF-52.
This will be addressed through the broader DealFlow history/audit roadmap.
31. Non-Goals
The following are explicitly outside DF-52:
- property matching
- property ranking
- property recommendations
- property availability
- property search
- maps
- GPS
- geocoding
- reverse geocoding
- geographic master data
- distance calculations
- radius search
- geospatial database functionality
- external map APIs
- AI location recommendations
- automatic location inference
- automatic geographic normalization
- complete history/versioning
- lead association changes
- customer association changes
- property association changes
- pricing or affordability calculations
These capabilities must be addressed through future stories or architectural decisions.
32. Testing Requirements
32.1 Domain and Model Tests
Tests must verify:
- model identity
- UUID generation
- required fields
- default lifecycle
- timestamps
- tenant ownership
- Customer Requirement relationship
32.2 Create API Tests
Tests must verify:
- authenticated creation
- permission enforcement
- valid city
- valid locality
- missing requirement
- cross-tenant requirement
- malformed payload
- validation
- server-controlled organization ownership
32.3 List API Tests
Tests must verify:
- authenticated retrieval
- permission enforcement
- correct requirement scoping
- tenant isolation
- empty result
- multiple locations
- active/inactive behavior
32.4 Update API Tests
Tests must verify:
- valid updates
- city update
- locality update
- independent field updates
- lifecycle updates
- invalid payload
- cross-tenant access
- requirement/location mismatch
- authorization
32.5 Regression Tests
All existing DealFlow backend tests must continue to pass.
DF-52 must not regress:
- authentication
- authorization
- tenant isolation
- contacts
- leads
- customer requirements
- budget management
- existing APIs
33. Backward Compatibility
DF-52 must preserve all existing Customer Requirement behavior.
Existing requirements created before DF-52 must remain valid.
A requirement with no location preferences remains valid.
The addition of location preferences must not require a destructive migration or forced population of existing data.
34. Future Compatibility
The design must allow future extensions without breaking existing location preferences.
Potential future additions must be additive wherever possible.
Existing records such as:
city = "Chennai"
locality = "Tambaram"

must remain valid even if future versions introduce:
postal_code
latitude
longitude
priority

The initial implementation must therefore avoid coupling the requirement to a specific future geographic provider or data model.
35. Implementation Order
DF-52 will be implemented in the following order:
ADR-0014
    |
    v
CustomerRequirementLocation model
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
List API
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

The ADR and complete implementation will be delivered through one DF-52 pull request.
36. Acceptance Criteria
DF-52 is complete when all of the following are satisfied:
- [ ] ADR-0014 is committed
- [ ] Customer Requirement Location model exists
- [ ] Location belongs to a Customer Requirement
- [ ] Location is tenant-scoped
- [ ] Tenant-safe foreign-key relationship exists
- [ ] Database migration succeeds
- [ ] Migration downgrade succeeds
- [ ] Customer Requirement can have multiple locations
- [ ] Customer Requirement can exist without locations
- [ ] Location can be created
- [ ] Locations can be listed
- [ ] Location can be updated
- [ ] Location lifecycle can be managed
- [ ] requirements.read is enforced for reads
- [ ] requirements.update is enforced for changes
- [ ] Cross-tenant access is denied
- [ ] Invalid requests are rejected
- [ ] Focused DF-52 tests pass
- [ ] Full backend regression passes
- [ ] git diff --check passes
- [ ] No unrelated changes exist
- [ ] One complete PR is created
- [ ] PR is reviewed and merged
- [ ] develop is verified after merge
- [ ] Feature branch is deleted
- [ ] Jira DF-52 is marked Done
37. Consequences
Positive consequences
This decision provides:
- support for multiple location preferences
- clear separation of requirement and location domains
- tenant-safe ownership
- future compatibility with property matching
- clean API boundaries
- simple initial implementation
- progressive extensibility
- preservation of existing Customer Requirement data
- compatibility with future AI and geographic capabilities
Trade-offs
The separate entity introduces:
- an additional database table
- additional API endpoints
- additional service logic
- additional tests
- slightly more implementation complexity than a single text field
This complexity is intentional because the location preference is a repeatable business concept and is expected to participate in future DealFlow capabilities.
38. Final Decision Summary
DealFlow will represent customer location preferences as a separate tenant-scoped child entity:
CustomerRequirement
        |
        +-- CustomerRequirementLocation
        |
        +-- CustomerRequirementLocation
        |
        +-- CustomerRequirementLocation

The initial location representation will use:
city
locality

with:
id
organization_id
customer_requirement_id
city
locality
is_active
created_at
updated_at
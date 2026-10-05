# ADR-0015: Customer Requirement Property Type, BHK & Property Preferences

- **Status:** Accepted
- **Date:** 2026-10-04
- **Decision Owners:** DealFlow Engineering
- **Related Sprint:** DF-S05
- **Related Story:** DF-53 — Capture Property Type / BHK / Preferences
- **Related Epic:** DF-E05 — Customer Requirements
- **Depends On:** ADR-0012, ADR-0013, ADR-0014

---

## 1. Context

DealFlow Customer Requirements represent the real-estate needs and preferences of a customer.

The Customer Requirement domain already supports:

- budget preferences
- location preferences

DF-53 introduces the ability to capture the type of property the customer is interested in and the preferred BHK range.

A customer may have more than one acceptable property configuration.

For example:

```text
Customer Requirement
│
├── Apartment — 2 BHK
├── Apartment — 3 BHK
└── Villa — 3–4 BHK

Therefore, property type and BHK preferences should not be represented as a collection of unrelated columns directly on customer_requirements.
The design must also remain compatible with future capabilities such as:
- Property Management
- Property Search
- Property Matching
- Property Availability
- Property Ranking
- AI-assisted matching
However, DF-53 must remain intentionally small and must not introduce those capabilities prematurely.
2. Decision
DealFlow will represent property-type and BHK preferences as a separate tenant-scoped child entity.
The relationship will be:
CustomerRequirement
        |
        | 1:N
        |
        v
CustomerRequirementPropertyPreference

A Customer Requirement may therefore contain:
- zero preferences
- one preference
- multiple preferences
The Customer Requirement remains the owner of the overall business requirement.
Each CustomerRequirementPropertyPreference represents one acceptable property configuration.
3. Domain Responsibility
3.1 Customer Requirement
The Customer Requirement represents the customer's overall real-estate need.
Conceptually:
Customer Requirement
├── Budget
├── Location Preferences
├── Property Type / BHK Preferences
├── Possession Preferences
├── Parking Preferences
└── Lead / Customer Association

The Customer Requirement owns the overall business context.
3.2 Customer Requirement Property Preference
A property preference represents one acceptable property configuration.
For example:
Property Type: APARTMENT
BHK Minimum: 2
BHK Maximum: 3

Its responsibility is limited to storing the customer's property-type and BHK preference.
It does not determine:
- which property is best
- whether a property is available
- whether a property matches
- property ranking
- property recommendations
- pricing suitability
Those responsibilities belong to future capabilities.
4. Multiple Property Preferences
A Customer Requirement may contain multiple property preferences.
Example:
Customer Requirement
│
├── Apartment
│   └── 2–3 BHK
│
├── Villa
│   └── 3–4 BHK
│
└── Independent House
    └── 3 BHK

This allows a customer to communicate alternatives without forcing the business user to create multiple Customer Requirements.
A separate preference entity also provides a clean extension point for future property-specific requirements.
5. Zero Property Preferences
A Customer Requirement does not require a property preference at creation time.
For example:
Customer Requirement
│
├── Budget: ₹50L–₹70L
├── Locations: Tambaram
└── Property Preferences: none

Property preferences may be captured later as the business user gathers more information.
This supports progressive completion of a requirement.
6. Property Type Vocabulary
DF-53 will initially use a controlled property-type vocabulary.
The initial values are:
APARTMENT
VILLA
INDEPENDENT_HOUSE
PLOT
COMMERCIAL
OTHER

Definitions
Value	Meaning
APARTMENT	Apartment or flat
VILLA	Villa property
INDEPENDENT_HOUSE	Independent residential house
PLOT	Land/residential plot
COMMERCIAL	Commercial property requirement
OTHER	Requirement not represented by the initial categories


The initial vocabulary is intentionally limited.
DF-53 will not introduce separate categories such as:
- OFFICE
- SHOP
- WAREHOUSE
- FARMHOUSE
- INDUSTRIAL
- HOTEL
unless those categories are explicitly required by a future Property domain decision.
Future property-type expansion must be handled as an explicit domain change rather than silently expanding the vocabulary.
7. BHK Representation
BHK will be represented numerically using:
bhk_min
bhk_max

Both fields are nullable.
Examples:
Exact BHK
2 BHK

bhk_min = 2
bhk_max = 2

Range
2–3 BHK

bhk_min = 2
bhk_max = 3

Minimum preference
3+ BHK

bhk_min = 3
bhk_max = NULL

No BHK requirement
bhk_min = NULL
bhk_max = NULL

This numeric representation is intentionally preferred over storing values such as:
"2 BHK"
"2/3 BHK"
"3+ BHK"

as free-form strings.
Numeric representation provides a stronger foundation for future property matching.
8. BHK Validation
When both values are supplied:
bhk_min <= bhk_max

must hold.
BHK values must be positive whole numbers.
Invalid examples include:
bhk_min = 0
bhk_min = -1
bhk_min = 2.5
bhk_min = 3
bhk_max = 2

The system should reject structurally invalid BHK input.
9. Property Type and BHK Relationship
BHK is not universally applicable to every property type.
For example:
APARTMENT          → BHK applicable
VILLA              → BHK applicable
INDEPENDENT_HOUSE  → BHK applicable
PLOT               → BHK generally not applicable
COMMERCIAL         → BHK generally not applicable

DF-53 will not introduce complex property-type-specific validation rules.
Therefore:
PLOT + bhk_min=NULL + bhk_max=NULL

is valid.
The initial system will store the preference without attempting to infer whether a BHK value is logically appropriate for every property category.
More detailed property-type semantics can be introduced later when the Property domain is implemented.
10. Persistence Model
The minimum DF-53 persistence model will contain:
Field	Type	Required	Purpose
id	UUID	Yes	Preference identity
organization_id	UUID	Yes	Tenant ownership
customer_requirement_id	UUID	Yes	Parent requirement
property_type	String	Yes	Property category
bhk_min	Integer	No	Minimum BHK
bhk_max	Integer	No	Maximum BHK
is_active	Boolean	Yes	Preference lifecycle
created_at	DateTime	Yes	Creation timestamp
updated_at	DateTime	Yes	Modification timestamp


The implementation will follow existing DealFlow model conventions.
11. Tenant Ownership
CustomerRequirementPropertyPreference is tenant-scoped.
Every preference must belong to exactly one organization.
The organization is derived from authenticated tenant context.
The client must not be trusted to determine the authoritative organization ownership.
The relationship must therefore use:
(customer_requirement_id, organization_id)

referencing:
(customer_requirements.id, organization_id)

This prevents a preference from being attached to a Customer Requirement belonging to another organization.
12. Tenant Isolation
All DF-53 operations must enforce tenant isolation.
For organization A:
Organization A
│
└── Requirement A
    │
    └── Property Preference A

The request must never be able to access:
Organization B
│
└── Requirement B
    │
    └── Property Preference B

Cross-tenant resources must not be exposed.
Application-level authorization and database-level tenant-safe relationships must work together.
13. Lifecycle
Property preferences will use an active/inactive lifecycle.
Initial lifecycle:
ACTIVE
INACTIVE

implemented through:
is_active

An inactive preference is retained rather than physically deleted.
Example:
Requirement
│
├── Apartment — 2 BHK     ACTIVE
│
└── Villa — 3 BHK        INACTIVE

This preserves the business record for future history and audit capabilities.
DF-53 does not introduce a complete versioning system.
14. Update Semantics
Updates follow established DealFlow PATCH semantics:
omitted field
    → unchanged

supplied valid value
    → replaced

explicit null
    → cleared when the field is nullable

invalid value
    → rejected

property_type remains required for a persisted preference.
bhk_min and bhk_max may be independently cleared.
is_active is independently editable.
15. Delete Semantics
DF-53 does not introduce destructive deletion as a normal business operation.
The normal business operation for removing a preference is:
is_active = false

The database relationship will retain appropriate referential behavior for persistence-level parent deletion.
Normal application workflows should prefer lifecycle management over destructive deletion.
16. API Boundaries
DF-53 will expose property preferences under the Customer Requirement resource hierarchy.
16.1 Create
POST /api/v1/customer-requirements/{requirement_id}/property-preferences

Permission:
requirements.update

16.2 List
GET /api/v1/customer-requirements/{requirement_id}/property-preferences

Permission:
requirements.read

The response must contain only preferences belonging to the requested Customer Requirement within the current tenant.
16.3 Update
PATCH /api/v1/customer-requirements/{requirement_id}/property-preferences/{preference_id}

Permission:
requirements.update

The preference must belong to:
1. the authenticated tenant
2. the requested Customer Requirement
17. Authorization
DF-53 follows the existing DealFlow authorization architecture.
Read operations:
requirements.read

Create/update operations:
requirements.update

Authorization is evaluated through the authenticated user's tenant membership and role permissions.
The client cannot bypass authorization by supplying an organization identifier.
18. Authentication and Tenant Context
DF-53 APIs require:
1. authenticated user
2. valid tenant context
3. active organization membership
4. required permission
Tenant context must come from the existing DealFlow tenant-context dependency.
DF-53 must not introduce an independent tenant-resolution mechanism.
19. Error Semantics
DF-53 follows existing DealFlow API conventions.
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

Preference missing
    → 404

Cross-tenant Preference
    → 404

Invalid request payload
    → 422

Business validation failure
    → 400

Cross-tenant requests must not disclose another tenant's resources.
20. Database Design
A new table will be introduced:
customer_requirement_property_preferences

It will contain:
id
organization_id
customer_requirement_id
property_type
bhk_min
bhk_max
is_active
created_at
updated_at

The table will have a tenant-safe foreign-key relationship to:
customer_requirements

The migration must be:
- additive
- reversible
- tenant-safe
- backward-compatible
- non-destructive
Existing Customer Requirement records remain valid after migration.
They simply have zero property preferences until preferences are added.
21. Indexing
At minimum, the database should support efficient tenant-scoped access.
Indexes should be considered for:
organization_id
customer_requirement_id
is_active
property_type

No speculative matching indexes will be introduced in DF-53.
22. Future Property Management
DF-53 provides structured requirement input for the future Property Management domain.
Conceptually:
Customer Requirement
        │
        ├── Property Preferences
        ├── Budget
        └── Locations
                │
                ▼
        Future Matching Engine
                │
                ▼
            Properties

DF-53 does not create Property records.
It does not establish a direct requirement-to-property relationship.
That belongs to future Property Management and Matching capabilities.
23. Future Property Matching
The numeric BHK representation is deliberately designed to support future matching.
For example:
Requirement:
APARTMENT
BHK 2–3

could eventually be compared against:
Property:
APARTMENT
3 BHK

But DF-53 itself does not perform that comparison.
No matching score, ranking, recommendation, or automated selection is introduced.
24. Future Property Characteristics
The following are explicitly deferred:
furnished
semi-furnished
unfurnished
floor
floor range
facing
age
balcony
amenities
gated community
parking
possession

Parking and possession will be handled through DF-54.
Other characteristics must be introduced through explicit future stories.
DF-53 must not become an uncontrolled catch-all preference model.
25. AI Boundaries
DF-53 does not introduce AI functionality.
Future AI may assist with:
- interpreting customer property preferences
- suggesting standardized property types
- identifying ambiguous BHK descriptions
- matching requirements against properties
However, AI must operate within DealFlow's:
- identity boundaries
- permission boundaries
- tenant boundaries
- policy boundaries
- audit requirements
AI must not silently modify customer preferences.
26. Security Requirements
DF-53 must preserve DealFlow security principles.
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
There must be no path allowing a user to associate a property preference with another organization's Customer Requirement.
27. Performance Considerations
The number of property preferences per requirement is expected to remain relatively small.
The initial implementation should prioritize:
- simple queries
- tenant-scoped access
- deterministic results
- correct ownership
- maintainability
No specialized search engine is required.
No matching engine is required.
No recommendation engine is required.
28. Observability
DF-53 remains compatible with the existing DealFlow observability architecture.
Future operational telemetry should be able to identify:
- preference creation
- preference update
- lifecycle changes
- authorization decisions
- failures
DF-53 does not introduce a separate observability subsystem.
29. Audit Compatibility
DF-53 should remain compatible with future history/audit capabilities.
Future audit capabilities should be able to attribute:
- who created the preference
- who changed it
- when it changed
- what resource was affected
- which organization owned it
A complete business-history subsystem is outside DF-53.
30. Non-Goals
The following are explicitly outside DF-53:
- property matching
- property ranking
- property recommendations
- property availability
- property search
- property pricing
- affordability calculation
- furnishing preferences
- floor preferences
- facing preferences
- amenity preferences
- parking preferences
- possession preferences
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
These capabilities must be addressed through future stories or architectural decisions.
31. Testing Requirements
31.1 Model Tests
Tests should verify:
- model identity
- UUID generation
- required fields
- property type
- BHK fields
- lifecycle default
- timestamps
- tenant ownership
- Customer Requirement relationship
31.2 Create API Tests
Tests should verify:
- authenticated creation
- permission enforcement
- valid property type
- valid BHK
- BHK range validation
- missing requirement
- cross-tenant requirement
- malformed payload
- server-controlled organization ownership
31.3 List API Tests
Tests should verify:
- authenticated retrieval
- permission enforcement
- correct requirement scoping
- tenant isolation
- empty result
- multiple preferences
- active/inactive behavior
31.4 Update API Tests
Tests should verify:
- property type update
- BHK update
- independent field updates
- lifecycle updates
- explicit null handling
- invalid payload
- invalid BHK range
- cross-tenant access
- requirement/preference mismatch
- authorization
31.5 Regression
All existing DealFlow backend tests must continue to pass.
DF-53 must not regress:
- authentication
- authorization
- tenant isolation
- contacts
- leads
- customer requirements
- budget management
- location preferences
- existing APIs
32. Backward Compatibility
DF-53 must preserve all existing Customer Requirement behavior.
Existing requirements created before DF-53 remain valid.
A requirement without property preferences remains valid.
The migration must not:
- fabricate property preferences
- modify existing requirements
- require property preferences
- perform destructive transformations
33. Future Compatibility
The design must allow future extensions without breaking existing preferences.
Future capabilities may introduce:
- additional property types
- structured property characteristics
- property metadata
- matching rules
- availability information
- pricing constraints
These must be introduced progressively.
Existing records such as:
property_type = APARTMENT
bhk_min = 2
bhk_max = 3

must remain valid as the Property domain evolves.
34. Implementation Order
DF-53 will be implemented in this order:
ADR-0015
    |
    v
CustomerRequirementPropertyPreference model
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

35. Acceptance Criteria
DF-53 is complete when:
- [ ] ADR-0015 is committed
- [ ] Property preference model exists
- [ ] Preference belongs to Customer Requirement
- [ ] Preference is tenant-scoped
- [ ] Tenant-safe foreign key exists
- [ ] Migration succeeds
- [ ] Migration downgrade succeeds
- [ ] Customer Requirement can have multiple preferences
- [ ] Customer Requirement can exist without preferences
- [ ] Property type is captured
- [ ] BHK range is captured
- [ ] BHK validation works
- [ ] Preference can be created
- [ ] Preferences can be listed
- [ ] Preference can be updated
- [ ] Preference lifecycle can be managed
- [ ] requirements.read is enforced for reads
- [ ] requirements.update is enforced for changes
- [ ] Cross-tenant access is denied
- [ ] Invalid requests are rejected
- [ ] Focused DF-53 tests pass
- [ ] Full backend regression passes
- [ ] git diff --check passes
- [ ] No unrelated changes exist
- [ ] One complete PR is created
- [ ] PR is reviewed and merged
- [ ] develop is verified after merge
- [ ] Feature branch is deleted
- [ ] Jira DF-53 is marked Done
36. Consequences
Positive consequences
This decision provides:
- multiple property preferences
- structured property type
- numeric BHK representation
- clean separation of requirement and preference domains
- tenant-safe ownership
- future matching compatibility
- future Property Management compatibility
- simple initial implementation
- progressive extensibility
- preservation of existing Customer Requirements
Trade-offs
The separate entity introduces:
- an additional database table
- additional API endpoints
- additional service logic
- additional tests
- slightly greater implementation complexity than direct columns
This complexity is intentional because property preference is a repeatable business concept expected to participate in future DealFlow capabilities.
37. Final Decision Summary
DealFlow will represent property-type and BHK preferences as a separate tenant-scoped child entity:
CustomerRequirement
        |
        +-- CustomerRequirementPropertyPreference
        |
        +-- CustomerRequirementPropertyPreference
        |
        +-- CustomerRequirementPropertyPreference

Each preference contains:
id
organization_id
customer_requirement_id
property_type
bhk_min
bhk_max
is_active
created_at
updated_at

Initial property types:
APARTMENT
VILLA
INDEPENDENT_HOUSE
PLOT
COMMERCIAL
OTHER

BHK will be represented as a numeric range.
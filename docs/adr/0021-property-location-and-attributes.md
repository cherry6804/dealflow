# ADR-0021: Property Location and Attributes

- **Status:** Accepted
- **Date:** 2026-10-08
- **Decision Owners:** Cherry / DealFlow Engineering
- **Decision Type:** Domain / Data Model
- **Scope:** Property Management
- **Related Sprint:** DF-S06
- **Related Story:** DF-153 — Capture Property Location and Attributes
- **Related Epic:** DF-E06 — Property Management
- **Depends On:** ADR-0019, ADR-0020
- **Supersedes:** None

---

## 1. Context

DealFlow Property Management was introduced through the Property domain
foundation.

The Property domain currently provides:

- stable Property identity;
- tenant ownership;
- creation and update timestamps;
- commercial information introduced by DF-152.

The Property Management roadmap is intentionally decomposed into:

```text
DF-151
Create Property
        |
        v
DF-152
Commercial Fields
        |
        v
DF-153
Location / Attributes
        |
        v
DF-154
Availability / Status
        |
        v
DF-155
Search / Filter
        |
        v
DF-156
Source / Owner

DF-153 introduces the physical location and core descriptive attributes
of a Property.
These values describe the actual property inventory held by the
organization.
They must remain separate from:
- Customer Requirement location preferences;
- Customer Requirement property preferences;
- Property commercial information;
- Property availability/status;
- Property search/filter behavior;
- Property source/owner information;
- Property matching and ranking;
- AI-generated property information.
The design must preserve DealFlow's existing principles:
- tenant isolation;
- server-controlled ownership;
- explicit authorization;
- structured domain data;
- backward-compatible evolution;
- additive migrations;
- predictable validation;
- future property search;
- future property matching;
- future AI operation within the same security boundaries.
2. Decision
DealFlow will extend the existing Property entity with structured
location and core property-attribute fields.
The information will remain directly associated with the Property
record.
No separate generic JSON attribute blob will be introduced.
The DF-153 Property data boundary will be:
Property
|
+-- Identity
|
+-- Tenant Ownership
|
+-- Commercial Information
|
+-- Physical Location
|
+-- Core Property Attributes
|
+-- Availability / Status       <-- DF-154
|
+-- Search / Filtering          <-- DF-155
|
+-- Source / Owner              <-- DF-156

DF-153 is responsible only for physical location and core descriptive
attributes.
3. Domain Responsibility
3.1 Property
Property represents real-estate inventory or an opportunity available to
the organization.
Property is responsible for storing:
- stable property identity;
- tenant ownership;
- commercial information;
- physical location;
- core descriptive property attributes.
Property does not determine:
- customer requirements;
- customer location preferences;
- property matching;
- ranking;
- recommendations;
- availability workflows;
- lead lifecycle;
- deal negotiation;
- booking;
- payment;
- commissions;
- AI-generated decisions.
Those responsibilities belong to their respective domains.
4. Location Model
The physical location of a Property will be represented using structured
fields.
The initial location fields are:
Field	Type	Required	Purpose
address_line_1	String	No	Primary property address
address_line_2	String	No	Additional address information
locality	String	No	Locality / neighborhood
city	String	No	City
state	String	No	State / region
postal_code	String	No	Postal / PIN code
country	String	No	Country


All location fields are nullable at the database level to preserve
backward compatibility with Property records created by DF-151 and
existing records created before DF-153.
The API may progressively collect location information.
DF-153 does not require a Property to have a completely populated
address before the record can exist.
5. Location Semantics
The Property location represents the physical location of the
Property.
It must not be confused with:
Customer Requirement Location
Customer Requirement location represents where a customer wants to find
a property.
Requirement
    |
    +-- preferred location

Property Location
Property location represents where the actual property exists.
Property
    |
    +-- physical location

Future Property Matching may compare these two concepts, but DF-153
does not implement matching behavior.
6. Property Attributes
DF-153 will introduce a deliberately limited set of structured core
property attributes.
The initial attributes are:
Field	Type	Required	Purpose
property_type	String	No	Property category
bhk	Integer	No	Number of bedrooms/BHK
built_up_area	Numeric	No	Built-up area
carpet_area	Numeric	No	Carpet area
floor_number	Integer	No	Property floor
total_floors	Integer	No	Total floors in the building


These fields describe the actual property.
They are not customer preferences.
For example:
Customer Requirement
    desired_bhk = 3

Property
    bhk = 3

The comparison between these values belongs to future Property Matching.
7. Property Type Vocabulary
DF-153 will initially use a controlled property-type vocabulary.
Initial values:
APARTMENT
VILLA
INDEPENDENT_HOUSE
PLOT
COMMERCIAL
OTHER

Definitions:
Value	Meaning
APARTMENT	Apartment / flat
VILLA	Villa property
INDEPENDENT_HOUSE	Independent residential house
PLOT	Land / residential plot
COMMERCIAL	Commercial property
OTHER	Property not represented by the initial categories


The vocabulary is intentionally limited.
DF-153 will not introduce additional specialized categories such as:
OFFICE
SHOP
WAREHOUSE
FARMHOUSE
INDUSTRIAL
HOTEL

unless a future Property domain decision explicitly requires them.
Vocabulary expansion must be an explicit domain change.
8. BHK Semantics
bhk represents the actual number of bedrooms/BHK for the Property.
Examples:
2 BHK
bhk = 2

3 BHK
bhk = 3

The value must be a positive whole number when supplied.
Invalid examples:
bhk = 0
bhk = -1
bhk = 2.5

For Property types where BHK is not applicable, such as a plot, the
value may remain NULL.
DF-153 does not introduce complex property-type-specific validation.
9. Area Semantics
built_up_area represents the property's built-up area.
carpet_area represents the property's carpet area.
Both values are optional.
Area values must be non-negative.
Fractional values are permitted because property area may require
decimal precision.
The system will not assume a universal unit without an explicit API
contract.
The initial API contract will use:
square_feet

as the unit for these fields.
The unit is therefore part of the DF-153 contract and must not be
silently interpreted differently by clients.
Future support for additional units or explicit unit fields must be
introduced through a separate domain decision.
10. Floor Semantics
floor_number represents the floor on which the Property is located.
total_floors represents the total number of floors in the building.
Both values are optional.
When supplied:
floor_number >= 0
total_floors > 0

If both values are supplied:
floor_number <= total_floors

must hold.
The system must not introduce availability or occupancy semantics into
these fields.
For example, floor availability belongs to future Property availability
and inventory capabilities.
11. Commercial Boundary
DF-152 is responsible for commercial information.
DF-153 must not duplicate or replace:
transaction_type
price
currency
rent
security_deposit
maintenance_charge

Those values remain part of the Property commercial model established
by DF-152.
The resulting Property domain is therefore:
Property
|
+-- Commercial
|   +-- transaction_type
|   +-- price
|   +-- currency
|   +-- rent
|   +-- security_deposit
|   +-- maintenance_charge
|
+-- Location
|   +-- address_line_1
|   +-- address_line_2
|   +-- locality
|   +-- city
|   +-- state
|   +-- postal_code
|   +-- country
|
+-- Attributes
    +-- property_type
    +-- bhk
    +-- built_up_area
    +-- carpet_area
    +-- floor_number
    +-- total_floors

12. Availability Boundary
DF-153 must not introduce Property availability or lifecycle status.
The following are explicitly reserved for DF-154:
availability
status
occupancy
listing state
sold state
rented state
leased state

DF-153 only describes the Property.
It does not determine whether the Property is currently available.
13. Search and Filtering Boundary
DF-153 introduces structured fields that can later support searching
and filtering.
However, DF-153 does not implement:
- Property search APIs;
- Property filtering APIs;
- sorting;
- ranking;
- relevance scoring;
- full-text search;
- geographic search;
- radius search;
- search indexes specifically designed for Property discovery.
Those capabilities belong to DF-155.
The fields introduced by DF-153 must therefore be modeled in a way that
allows future indexing without prematurely implementing the search
system.
14. Source and Owner Boundary
DF-153 does not introduce Property source or ownership assignment.
The following are reserved for DF-156:
source
source_reference
property_owner
assigned_user
property_manager

DF-153 must not create speculative relationships to contacts,
customers, leads, or users for these purposes.
15. Tenant Ownership
Property remains a tenant-scoped entity.
The authoritative organization ownership is derived from the verified
tenant context.
The client must never be trusted to establish or change
organization_id.
The API boundary remains:
Authenticated User
        |
        v
Verified Organization Membership
        |
        v
Tenant Context
        |
        v
Property Permission
        |
        v
Property Service
        |
        v
Tenant-scoped Property

Cross-tenant Property access must be denied.
Cross-tenant Property modification must be denied.
A client-provided organization identifier must not override the verified
tenant context.
16. Authorization
DF-153 location and attribute modification requires:
properties.update

Property retrieval continues to use the existing Property read
authorization boundary where applicable.
Authorization must be evaluated before the service performs the
operation.
The frontend is never a security boundary.
17. API Boundary
DF-153 will expose an explicit update operation for Property location and
attributes.
The endpoint will be:
PATCH /api/v1/properties/{property_id}/location-attributes

The request must contain only DF-153 fields.
The endpoint must:
1. authenticate the user;
2. resolve the verified tenant context;
3. verify properties.update;
4. retrieve the Property within that tenant;
5. validate the request;
6. update the Property;
7. persist the change;
8. return the updated Property location/attribute representation.
The client must not provide authoritative organization ownership.
An inaccessible or cross-tenant Property must not be exposed.
18. Persistence Strategy
DF-153 will add the location and attribute fields directly to the
existing properties table.
A separate PropertyLocation table is not required for the initial scope.
A generic JSON attributes column is also rejected.
Structured columns are preferred because they provide:
- predictable validation;
- explicit API contracts;
- database-level type information;
- future indexing capability;
- simpler querying;
- controlled schema evolution;
- better compatibility with future Property Matching.
All new columns will initially be nullable at the database level.
This preserves compatibility with Properties created during DF-151 and
DF-152.
19. Backward Compatibility
Existing Property records must remain valid after the DF-153 migration.
The migration must:
- be additive;
- not delete existing Property records;
- not change Property identifiers;
- not change tenant ownership;
- not fabricate location or attribute values;
- not modify DF-152 commercial values;
- not require a destructive data migration.
Existing Properties will have NULL values for fields that were not
captured before DF-153.
Future workflows may progressively populate those values.
20. Transaction and Consistency
Property location and attribute updates must be persisted atomically.
If validation fails:
No Property changes

If persistence fails:
No partial Property update

The service layer owns the database transaction boundary for the
operation.
21. AI and Automation Boundary
DF-153 does not introduce AI-generated Property attributes.
Future AI capabilities may assist with:
- property data extraction;
- address normalization;
- attribute extraction;
- property classification;
- matching.
However, AI must operate through authorized application/service paths.
AI must respect:
- tenant scope;
- authenticated identity;
- permissions;
- policies;
- audit requirements;
- data-access boundaries.
AI must not receive unrestricted direct database access.
22. Observability
DF-153 operations should follow the existing DealFlow observability
direction.
The system should be capable of identifying:
- validation failures;
- authorization failures;
- tenant isolation failures;
- database failures;
- API failures;
- abnormal error rates;
- latency.
Sensitive property information must not be indiscriminately written into
logs.
23. Testing Requirements
DF-153 implementation must include tests covering at minimum:
Model
- location fields exist;
- attribute fields exist;
- tenant ownership remains required;
- nullable location fields support existing Properties;
- nullable attribute fields support existing Properties;
- numeric fields use the expected types.
API
- successful location update;
- successful attribute update;
- successful combined update;
- response contract;
- persistence after update;
- malformed input;
- invalid BHK;
- invalid area values;
- invalid floor values;
- invalid property type;
- invalid floor relationship.
Authorization
- missing properties.update permission;
- denied update;
- authorized update.
Tenant Security
- missing tenant context;
- cross-tenant Property access;
- cross-tenant Property update;
- client-supplied organization ownership cannot override tenant context.
Regression
All existing DealFlow tests must continue to pass.
DF-153 tests must extend existing guarantees rather than weaken them.
24. Rejected Alternatives
24.1 Generic JSON Property Attributes
Rejected.
A generic JSON blob would weaken:
- validation;
- API contracts;
- database typing;
- querying;
- indexing;
- future matching;
- controlled schema evolution.
Structured attributes are preferred.
24.2 Separate Property Location Entity
Rejected for DF-153.
A separate location entity would introduce additional complexity without
a current business requirement for independently reusable Property
locations.
If future requirements introduce address history, multiple locations,
geographic entities, or reusable location references, that should be
handled through an explicit future domain decision.
24.3 Implement Property Availability
Rejected.
Availability belongs to DF-154.
24.4 Implement Property Search
Rejected.
Search and filtering belong to DF-155.
24.5 Implement Property Source / Owner
Rejected.
Source and ownership assignment belong to DF-156.
24.6 Implement Property Matching
Rejected.
Matching is a future capability that must consume Property and
Customer Requirement data rather than being embedded inside the
Property foundation.
24.7 Add Speculative Future Fields
Rejected.
DF-153 must establish only the location and core attributes required by
the current story.
Future capabilities must introduce their own explicit fields and
migrations.
25. Implementation Order
DF-153 implementation will proceed in the following order:
ADR-0021
Property Location & Attributes
        |
        v
Property Model
        |
        v
Database Migration
        |
        v
Schemas
        |
        v
Service
        |
        v
API
        |
        v
Authorization / Tenant Validation
        |
        v
Tests
        |
        v
Regression
        |
        v
Review / Commit

The broader Property roadmap remains:
DF-151
Property Foundation
        |
        v
DF-152
Commercial Fields
        |
        v
DF-153
Location / Attributes
        |
        v
DF-154
Availability / Status
        |
        v
DF-155
Search / Filter
        |
        v
DF-156
Source / Owner

26. Acceptance Criteria
DF-153 is complete when:
- Property location is represented using structured fields.
- Property core attributes are represented using structured fields.
- Location and attributes remain part of the Property domain.
- Tenant ownership remains server-controlled.
- Cross-tenant access remains denied.
- properties.update protects modification.
- Existing DF-151 and DF-152 Property records remain valid.
- New database fields are additive.
- No existing commercial fields are duplicated or changed.
- Property availability/status remains outside DF-153.
- Property search/filter remains outside DF-153.
- Property source/owner remains outside DF-153.
- Property matching remains outside DF-153.
- AI behavior is not introduced prematurely.
- API validation is explicit.
- Persistence is transactional.
- Tests cover validation, authorization, tenant isolation, persistence,
  and regression.
- Migration is reversible.
- ADR is committed and reviewed.
27. Final Decision Summary
DF-153 will extend the existing tenant-scoped Property entity with
structured physical location and core descriptive attributes.
The initial model will provide:
Location
    address_line_1
    address_line_2
    locality
    city
    state
    postal_code
    country

Attributes
    property_type
    bhk
    built_up_area
    carpet_area
    floor_number
    total_floors

The implementation remains intentionally focused.
Commercial information remains owned by DF-152.
Availability/status remains owned by DF-154.
Search/filter remains owned by DF-155.
Source/owner remains owned by DF-156.
Property Matching, ranking, recommendations, automation, and AI remain
future capabilities.
This preserves a structured, tenant-safe, backward-compatible Property
foundation while allowing DealFlow to evolve the Property domain
incrementally.
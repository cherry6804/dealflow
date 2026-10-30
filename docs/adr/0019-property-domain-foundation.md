# ADR-0019: Property Domain Foundation

- **Status:** Accepted
- **Date:** 2026-10-07
- **Decision Owners:** Cherry / DealFlow Engineering
- **Decision Type:** Domain Architecture
- **Scope:** Property Management
- **Related Sprint:** DF-S05 — Requirements & Properties
- **Related Story:** DF-151 — Create Property Record
- **Related Epic:** DF-E06 — Property Management
- **Depends On:** ADR-0007, ADR-0008, ADR-0012

---

## 1. Context

DealFlow requires a dedicated Property domain to represent real-estate
inventory or opportunities being considered by an organization.

Property is a distinct business concept from:

- Contact;
- Customer Profile;
- Lead;
- Customer Requirement;
- Deal.

A Customer Requirement represents what a customer wants or needs.

A Property represents real-estate inventory or an opportunity that may
eventually be evaluated against one or more Customer Requirements.

The Property domain must therefore have a stable tenant-scoped identity
before additional Property capabilities are introduced.

The Property Management capability is intentionally decomposed into
separate stories:

```text
DF-151
Create Property Record
        |
        v
DF-152
Capture Property Commercial Fields
        |
        v
DF-153
Capture Property Location and Attributes
        |
        v
DF-154
Track Property Availability / Status
        |
        v
DF-155
Search / Filter Properties
        |
        v
DF-156
Associate Property

2. Decision
DealFlow will introduce Property as a separate tenant-scoped business
entity.
The Property record will have a server-generated stable UUID identity and
will belong to exactly one Organization.
The initial DF-151 persistence foundation contains only:
id
organization_id
created_at
updated_at

The organization is authoritative from the verified tenant context.
The client must not be trusted to establish Property ownership.
3. Property Domain Responsibility
Property is responsible for representing a real-estate inventory or
opportunity belonging to an organization.
The Property domain will eventually support capabilities including:
- property commercial information;
- property location;
- property physical attributes;
- property availability;
- property lifecycle/status;
- property search;
- property filtering;
- property associations;
- future property matching.
These capabilities will be introduced through explicit stories.
Property is not responsible for:
- Contact identity;
- Customer Profile identity;
- Lead lifecycle;
- Customer Requirement preferences;
- authentication;
- authorization policy definitions;
- property matching algorithms;
- follow-up scheduling;
- site visits;
- negotiation;
- booking;
- payments;
- commissions;
- AI-generated decisions.
Those responsibilities belong to their respective domains.
4. Property Identity
Every Property must have a stable unique identifier.
The identifier is:
UUID

The identifier is generated and controlled by the server.
Clients must not supply or override the Property primary key during
creation.
No speculative human-readable property code or reference field is
introduced in DF-151.
A human-readable property reference may be introduced later through an
explicit Property story if required by the product.
5. Tenant Ownership
Property is a tenant-owned entity.
Every Property belongs to exactly one Organization.
The ownership boundary is:
Authenticated User
        |
        v
Verified Organization Membership
        |
        v
Tenant Context
        |
        v
Property

The organization must be derived from the verified tenant context.
Client-supplied organization identifiers must not be treated as proof of
ownership or authorization.
All Property queries and mutations must be tenant-scoped.
Cross-tenant Property access must be denied.
6. Persistence Foundation
The initial DF-151 Property table contains:
Field	Type	Required	Purpose
id	UUID	Yes	Stable Property identity
organization_id	UUID	Yes	Tenant ownership
created_at	DateTime	Yes	Creation timestamp
updated_at	DateTime	Yes	Last modification timestamp


The implementation must follow existing DealFlow SQLAlchemy model
conventions.
The Property table must contain a foreign key to the Organization table.
The organization relationship must preserve tenant ownership at the
database level.
7. Deliberately Deferred Fields
DF-151 must not introduce fields belonging to later Property stories.
The following capabilities are explicitly deferred:
DF-152 — Commercial Fields
Examples include:
- sale price;
- rent;
- deposit;
- commercial pricing information;
- other commercial terms.
The exact fields belong to DF-152.
DF-153 — Location and Attributes
Examples include:
- address;
- city;
- state;
- locality;
- property type;
- bedrooms;
- bathrooms;
- area;
- furnishing;
- physical characteristics.
The exact fields belong to DF-153.
DF-154 — Availability / Status
Property availability and lifecycle/status semantics belong to DF-154.
DF-151 must not introduce a substitute status model.
DF-155 — Search / Filter
Property search and filtering behavior belongs to DF-155.
DF-151 must not introduce specialized search infrastructure.
DF-156 — Association
Property associations belong to DF-156.
DF-151 must not create speculative relationships to Leads,
Customer Requirements, Customers, or Deals.
8. API Boundary
DF-151 will introduce a Property creation API under the Property API
resource boundary.
The API must:
- require authentication;
- require verified tenant context;
- require the Property creation permission;
- derive organization ownership from tenant context;
- generate the Property identity server-side;
- persist the Property;
- return the created Property representation.
The client must not be able to override organization ownership.
The exact API implementation must follow existing DealFlow API and
service-layer conventions.
9. Authorization
Property creation requires the dedicated:
properties.create

permission.
Authorization is evaluated through the existing DealFlow authorization
dependency.
A permission granted for one organization must not authorize Property
operations against another organization.
Future Property read/update/delete operations must use explicit
Property permissions rather than relying on the creation permission.
10. Tenant Isolation
Tenant isolation is mandatory.
For example:
Organization A
    |
    +-- Property A

Organization B
    |
    +-- Property B

A user operating within Organization A must not be able to access or
modify Property B.
Tenant isolation must be enforced by:
- authenticated identity;
- verified organization membership;
- tenant context;
- tenant-scoped application queries;
- database ownership relationships.
Cross-tenant access must not disclose whether another organization's
Property exists.
11. Transaction Semantics
Property creation must be atomic.
The operation must either:
create Property
+
persist tenant ownership
+
commit

or produce no persisted Property.
Validation or authorization failure must not create a partial Property
record.
12. Backward Compatibility
The Property foundation is additive.
The migration must:
- create the Property table;
- create required constraints and indexes;
- not modify existing business records;
- not fabricate Property records;
- be reversible;
- preserve all existing DealFlow functionality.
Existing Contact, Customer, Lead, and Requirement records must remain
unchanged.
13. Future Evolution
Later Property stories will extend the Property model through explicit
additive migrations.
The Property foundation must therefore remain compatible with:
Property
    |
    +-- Commercial Information
    |
    +-- Location
    |
    +-- Attributes
    |
    +-- Availability / Status
    |
    +-- Search / Filtering
    |
    +-- Associations
    |
    +-- Future Matching

Future fields must not be introduced prematurely merely to avoid future
migrations.
Controlled additive evolution is preferred.
14. Property Matching Boundary
Property Matching is a future capability.
Matching will eventually evaluate Customer Requirements against
Properties.
Conceptually:
Customer Requirement
        |
        v
Future Matching Engine
        |
        v
Property

DF-151 does not implement:
- matching;
- ranking;
- recommendations;
- shortlist generation;
- AI matching;
- automated property selection.
These capabilities belong to future work.
15. AI Boundary
DF-151 introduces no AI functionality.
Future AI capabilities may assist with Property workflows, including:
- property data extraction;
- normalization;
- search assistance;
- matching;
- recommendations;
- operational assistance.
Any future AI operation must use the same:
- identity;
- tenant;
- permission;
- policy;
- audit;
- data-access
boundaries as human operations.
AI must not receive unrestricted direct database access.
16. Testing Requirements
DF-151 implementation must include tests covering at minimum:
Model
- Property identity;
- UUID generation;
- required organization ownership;
- creation timestamp;
- update timestamp;
- organization relationship.
API
- authenticated Property creation;
- successful creation;
- response contract;
- malformed requests;
- authorization failure;
- tenant context requirement.
Tenant Security
- missing tenant context;
- unauthorized tenant;
- cross-tenant access;
- client-supplied organization ownership;
- organization ownership derived from server-side tenant context.
Database
- migration succeeds;
- migration downgrade succeeds;
- organization foreign key exists;
- existing records remain unaffected.
Regression
All existing DealFlow tests must continue to pass.
17. Rejected Alternatives
17.1 Store Property Fields on Customer Requirement
Rejected.
Customer Requirement represents what a customer wants.
Property represents real-estate inventory or an opportunity.
Combining them would violate the domain boundary.
17.2 Store Property Fields on Lead
Rejected.
Lead represents the active business opportunity and its lifecycle.
Property is a separate inventory/opportunity entity.
17.3 Create All Property Fields in DF-151
Rejected.
Commercial fields, location, attributes, availability/status, search, and
associations have separate stories.
Prematurely implementing them would weaken the intended incremental
architecture.
17.4 Use a Generic JSON Property Blob
Rejected as the primary Property representation.
Structured Property capabilities should be introduced through explicit
typed fields and migrations.
A generic blob would weaken validation, querying, indexing, API
contracts, and future matching.
17.5 Create Speculative Property Relationships
Rejected.
DF-151 must not introduce relationships to Leads, Requirements,
Customers, or Deals until the corresponding business capability is
defined.
18. Final Decision Summary
DealFlow will introduce a dedicated tenant-scoped Property entity.
The DF-151 foundation contains:
Property
├── id
├── organization_id
├── created_at
└── updated_at

Property identity is server-controlled.
Organization ownership is derived from verified tenant context.
Property creation requires:
properties.create

permission.
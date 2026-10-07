# ADR-0020: Property Commercial Fields

- **Status:** Accepted
- **Date:** 2026-10-07
- **Decision Owners:** Cherry / DealFlow Engineering
- **Decision Type:** Domain Evolution
- **Scope:** Property Management
- **Related Sprint:** DF-S06 — Property Management
- **Related Story:** DF-152 — Capture property commercial fields
- **Related Epic:** DF-E06 — Property Management
- **Depends On:** ADR-0019 — Property Domain Foundation

---

## 1. Context

DealFlow has established the Property domain foundation through DF-151.

The Property entity is a tenant-owned real-estate inventory/opportunity record.

The Property Management implementation sequence is:

```text
DF-151
Create Property
        |
        v
DF-152
Commercial fields
        |
        v
DF-153
Location / attributes
        |
        v
DF-154
Availability / status
        |
        v
DF-155
Search / filter
        |
        v
DF-156
Source / owner

DF-152 introduces the minimum commercial information required to describe
the financial terms associated with a Property.
The implementation must remain intentionally small and must not introduce
location, physical attributes, availability, search, ownership, matching,
or AI capabilities prematurely.
2. Decision
DealFlow will extend the existing properties entity with structured
commercial fields.
The initial DF-152 commercial model will contain:
Field	Type	Required	Purpose
transaction_type	String	Yes	Commercial transaction model
price	Numeric	No	Primary property price/value
currency	String	Yes	Currency used for monetary values
rent	Numeric	No	Recurring rental amount when applicable
security_deposit	Numeric	No	Security deposit when applicable
maintenance_charge	Numeric	No	Recurring/property maintenance charge when applicable


The fields are stored directly on properties because they describe the
commercial terms of the Property itself.
3. Transaction Type
DF-152 will use a controlled transaction-type vocabulary.
Initial values:
SALE
RENT
LEASE

The vocabulary is intentionally small.
DF-152 will not introduce additional transaction types unless a future
domain decision explicitly requires them.
4. Monetary Representation
Monetary fields will use a fixed-precision database numeric type rather
than floating-point storage.
The following fields are monetary:
price
rent
security_deposit
maintenance_charge

The initial precision will support normal real-estate transaction values
without relying on floating-point arithmetic.
Currency will be stored separately from the amount.
The initial API representation will use decimal-compatible values.
5. Currency
currency is required.
The initial implementation will use a three-character currency code.
For example:
INR
USD
EUR

DF-152 does not introduce a complete currency-management subsystem.
Future currency validation or organization-specific currency configuration
may be introduced through a dedicated capability.
6. Field Applicability
Commercial fields are conditionally applicable depending on the
transaction type.
Examples:
SALE
transaction_type = SALE
price = 10000000
currency = INR

RENT
transaction_type = RENT
rent = 50000
security_deposit = 300000
currency = INR

LEASE
transaction_type = LEASE
price = 5000000
security_deposit = 500000
currency = INR

DF-152 will not introduce complex transaction-specific validation rules
beyond basic structural validation.
The system will preserve structured commercial information without trying
to infer the complete business meaning of every transaction model.
7. Ownership and Tenant Isolation
Property ownership remains controlled by the verified tenant context.
The client must never be able to change:
organization_id

through the commercial-fields API.
Commercial updates must operate only against a Property belonging to the
verified organization.
Cross-tenant Property access must be rejected.
8. Authorization
DF-152 will follow the existing DealFlow authorization architecture.
Commercial-field creation/update operations require:
properties.update

Property retrieval continues to use the appropriate Property read
permission.
The API must not trust client-supplied roles, organization identifiers, or
authorization claims.
9. API Boundary
DF-152 will extend the Property API without creating a separate commercial
entity.
The commercial update endpoint will be:
PATCH
/api/v1/properties/{property_id}/commercial

The endpoint will accept only DF-152 commercial fields.
Example:
{
  "transaction_type": "SALE",
  "price": "10000000.00",
  "currency": "INR",
  "rent": null,
  "security_deposit": null,
  "maintenance_charge": null
}

The response will return the complete Property representation currently
defined by the Property API, including the commercial fields.
10. Backward Compatibility
Existing Property records created by DF-151 must remain valid.
Therefore:
- commercial amount fields are nullable;
- existing Property records are not rewritten;
- the migration must not fabricate commercial values;
- no destructive migration is permitted;
- existing Property identifiers remain unchanged;
- existing tenant ownership remains unchanged.
The required transaction_type and currency fields will therefore be
introduced as nullable database columns initially so existing DF-151
records can continue to exist.
New commercial updates will require valid values for them.
11. Migration
The migration must be additive and reversible.
The migration must:
- add DF-152 commercial columns to properties;
- preserve existing Property records;
- not fabricate commercial values;
- not change organization_id;
- not change Property identifiers;
- support downgrade.
No unrelated schema changes are permitted.
12. Service Boundary
The Property service layer owns commercial-field updates.
The service must:
1. receive verified tenant context;
2. receive the Property identifier;
3. retrieve the Property using tenant-scoped lookup;
4. reject missing/cross-tenant Properties;
5. validate the commercial payload;
6. update only DF-152 fields;
7. flush the transaction;
8. return the updated Property.
The API layer must not directly manipulate commercial persistence logic.
13. Validation
The API must reject structurally invalid commercial data.
At minimum:
- transaction type must be one of the supported values;
- currency must contain a valid three-character code;
- monetary values must not be negative;
- malformed decimal values must be rejected;
- unknown commercial fields must not silently become persisted data.
DF-152 will not introduce complex affordability or pricing calculations.
14. Non-Goals
DF-152 does not introduce:
- property location;
- city;
- locality;
- latitude/longitude;
- property area;
- BHK;
- floor;
- facing;
- furnishing;
- amenities;
- parking;
- possession;
- property availability;
- property lifecycle status;
- property search;
- property filtering;
- property source;
- property owner assignment;
- property matching;
- property ranking;
- recommendations;
- AI pricing;
- affordability calculation;
- external property APIs.
Those capabilities belong to later stories or explicit future decisions.
15. Security
DF-152 must preserve DealFlow security principles:
- authentication;
- tenant isolation;
- authorization;
- server-controlled organization ownership;
- tenant-scoped resource lookup;
- controlled updates;
- audit compatibility.
Commercial information must not bypass the existing Property security
boundary.
16. Testing Requirements
Tests must cover:
Model
- commercial columns exist;
- nullable commercial amounts;
- transaction type storage;
- currency storage;
- decimal precision;
- timestamps remain functional.
API
- successful commercial update;
- complete commercial response;
- valid transaction types;
- valid currency;
- valid monetary values;
- negative monetary values rejected;
- malformed monetary values rejected;
- invalid transaction type rejected;
- unknown fields rejected.
Tenant Security
- missing tenant context;
- cross-tenant Property update;
- client-supplied organization ownership cannot override tenant context.
Authorization
- properties.update required;
- unauthorized update rejected.
Persistence
- commercial values persist;
- existing Property records remain valid;
- null optional commercial values remain supported.
Regression
All existing DealFlow backend tests must continue to pass.
17. Future Compatibility
The commercial model must remain extensible.
Future Property capabilities may introduce:
- pricing history;
- price-per-area calculations;
- lease-specific commercial terms;
- tax information;
- brokerage;
- maintenance schedules;
- project/unit pricing;
- configurable commercial fields.
These must be introduced through explicit future domain decisions.
DF-152 must not become a generic JSON-based commercial metadata store.
18. Rejected Alternatives
18.1 Generic JSON Commercial Metadata
Rejected.
A JSON blob would weaken validation, querying, indexing, API contracts,
and future reporting.
Structured commercial fields are preferred.
18.2 Separate PropertyCommercial Entity
Rejected for DF-152.
The initial commercial model is small enough to belong directly to the
Property entity.
A separate entity can be introduced later if commercial complexity
requires independent lifecycle or history.
18.3 Store Money as Floating Point
Rejected.
Floating-point storage is unsuitable for reliable monetary persistence.
Fixed-precision numeric storage is preferred.
18.4 Implement All Property Fields in DF-152
Rejected.
Location, physical attributes, availability, search, and source/owner are
explicitly separated into later stories.
19. Implementation Order
ADR-0020
    |
    v
Property model
    |
    v
Alembic migration
    |
    v
API schemas
    |
    v
Property service
    |
    v
Commercial update API
    |
    v
Authorization
    |
    v
Tenant isolation tests
    |
    v
Focused DF-152 tests
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
PR

20. Acceptance Criteria
DF-152 is complete when:
- [ ] ADR-0020 is committed.
- [ ] Property supports structured commercial fields.
- [ ] Transaction type is captured.
- [ ] Price is supported.
- [ ] Currency is captured.
- [ ] Rent is supported.
- [ ] Security deposit is supported.
- [ ] Maintenance charge is supported.
- [ ] Monetary values use fixed precision.
- [ ] Negative monetary values are rejected.
- [ ] Invalid transaction types are rejected.
- [ ] Invalid currency values are rejected.
- [ ] Existing DF-151 Property records remain valid.
- [ ] Migration succeeds.
- [ ] Migration downgrade succeeds.
- [ ] Commercial update API exists.
- [ ] properties.update is enforced.
- [ ] Tenant isolation is enforced.
- [ ] Client cannot change organization ownership.
- [ ] Commercial values persist correctly.
- [ ] Focused DF-152 tests pass.
- [ ] Full backend regression passes.
- [ ] git diff --check passes.
- [ ] No unrelated changes exist.
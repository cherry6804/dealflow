\# ADR-0023: Property Search and Filtering



\- \*\*Status:\*\* Accepted

\- \*\*Date:\*\* 2026-10-08

\- \*\*Decision Owners:\*\* Cherry / DealFlow Engineering

\- \*\*Scope:\*\* Property Management

\- \*\*Related Epic:\*\* DF-E06 — Property Management

\- \*\*Related Story:\*\* DF-155 — Search/filter properties

\- \*\*Supersedes:\*\* None

\- \*\*Depends On:\*\* ADR-0019, ADR-0020, ADR-0021, ADR-0022



\---



\## 1. Context



DealFlow Property Management currently provides a tenant-scoped Property domain with the following capabilities:



\- DF-151 — Property domain foundation

\- DF-152 — Property commercial fields

\- DF-153 — Property location and core attributes

\- DF-154 — Property availability and status



The Property entity now contains structured information that real-estate users need to locate and evaluate properties, including:



\### Identity and tenancy



\- Property ID

\- Organization ID

\- Created timestamp

\- Updated timestamp



\### Commercial information



\- Transaction type

\- Price

\- Currency

\- Rent

\- Security deposit

\- Maintenance charge



\### Location



\- Address line 1

\- Address line 2

\- Locality

\- City

\- State

\- Postal code



\### Property attributes



\- Property type

\- BHK

\- Built-up area

\- Carpet area

\- Floor number

\- Total floors



\### Availability



\- Property status



As the number of Property records increases, retrieving properties individually is insufficient.



Users need to search and narrow the tenant's Property inventory using practical real-estate criteria.



DF-155 introduces a controlled Property search and filtering capability without changing the existing Property creation or update contracts.



\---



\# 2. Decision



DealFlow will implement Property search and filtering as a \*\*tenant-scoped, database-backed query capability using PostgreSQL and SQLAlchemy\*\*.



The initial implementation will use the existing Property database as the authoritative search source.



No separate search engine will be introduced for DF-155.



The search capability will expose a read-only API that supports:



1\. Text search

2\. Structured filters

3\. Range filters

4\. Pagination

5\. Deterministic ordering

6\. Tenant isolation

7\. Permission enforcement



The implementation must remain additive and must not change the behavior of DF-151, DF-152, DF-153, or DF-154 APIs.



\---



\# 3. Goals



DF-155 has the following goals:



\- Allow users to search Property records efficiently.

\- Allow users to filter properties using structured business fields.

\- Keep search tenant-isolated.

\- Use verified tenant context as the source of organization ownership.

\- Provide predictable pagination.

\- Provide deterministic result ordering.

\- Prevent unbounded result retrieval.

\- Keep the API simple enough for the current product stage.

\- Reuse the existing Property domain model.

\- Avoid introducing unnecessary infrastructure.

\- Provide a foundation that can evolve into more advanced search capabilities later.



\---



\# 4. Non-Goals



The following capabilities are explicitly outside DF-155:



\- Geospatial search

\- Radius/distance search

\- Map-based search

\- Geographic coordinates

\- Polygon/boundary search

\- AI-powered property matching

\- Recommendation/ranking engines

\- Semantic search

\- Elasticsearch

\- OpenSearch

\- Saved searches

\- Search history

\- Search analytics

\- Property owner filtering

\- Property source filtering

\- External listing synchronization

\- Booking workflows

\- Reservation workflows

\- Occupancy management

\- Listing publication

\- Lead-property matching

\- Customer-property matching

\- Property status transition workflows

\- Property status history

\- Advanced reporting

\- Export functionality

\- Bulk property operations



These capabilities may be considered in future stories.



\---



\# 5. API Design



DF-155 will expose a read-only Property search endpoint.



\## Endpoint



```text

GET /api/v1/properties/search



The endpoint will use the verified tenant context.

The organization ID will not be accepted as a trusted client-supplied search parameter.

6\. Authorization

Property search requires the Property read permission:

properties.read



The permission must be enforced through the existing authorization mechanism.

The endpoint must not bypass the standard tenant and permission dependency chain.

A caller without:

properties.read



must not receive Property search results.

7\. Tenant Isolation

Tenant isolation is mandatory.

The organization used for the search query must come exclusively from the verified tenant context.

Conceptually:

verified tenant context

&#x20;       ↓

organization\_id

&#x20;       ↓

Property query

&#x20;       ↓

results



The API must not trust a client-provided:

organization\_id



for determining the tenant scope.

Every Property query must include tenant ownership as part of the query condition.

Conceptually:

Property.organization\_id == tenant\_context.organization\_id



before applying user-supplied filters.

Cross-tenant Property records must never be returned.

8\. Search Query

The endpoint will support an optional text query:

q



The purpose of q is to provide a simple user-facing search across useful textual Property information.

The initial searchable fields are:

\- address\_line\_1

\- address\_line\_2

\- locality

\- city

\- state

\- postal\_code

The search must not be interpreted as AI or semantic search.

It is a database-backed textual search capability.

9\. Text Search Semantics

The initial implementation will use case-insensitive partial matching appropriate for PostgreSQL.

Conceptually:

q

&#x20;↓

text matching against supported Property location fields

&#x20;↓

matching Property records



The implementation must avoid unrestricted searching across arbitrary database columns.

Only explicitly approved searchable fields may participate in the q query.

The initial implementation does not require fuzzy matching, typo correction, stemming, semantic similarity, or ranking.

10\. Structured Filters

DF-155 will support filtering using existing structured Property fields.

The following filters are approved.

10.1 Transaction Type

Parameter:

transaction\_type



Supported values:

SALE

RENT

LEASE



The values must align with the existing DF-152 transaction type contract.

10.2 Status

Parameter:

status



Supported values:

AVAILABLE

RESERVED

SOLD

RENTED

LEASED

UNAVAILABLE



The values must align with the existing DF-154 Property status contract.

DF-155 must not introduce a second status definition.

10.3 Property Type

Parameter:

property\_type



Supported values:

APARTMENT

VILLA

INDEPENDENT\_HOUSE

PLOT

COMMERCIAL

OTHER



The values must align with the existing DF-153 Property type contract.

10.4 BHK

Parameter:

bhk



The filter represents an exact BHK value.

Example:

?bhk=2



Only properties with:

bhk = 2



are returned.

10.5 City

Parameter:

city



The filter performs case-insensitive matching against the structured city field.

10.6 State

Parameter:

state



The filter performs case-insensitive matching against the structured state field.

10.7 Locality

Parameter:

locality



The filter performs case-insensitive partial matching against the structured locality field.

10.8 Postal Code

Parameter:

postal\_code



The filter performs matching against the structured postal\_code field.

11\. Commercial Range Filters

DF-155 will support range filtering for commercial values.

11.1 Price

Parameters:

min\_price

max\_price



Semantics:

price >= min\_price

price <= max\_price



If both are provided:

min\_price <= price <= max\_price



11.2 Rent

Parameters:

min\_rent

max\_rent



Semantics:

rent >= min\_rent

rent <= max\_rent



12\. Area Range Filters

DF-155 will support range filtering for Property areas.

The existing area unit defined by DF-153 remains authoritative.

12.1 Built-up Area

Parameters:

min\_built\_up\_area

max\_built\_up\_area



Semantics:

built\_up\_area >= min\_built\_up\_area

built\_up\_area <= max\_built\_up\_area



12.2 Carpet Area

Parameters:

min\_carpet\_area

max\_carpet\_area



Semantics:

carpet\_area >= min\_carpet\_area

carpet\_area <= max\_carpet\_area



13\. Floor Filters

DF-155 will support exact filtering for:

floor\_number



and:

total\_floors



Examples:

?floor\_number=5



or:

?total\_floors=10



No floor-range or floor-category abstraction is introduced by DF-155.

14\. Combining Filters

Multiple filters may be supplied simultaneously.

Filters use logical AND semantics.

Example:

GET /api/v1/properties/search?city=Chennai\&property\_type=APARTMENT\&bhk=2\&status=AVAILABLE



Conceptually:

tenant

AND city = Chennai

AND property\_type = APARTMENT

AND bhk = 2

AND status = AVAILABLE



Only records satisfying all supplied filters are returned.

15\. Text Search and Structured Filters

The text query may be combined with structured filters.

Example:

GET /api/v1/properties/search?q=Tambaram\&status=AVAILABLE\&property\_type=APARTMENT



The resulting query represents:

tenant

AND text\_match(q)

AND status = AVAILABLE

AND property\_type = APARTMENT



16\. Null Handling

Existing Property fields are nullable because previous stories intentionally preserved backward compatibility.

DF-155 must respect this.

A filter against a field must not treat:

NULL



as a valid value.

For example:

?bhk=2



must not return a Property whose:

bhk IS NULL



Similarly:

?min\_price=5000000



must not return a Property whose price is NULL.

17\. Range Validation

Range filters must be validated.

If both minimum and maximum values are provided:

minimum <= maximum



must hold.

Invalid ranges must be rejected as a client validation error.

Examples:

min\_price > max\_price



or:

min\_rent > max\_rent



must not execute a database query.

The same rule applies to area ranges.

18\. Pagination

Property search must be paginated.

The API will support:

page

page\_size



The implementation must enforce safe limits.

Recommended initial contract:

page >= 1

page\_size >= 1

page\_size <= 100



Default:

page = 1

page\_size = 20



The exact values must be implemented consistently in the API schema.

Unbounded Property result retrieval is not permitted.

19\. Pagination Response

The response should provide enough information for the client to navigate the result set.

The response will contain:

\- matching Property records

\- current page

\- page size

\- total matching records

\- total pages

Conceptual response:

{

&#x20; "items": \[],

&#x20; "page": 1,

&#x20; "page\_size": 20,

&#x20; "total": 0,

&#x20; "total\_pages": 0

}



The exact schema will be defined in the implementation.

20\. Ordering

Search results must have deterministic ordering.

The initial default ordering will be:

created\_at DESC



with:

id DESC



as a deterministic tie-breaker.

Conceptually:

ORDER BY created\_at DESC, id DESC



Client-controlled arbitrary ordering is not introduced by DF-155.

This prevents unpredictable pagination caused by unstable ordering.

21\. Database Query Strategy

DF-155 will use SQLAlchemy to construct the Property query.

The service layer will:

1\. Start with the tenant-scoped Property query.

2\. Apply the text query if supplied.

3\. Apply each supplied structured filter.

4\. Apply range conditions.

5\. Apply deterministic ordering.

6\. Calculate pagination metadata.

7\. Apply offset/limit.

8\. Return the paginated result.

The service layer owns query construction.

The API layer owns:

\- request parsing

\- dependency injection

\- authorization dependency

\- tenant context

\- response serialization

The API must not contain complex query-building logic.

22\. Tenant-Scoped Query Foundation

The query must begin from the verified tenant scope.

Conceptually:

select(Property).where(    Property.organization\_id == organization\_id)





Additional conditions are then added.

This establishes tenant isolation as a mandatory query foundation rather than an optional filter.

23\. Performance Strategy

DF-155 will initially rely on PostgreSQL and existing relational indexes.

Indexes should be introduced only where justified by actual query patterns.

The implementation must not create speculative indexes for every filter.

Potentially indexable fields include:

\- organization\_id

\- status

\- transaction\_type

\- property\_type

\- city

\- state

\- locality

\- postal\_code

However, the final migration must include only indexes justified by the DF-155 query contract and existing schema behavior.

The implementation must not modify unrelated indexes or unrelated tables.

24\. Text Search Performance

The initial implementation does not introduce PostgreSQL full-text search, trigram indexes, Elasticsearch, or OpenSearch.

Simple case-insensitive matching is sufficient for the initial DF-155 capability.

If production usage demonstrates that text search becomes a performance bottleneck, a future ADR may evaluate:

\- PostgreSQL trigram search

\- PostgreSQL full-text search

\- dedicated search infrastructure

Such optimization is outside the current story.

25\. Currency Consideration

Commercial values currently contain:

currency



DF-155 will not perform currency conversion.

Price and rent range filtering operate against the stored numeric values.

Therefore a client should use range filters consistently with the currency represented by the Property records.

Currency normalization/conversion is outside DF-155.

26\. Security

DF-155 must preserve the existing DealFlow security architecture.

Required controls:

\- authenticated request

\- verified tenant context

\- properties.read permission

\- tenant-scoped query

\- no client-controlled organization ownership

\- bounded pagination

\- validated filter values

\- validated numeric ranges

\- no dynamic SQL constructed from raw client strings

\- no arbitrary column selection

\- no arbitrary ordering expression

All query construction must use SQLAlchemy parameterization.

27\. Backward Compatibility

DF-155 must not modify the behavior of:

POST /api/v1/properties



or existing DF-152/DF-153/DF-154 update endpoints.

Existing Property records must remain valid.

Existing NULL values must remain supported.

No existing Property records may be rewritten solely to support search.

No destructive migration is permitted.

No existing API contract should be changed merely to support DF-155.

28\. Existing API Preservation

The following existing capabilities remain unchanged:

DF-151

Property creation and tenant ownership.

DF-152

Commercial field updates.

DF-153

Location and attribute updates.

DF-154

Availability/status updates.

DF-155 only introduces read/search capability.

29\. Service Layer Responsibility

The Property service layer owns:

\- tenant-scoped query construction

\- filter application

\- range validation

\- pagination

\- ordering

\- result retrieval

\- total-count calculation

The service must not trust organization IDs supplied by the caller.

The service receives the verified organization ID from the API's tenant context.

30\. API Layer Responsibility

The API layer owns:

\- HTTP endpoint definition

\- query parameter parsing

\- request validation

\- authorization dependency

\- tenant dependency

\- service invocation

\- HTTP response mapping

The API layer must not duplicate business filtering logic.

31\. Schema Responsibility

Search request/query parameters must be represented using validated API schemas or equivalent FastAPI/Pydantic validation.

Schemas must validate:

\- enum values

\- positive pagination values

\- maximum page size

\- nonnegative numeric ranges where applicable

\- minimum/maximum relationships

The schema must reject malformed requests before unnecessary database work.

32\. Error Handling

DF-155 should use standard API validation behavior for invalid query parameters.

Examples include:

\- invalid transaction type

\- invalid status

\- invalid property type

\- invalid BHK

\- invalid pagination

\- invalid range

\- invalid numeric values

The search endpoint should not expose database implementation errors to the client.

33\. Empty Results

A valid search that matches no Properties is not an error.

The endpoint must return a successful response containing:

items = \[]



and appropriate pagination metadata.

It must not return HTTP 404 merely because no Property matches.

34\. Unknown Property

DF-155 is a collection search capability.

There is no requirement to return individual-property 404 behavior from this endpoint.

Existing individual Property endpoints retain their existing behavior.

35\. Testing Strategy

DF-155 must include automated tests covering at least:

Search

\- search by supported location text

\- case-insensitive search

\- no-match search

\- search combined with filters

Filters

\- transaction type

\- status

\- property type

\- BHK

\- city

\- state

\- locality

\- postal code

\- floor number

\- total floors

Range filters

\- minimum price

\- maximum price

\- price range

\- minimum rent

\- maximum rent

\- rent range

\- built-up area range

\- carpet area range

Pagination

\- default pagination

\- explicit page

\- explicit page size

\- maximum page size

\- page beyond available results

\- deterministic ordering

Validation

\- invalid enum

\- invalid numeric value

\- invalid page

\- invalid page size

\- invalid range

Authorization

\- missing authentication

\- missing properties.read

\- unauthorized request

Tenant isolation

\- tenant A cannot retrieve tenant B properties

\- search remains tenant-scoped when filters are applied

Null handling

\- NULL values are not incorrectly matched by filters

Regression

\- existing DF-151 tests continue to pass

\- existing DF-152 tests continue to pass

\- existing DF-153 tests continue to pass

\- existing DF-154 tests continue to pass

36\. Migration Strategy

A migration is required only if the final DF-155 implementation introduces database indexes.

Any migration must be:

\- additive

\- reversible

\- tenant-safe

\- limited to DF-155

\- free of unrelated schema changes

The migration must not modify existing unrelated indexes or tables.

If no additional index is justified by the implementation, no migration should be introduced solely for DF-155.

37\. Observability

DF-155 should use existing application observability mechanisms.

The implementation should make it possible to identify:

\- search endpoint failures

\- validation failures

\- authorization failures

\- database/query failures

Detailed query values must not be logged in a way that exposes sensitive customer information.

Search analytics are outside DF-155.

38\. Rejected Alternatives

38.1 Elasticsearch/OpenSearch

Rejected for DF-155 because the current Property inventory does not justify introducing dedicated search infrastructure.

It adds:

\- infrastructure complexity

\- operational cost

\- synchronization concerns

\- additional failure modes

\- data consistency concerns

It may be reconsidered when actual scale requires it.

38.2 JSON Search Criteria

Rejected.

Searchable Property attributes already have structured database columns.

Using a JSON search object would weaken:

\- validation

\- query clarity

\- indexing

\- API documentation

\- database constraints

38.3 Client-Supplied Organization ID

Rejected.

Tenant ownership must come from verified tenant context.

Allowing:

organization\_id



to determine search scope would create a tenant-isolation risk.

38.4 Arbitrary Dynamic Filters

Rejected.

Clients must only filter against explicitly supported Property fields.

The API must not allow arbitrary database column names or SQL expressions.

38.5 AI/semantic search

Rejected for DF-155.

AI matching is not required for the initial Property search capability.

It can be introduced later as a separate capability with its own security, relevance, observability, and cost considerations.

38.6 Geospatial Search

Rejected.

The current Property domain does not yet contain geographic coordinates or a geospatial search contract.

Geospatial capabilities require separate architectural decisions.

38.7 Saved Search

Rejected.

Saved searches introduce persistence, ownership, lifecycle, notification, and authorization concerns that are outside this story.

39\. Future Evolution

DF-155 establishes the initial database-backed Property search foundation.

Future capabilities may extend it with:

\- advanced sorting

\- geospatial search

\- map search

\- saved searches

\- search history

\- search analytics

\- optimized PostgreSQL text search

\- dedicated search infrastructure

\- relevance ranking

\- AI-assisted matching

\- lead-property matching

\- customer-property matching

Such capabilities must be introduced through separate stories and, where architecturally significant, separate ADRs.

40\. Acceptance Criteria

DF-155 is considered complete when:

1\. A tenant-authorized user can search Properties.

2\. Search is restricted to the verified tenant.

3\. properties.read is required.

4\. Supported text fields can be searched.

5\. Supported structured filters work independently.

6\. Multiple filters combine using AND semantics.

7\. Commercial range filters work correctly.

8\. Area range filters work correctly.

9\. Invalid ranges are rejected.

10\. Pagination is implemented.

11\. Page size is bounded.

12\. Result ordering is deterministic.

13\. Empty result sets return successfully.

14\. NULL Property fields are handled correctly.

15\. Existing Property APIs remain unchanged.

16\. DF-151 through DF-154 tests continue to pass.

17\. DF-155 has comprehensive automated test coverage.

18\. No cross-tenant Property data can be returned.

19\. No unnecessary search infrastructure is introduced.

20\. Any required migration contains only DF-155 changes.

21\. git diff --check passes.

22\. Full backend regression tests pass.

41\. Security Acceptance Criteria

The implementation must additionally demonstrate:

\- tenant context cannot be overridden by request parameters

\- unauthorized users cannot search Properties

\- cross-tenant records are never returned

\- arbitrary SQL cannot be injected through search parameters

\- arbitrary database columns cannot be selected as filters

\- arbitrary ordering expressions cannot be supplied

\- pagination cannot be used to request unbounded results

42\. Compatibility Acceptance Criteria

The implementation must preserve:

\- existing Property creation

\- existing commercial updates

\- existing location/attribute updates

\- existing status updates

\- existing Property database records

\- existing tenant isolation behavior

\- existing authorization behavior

No destructive migration or silent data transformation is permitted.

43\. Final Decision

DealFlow will implement DF-155 as a tenant-scoped PostgreSQL/SQLAlchemy Property search and filtering capability.

The initial capability will provide:

Text search

\+

Structured filters

\+

Range filters

\+

Pagination

\+

Deterministic ordering

\+

Tenant isolation

\+

properties.read authorization



The implementation will remain inside the existing Property domain and will not introduce a dedicated search engine, AI matching, geospatial search, or other advanced search infrastructure.

The design intentionally provides a simple and secure foundation that can evolve as actual customer usage and Property inventory scale demonstrate the need for more advanced search capabilities.


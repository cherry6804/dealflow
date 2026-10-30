# ADR-0022: Property Availability and Status

- Status: Accepted
- Date: 2026-10-08
- Decision Owners: Cherry / DealFlow Engineering
- Decision Type: Domain/Data Model
- Scope: Property Management
- Related Sprint: DF-S06
- Related Story: DF-154
- Related Epic: DF-E06
- Depends On: ADR-0019, ADR-0020, ADR-0021

## 1. Context

DealFlow Property Management currently provides:

- Property tenant ownership and persistence through DF-151.
- Commercial fields through DF-152.
- Structured location and core property attributes through DF-153.

The next Property Management capability is DF-154:

> Track property availability/status.

The existing `transaction_type` field describes the commercial mode associated with a property:

- `SALE`
- `RENT`
- `LEASE`

It does not describe the current business state of the property.

A separate status is therefore required to represent whether a property is available, reserved, sold, rented, leased, or otherwise unavailable.

The implementation must remain compatible with the existing Property domain and must not introduce search, source/owner, matching, AI, or workflow capabilities that belong to later stories.

## 2. Decision

The Property entity will be extended with a dedicated structured `status` field.

The status will be stored directly on the `properties` table.

The initial controlled status vocabulary will be:

- `AVAILABLE`
- `RESERVED`
- `SOLD`
- `RENTED`
- `LEASED`
- `UNAVAILABLE`

These values are an engineering/product decision for DF-154 because the Jira story defines the capability but does not specify an exact status vocabulary.

## 3. Status Semantics

### 3.1 AVAILABLE

The property is currently available for the commercial transaction represented by its `transaction_type`.

### 3.2 RESERVED

The property is temporarily reserved and should not be treated as generally available.

### 3.3 SOLD

The property has been sold.

### 3.4 RENTED

The property has been rented.

### 3.5 LEASED

The property has been leased.

### 3.6 UNAVAILABLE

The property is not currently available for the organization's normal property workflow for a reason that does not require a more specific lifecycle state.

## 4. Relationship to Transaction Type

`transaction_type` and `status` represent different concepts.

`transaction_type`:

- `SALE`
- `RENT`
- `LEASE`

describes the commercial transaction mode.

`status`:

- `AVAILABLE`
- `RESERVED`
- `SOLD`
- `RENTED`
- `LEASED`
- `UNAVAILABLE`

describes the current property state.

DF-154 does not remove, rename, or alter the DF-152 commercial fields.

## 5. Persistence

The following field will be added to `properties`:

| Field | Type | Nullable | Description |
|---|---|---:|---|
| `status` | String | Yes | Controlled Property availability/status value |

The database column will initially remain nullable to preserve compatibility with Property records created before DF-154.

Existing records will not be silently modified or assigned a fabricated status.

No migration will populate existing rows.

## 6. API

DF-154 will expose:

```text
PATCH /api/v1/properties/{property_id}/status

The endpoint will:
1. Require authenticated user context.
2. Require properties.update.
3. Require verified tenant context.
4. Retrieve the Property using the tenant organization.
5. Validate the status against the controlled vocabulary.
6. Update only the Property status.
7. Persist the change transactionally.
8. Return the updated Property status representation.
The client must not provide or override organization_id.
7. Authorization and Tenant Isolation
Property status modification requires:
properties.update

The organization is derived from the verified tenant context.
The Property must be retrieved using both:
property_id
organization_id

A Property belonging to another organization must behave as not found.
No client-supplied organization identifier may override the tenant context.
8. Backward Compatibility
DF-154 must not modify the behavior of:
- DF-151 Property creation.
- DF-152 Property commercial fields.
- DF-153 Property location and core attributes.
The new status column is additive.
Existing Property records remain valid with status = NULL.
No destructive migration or silent data transformation is permitted.
9. Validation
Only the controlled status values defined by this ADR are accepted through the DF-154 API.
Invalid status values must be rejected with a validation error.
The database column itself remains nullable and does not enforce the application vocabulary through a database enum at this stage.
The service and API layer are responsible for controlled-value validation.
10. Transaction Behavior
Status modification and persistence must occur within the existing request transaction model.
A failed validation must not modify the Property.
A Property that cannot be resolved within the verified tenant must not be modified.
No separate status history or event record is created by DF-154.
11. Scope Boundaries
DF-154 does not introduce:
- Status history.
- Status transition history.
- Workflow engines.
- Approval workflows.
- Booking management.
- Reservation management.
- Occupancy management.
- Listing publication state.
- External listing synchronization.
- Search or filtering.
- Ranking.
- Geographic search.
- Source or owner association.
- Lead/customer matching.
- AI recommendations.
- Automated status transitions.
These capabilities may be considered in future stories if required.
12. Search Boundary
The status field is persisted as structured data so that future DF-155 search/filter capabilities can use it.
DF-154 itself does not implement Property search or filtering.
13. Migration
The migration must:
- Add only the status column to properties.
- Be additive.
- Be reversible.
- Leave existing Property rows unchanged.
- Avoid unrelated schema changes.
- Avoid fabricated default status values.
14. Testing Requirements
DF-154 must include tests covering:
Model/Persistence
- Status field persists.
- Existing Property records remain valid with NULL status.
- Controlled status values persist correctly.
API
- Successful status update.
- Status response.
- Invalid status rejection.
- Unknown Property returns 404.
- Tenant-scoped update.
- Cross-tenant Property cannot be updated.
- Missing tenant context is rejected.
- Missing properties.update permission is rejected.
Regression
Existing DF-151, DF-152, and DF-153 Property behavior must remain unchanged.
15. Rejected Alternatives
Generic JSON status object
Rejected because status is a first-class business attribute and should remain structured and queryable.
Separate PropertyStatus entity
Rejected because DF-154 only requires a current status value and does not require status history or workflow behavior.
Database enum
Not selected initially because controlled-value enforcement belongs at the application boundary and future status vocabulary may evolve.
Automatic status transitions
Rejected because DF-154 does not define the business events or workflows that would safely trigger automatic transitions.
16. Consequences
Positive
- Property availability becomes explicitly represented.
- Status is structured and future-search compatible.
- Existing commercial semantics remain separate.
- Tenant isolation remains consistent with the Property domain.
- Existing Property records remain backward compatible.
- Future workflow and history capabilities can be introduced without changing the basic Property identity.
Trade-offs
- Existing Properties may have NULL status until explicitly updated.
- The application must maintain the controlled status vocabulary.
- Status semantics may need to evolve as future Property workflows are introduced.
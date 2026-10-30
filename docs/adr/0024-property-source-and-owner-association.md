# ADR-0024: Property Source and Owner Association

-   **Status:** Proposed
-   **Date:** 2026-10-08
-   **Scope:** Property Management
-   **Story:** DF-156 --- Associate Property
-   **Depends on:** ADR-0019, ADR-0020, ADR-0021, ADR-0022, ADR-0023

## 1. Context

DF-151 through DF-155 established the tenant-scoped Property domain,
including:

-   Property persistence foundation
-   Commercial fields
-   Location and core attributes
-   Availability/status
-   Search and filtering

DF-156 requires Property to support association with its source and
owner.

The association must integrate with the existing DealFlow domain model
rather than creating a parallel identity representation.

## 2. Decision

Property source and owner association will be implemented as first-class
relationships from Property to existing tenant-owned domain identities.

The exact target entity and foreign-key structure must be confirmed
against the existing DealFlow domain model before implementation. This
ADR therefore establishes the architectural constraints for DF-156
without inventing a new identity/entity model.

### 2.1 Tenant Ownership

All Property associations are tenant-scoped.

The authenticated and verified tenant context is authoritative.

The client must not be trusted to select an arbitrary `organization_id`.

Any associated source or owner must belong to the same organization as
the Property.

Cross-tenant associations must be rejected.

### 2.2 Source

A Property Source represents the existing domain entity from which the
Property inventory/opportunity was obtained.

The implementation must reference an existing tenant-owned domain
identity where one already exists.

A new duplicate Contact/Party/Customer identity must not be created
solely for DF-156.

### 2.3 Owner

A Property Owner represents the existing domain identity that owns or
provides the Property.

The implementation must reference an existing tenant-owned domain
identity where one already exists.

A new duplicate identity must not be created solely for DF-156.

### 2.4 Nullability

Source and owner association should remain nullable unless the existing
product/domain requirements establish that either relationship is
mandatory.

Existing Properties created by DF-151 must remain valid without source
or owner information.

No fabricated source or owner associations will be created for existing
records.

### 2.5 Update Semantics

DF-156 should support updating the Property's source and owner
associations.

If the final domain design permits clearing an association, explicit
null should clear the relationship.

Omitted fields must remain unchanged when using a partial update
operation.

### 2.6 Tenant-Safe Association

Association operations must:

1.  Resolve the Property using the verified tenant context.
2.  Resolve the source/owner target using the same verified tenant
    context.
3.  Reject missing targets.
4.  Reject cross-tenant targets.
5.  Persist the relationship transactionally.

The client must never be able to bypass tenant isolation by supplying
another organization identifier.

## 3. API Direction

The intended API boundary is:

`PATCH /api/v1/properties/{property_id}/association`

The final request and response schema must be defined after confirming
the existing source/owner domain entity.

The endpoint must require:

`properties.update`

The response should return the updated Property association state.

## 4. Data Model Direction

The preferred design is to add direct foreign-key relationships to the
existing tenant-owned entity where the domain model supports this
cleanly.

Composite tenant-safe foreign keys should be preferred when the
referenced entity already exposes `(id, organization_id)` as a
tenant-safe key.

No JSON-based association storage will be introduced.

No free-form source/owner names will replace relational identity
references.

No separate association table will be introduced unless the existing
domain model demonstrates that multiple source/owner records per
Property are an actual requirement.

## 5. Deletion Behavior

DF-156 must not silently delete a Property when its associated source or
owner is removed.

The final foreign-key deletion behavior must preserve Property integrity
and follow the existing domain's deletion policy.

No cascade delete from source/owner to Property will be introduced
without an explicit domain requirement.

## 6. Permissions and Security

The association endpoint requires:

`properties.update`

Security requirements:

-   authenticated user
-   verified tenant context
-   tenant-scoped Property lookup
-   tenant-scoped source lookup
-   tenant-scoped owner lookup
-   no client-supplied organization trust
-   no arbitrary foreign-key assignment across tenants

## 7. Backward Compatibility

DF-156 must be additive.

It must not change the behavior or contracts established by:

-   DF-151 Property creation
-   DF-152 Property commercial fields
-   DF-153 Property location and attributes
-   DF-154 Property availability/status
-   DF-155 Property search and filtering

Existing Property records must remain usable.

Existing Property APIs must remain compatible.

Existing search/filter behavior must remain unchanged unless association
fields are explicitly added to a future search story.

## 8. Explicitly Out of Scope

DF-156 does not include:

-   Lead association
-   Customer Requirement association
-   Customer Profile association
-   Property matching
-   Lead-property matching
-   AI matching
-   Source history
-   Owner history
-   Ownership transfer workflow
-   Commission calculation
-   Brokerage calculation
-   Listing/publication workflow
-   Property booking/reservation
-   Search changes
-   Saved searches
-   Analytics
-   Notifications

These capabilities require separate stories and decisions.

## 9. Testing Requirements

The implementation must include tests covering:

-   source association
-   owner association
-   source update
-   owner update
-   clearing nullable associations, if supported
-   Property not found
-   source/owner target not found
-   cross-tenant source rejection
-   cross-tenant owner rejection
-   permission enforcement
-   tenant isolation
-   backward compatibility with existing Property APIs
-   search behavior remaining unchanged

## 10. Migration Policy

A database migration will be created only if the confirmed existing
domain relationship requires schema changes.

The migration must be additive and limited to DF-156.

No unrelated schema/index changes should be included.

## 11. Confirmed Domain Model

The existing DealFlow domain model was inspected before implementation.

The confirmed association target for both Property Source and Property Owner
is the existing `Contact` entity.

### 11.1 Property Source

A Property Source is represented by:

`properties.source_contact_id`

The relationship is:

`(properties.source_contact_id, properties.organization_id)`
→ `(contacts.id, contacts.organization_id)`

### 11.2 Property Owner

A Property Owner is represented by:

`properties.owner_contact_id`

The relationship is:

`(properties.owner_contact_id, properties.organization_id)`
→ `(contacts.id, contacts.organization_id)`

### 11.3 Tenant Ownership

The existing `Contact` entity is tenant-scoped through
`organization_id`.

The repository already establishes tenant-safe composite foreign-key
patterns for relationships involving Contact and other tenant-owned
entities.

DF-156 will follow the same architectural pattern.

### 11.4 Association Characteristics

Both associations are:

- nullable
- tenant-scoped
- directly associated with Property
- references to existing Contacts
- protected by the verified Property tenant context

A Contact may simultaneously be:

- the Property Source
- the Property Owner

No duplicate Contact or identity record will be created for DF-156.

### 11.5 Deletion Behavior

DF-156 must not cascade deletion from Contact to Property.

If a Contact is removed or becomes unavailable, Property records must not
be silently deleted.

The final database foreign-key deletion behavior must preserve Property
integrity and follow the existing Contact lifecycle policy.

### 11.6 Confirmed Implementation Direction

The Property model will be extended with:

- `source_contact_id`
- `owner_contact_id`

Both fields will use tenant-safe composite foreign keys.

No separate association table is required.

No JSON-based association representation is required.

No free-form source or owner identity fields are required.

## 12. Consequence

This decision integrates Property with the existing DealFlow identity
model instead of creating a second identity model for Property.

Using Contact as the common association target allows a Property Source
and Property Owner to participate in the existing Contact, Customer
Profile, and Lead domain relationships without duplicating identities.

Tenant-safe composite foreign keys ensure that a Property cannot be
associated with a Contact belonging to another organization at the
database relationship level.

The DF-156 implementation therefore remains additive and preserves the
contracts established by DF-151 through DF-155.
# ADR-0017: Customer Requirement Lead and Customer Profile Association

- Status: Accepted
- Date: 2026-10-05
- Decision Owners: DealFlow Engineering

## 1. Context

A Customer Requirement represents a business requirement captured within a tenant. The existing architecture separates Contact, Customer Profile, Lead, and Requirement responsibilities:

- Contact represents the reusable person/contact identity.
- Customer Profile represents customer-specific business context.
- Lead represents a prospective business opportunity or process state.
- Customer Requirement represents what the customer wants or needs.

A requirement may need to be connected to the business context that generated or owns it. In particular, a requirement may originate from a Lead, belong to an existing Customer Profile, belong to both, or remain unassociated.

The association must remain tenant-safe and must not trust organization identifiers supplied by clients.

## 2. Decision

Extend the existing Customer Requirement entity with two optional tenant-safe references:

- lead_id
- customer_profile_id

Both references are nullable so existing requirements remain valid and backward compatible.

The database will enforce tenant-safe relationships using composite foreign keys:

- lead_id + organization_id -> leads.id + leads.organization_id
- customer_profile_id + organization_id -> customer_profiles.id + customer_profiles.organization_id

The Customer Requirement organization_id remains the authoritative tenant boundary. Clients must not provide or override the organization_id used for these associations.

The service layer must verify that the referenced Lead and Customer Profile belong to the current tenant before creating or updating an association.

## 3. Supported Association States

A requirement may exist in any of the following valid states:

1. No Lead and no Customer Profile.
2. Lead only.
3. Customer Profile only.
4. Both Lead and Customer Profile.

This allows the requirement lifecycle to evolve without requiring a separate association record.

## 4. Why the Association Is Stored on Customer Requirement

A separate many-to-many association table is not required for the current business relationship. A requirement represents one business requirement and may optionally reference its originating Lead and/or Customer Profile.

Keeping the references directly on Customer Requirement provides:

- Simple querying.
- Simple API behavior.
- Clear ownership semantics.
- Strong tenant isolation through composite foreign keys.
- Backward compatibility with existing requirements.
- A structure that can be extended later if the business model requires richer relationship history.

## 5. Tenant Isolation

Tenant isolation is enforced at multiple layers:

- API and service queries remain scoped by the authenticated organization.
- Lead lookup must include the current organization_id.
- Customer Profile lookup must include the current organization_id.
- Composite foreign keys prevent a requirement from referencing an entity belonging to another organization.

A client-supplied organization_id is never trusted for authorization or association decisions.

## 6. Delete Behavior

The association foreign keys use the database default NO ACTION behavior rather than cascading deletion.

A Lead or Customer Profile referenced by a Requirement must not cause the Requirement itself to be deleted automatically.

Because organization_id is part of the tenant-safe composite relationship and is mandatory on Customer Requirement, automatic SET NULL behavior is also avoided. Associations should be explicitly cleared before a referenced entity is permanently deleted.

## 7. API Direction

The association will be exposed through the Customer Requirement API.

Planned operations:

- POST /api/v1/customer-requirements/{requirement_id}/association
- GET /api/v1/customer-requirements/{requirement_id}/association
- PATCH /api/v1/customer-requirements/{requirement_id}/association

The API operates within the authenticated tenant context and uses the existing Customer Requirement authorization model.

## 8. Backward Compatibility

The new fields are nullable. Existing Customer Requirements therefore remain valid without migration of existing business data.

No destructive data migration is required.

Existing Customer Requirement APIs remain compatible unless an association is explicitly supplied.

## 9. Security Requirements

The implementation must:

- Enforce tenant-scoped reads and writes.
- Reject references to Leads belonging to another tenant.
- Reject references to Customer Profiles belonging to another tenant.
- Never accept organization_id from the client as the authorization source.
- Preserve existing authorization requirements.
- Prevent cross-tenant foreign-key relationships at the database level.

## 10. Alternatives Considered

### Alternative A - Separate Requirement Association Table

Rejected for the current scope because it introduces unnecessary complexity for two optional one-to-one references.

### Alternative B - Associate Requirement Directly Through Contact

Rejected because Contact is a reusable identity and does not represent customer-specific business context. Customer Profile is the appropriate customer-level entity.

### Alternative C - Store Only Lead Association

Rejected because requirements may belong to an established Customer Profile without an active or originating Lead.

### Alternative D - Store Only Customer Profile Association

Rejected because requirements may originate from a Lead before a Customer Profile exists or becomes relevant.

## 11. Future Compatibility

This decision does not prevent future requirement relationship capabilities such as:

- Requirement history.
- Requirement reassignment.
- Requirement activity tracking.
- Requirement-to-deal relationships.
- Requirement relationship auditing.

Such capabilities should be introduced separately when their business requirements are defined.

## 12. Consequences

Positive consequences:

- Requirements can be connected to their business context.
- Lead and Customer Profile workflows can converge on the same requirement.
- Tenant isolation remains enforced structurally.
- Existing requirements remain backward compatible.
- The implementation remains simple and query-friendly.

Trade-offs:

- A requirement currently supports at most one Lead and one Customer Profile.
- Relationship history is not stored by this decision.
- Referenced entities should have their associations cleared before permanent deletion.

## 13. Implementation Scope

This ADR covers only the Lead and Customer Profile association for Customer Requirements.

It does not introduce:

- Requirement history.
- Lead conversion.
- Deal management.
- Customer lifecycle redesign.
- Contact model changes.
- Cross-tenant relationship support.

Those concerns require separate decisions.

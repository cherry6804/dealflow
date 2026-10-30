# ADR-0007: Contact and Customer Domain Architecture

- **Status:** Accepted
- **Date:** 2026-09-29
- **Decision Owners:** Cherry / DealFlow Engineering
- **Related Sprint:** DF-S03 — Contacts & Customers
- **Related Story:** DF-31 — Define Contact and Customer Domain Model
- **Related Epic:** DF-E03 — Contacts & Customers

## 1. Context

DealFlow requires a clear business-data foundation for contacts and customers before implementing lead management, customer requirements, property matching, follow-ups, and deal operations.

The DealFlow product model identifies Contacts and customer profiles as core modules and defines the broader business lifecycle as:

> Contact → Lead → Qualification → Customer Requirement → Property Match → Shortlist → Follow-up → Site Visit → Feedback → Negotiation → Documentation → Booking/Deal → Payment → Commission → Closure → Referral

The product must support both existing/historical data and actively managed business data. Imported or historical records must remain distinguishable from actively managed records, and important active records require lifecycle state, ownership, timing, and history.

The architecture must preserve the tenant and authorization boundaries established by the Identity & Tenant Foundation sprint.

## 2. Decision

DealFlow will use a **Contact + Customer Profile** domain boundary for the initial Contacts & Customers capability.

The initial relationship is:

```text
Organization / Tenant
        |
        +---- Contact
        |
        +---- Customer Profile
                    |
                    +---- Future Lead relationship
                    |
                    +---- Future Requirement relationship
```

A Contact represents the reusable person/business-contact identity and communication information managed by the organization.

A Customer Profile represents customer-specific business context associated with a Contact. Customer-specific information must not be forced into the generic Contact record.

This separation allows DealFlow to reuse a contact across future business workflows while keeping customer-specific state and information distinct.

## 3. Contact Definition

A Contact is a tenant-owned business record representing a person or contact identity known to the organization.

The Contact domain is responsible for:

- Contact identity information.
- Basic communication information.
- Contact lifecycle state.
- Tenant ownership.
- Record timestamps.
- Source/provenance references when introduced by import or integration workflows.
- Relationships to future business records.

The Contact domain is not responsible for:

- Lead pipeline state.
- Customer requirements.
- Property inventory.
- Site visits.
- Deal negotiation.
- Payments or commissions.
- AI-generated decisions.
- Authorization policy definitions.

Those capabilities belong to their respective domains.

## 4. Customer Profile Definition

A Customer Profile represents customer-specific business context associated with a Contact.

The Customer Profile domain is responsible for:

- Customer lifecycle state.
- Customer-specific business information.
- Customer relationship context.
- Tenant ownership.
- Association with the underlying Contact.
- Future links to leads, requirements, activities, and deals.

The Customer Profile must not duplicate information that is authoritative in another domain.

For example, a customer's future property requirement belongs to the Requirement domain rather than becoming an uncontrolled field on the Customer Profile.

## 5. Contact vs Customer Boundary

The following distinction is mandatory:

| Concept | Purpose |
|---|---|
| Contact | Who the organization knows and how that person/contact can be identified or reached |
| Customer Profile | Customer-specific business context and lifecycle |
| Lead | A prospective business opportunity/process state |
| Requirement | What the customer wants or needs |
| Property | Real-estate inventory or opportunity being considered |
| Deal | Commercial transaction/workflow |

A Contact does not automatically become a Lead.

A Contact does not automatically become a Customer Profile merely because the record exists.

The system must support gradual enrichment of records as business workflows progress.

## 6. Tenant Ownership

All Contact and Customer Profile records are tenant-scoped.

The authoritative ownership boundary is:

```text
Authenticated User
        |
        v
Verified Organization Membership
        |
        v
Tenant Context
        |
        v
Contact / Customer Data
```

Client-provided organization identifiers are never treated as proof of authorization.

Tenant ownership must be established from verified server-side tenant context.

Cross-tenant access is denied by default.

A permission granted within one organization must not authorize access to another organization.

## 7. Identity and Relationship Rules

The initial implementation will keep Contact and Customer Profile relationships explicit.

A Customer Profile must reference its owning organization and its associated Contact according to the approved domain model.

Future Lead functionality may reference an existing Contact and/or Customer Profile.

Future Requirement functionality may reference the appropriate Customer Profile and/or Lead.

The Contacts & Customers domain must not create hidden coupling to future Lead, Requirement, Property, or Deal implementations.

## 8. Lifecycle

Contact and Customer Profile records require explicit lifecycle state.

The initial lifecycle must remain intentionally simple and extensible.

At minimum, the architecture supports:

```text
Active
Inactive
```

Future lifecycle states may be introduced through controlled, backward-compatible changes.

Lifecycle transitions must be validated by server-side domain/application logic rather than relying solely on frontend behavior.

Deactivation must not silently destroy historical relationships or business history.

Archival and deletion policies will be defined by later product, security, privacy, and compliance requirements.

## 9. Imported and Historical Data

DealFlow must support historical and imported business data.

Imported records must retain provenance and remain distinguishable from actively managed records when the import capability is implemented.

The Contacts & Customers domain therefore remains compatible with future import metadata such as:

- Source.
- Import batch.
- Original source identifier.
- Import timestamp.
- Mapping/validation state.
- Review state.

Importing a Contact must not automatically create an active Lead.

Imported data must not silently overwrite existing business records.

Duplicate detection and merge behavior will be implemented through the appropriate future data-quality/import capabilities rather than hidden inside basic Contact creation.

## 10. Duplicate and Identity Principles

Contact creation must not assume that one communication field alone is a globally unique identity.

Potential duplicates may be identified using available information such as:

- Email.
- Phone.
- External/source identifier.
- Other approved identifying information.

Duplicate detection must remain explainable and must not silently merge records.

A future duplicate/merge capability must preserve relevant history and provenance.

The initial Contacts & Customers implementation should establish identifiers and constraints that permit safe future duplicate management.

## 11. Audit and History

Important Contact and Customer Profile changes must remain auditable as the product matures.

The existing DealFlow audit foundation provides the architectural boundary for security-sensitive events.

Business-history requirements for Contact and Customer records will be implemented through the appropriate activity/history capabilities rather than putting unrestricted audit payloads into the core entity tables.

Sensitive authentication material must never be stored in Contact or Customer records.

## 12. Authorization Boundary

The Contacts & Customers domain follows the established authorization architecture:

```text
Authentication
      |
      v
Current User Context
      |
      v
Verified Tenant Context
      |
      v
Authorization
      |
      v
Contact / Customer Operation
      |
      v
Audit where required
```

The frontend is never a security boundary.

Client-provided roles, permissions, or ownership claims are never trusted.

Authorization decisions are made server-side.

## 13. Data Evolution and Backward Compatibility

The Contact and Customer Profile model must support controlled evolution.

Required principles:

- No silent destructive migrations.
- Existing records remain usable after additive changes.
- Database changes use explicit migrations.
- New fields should be introduced in a backward-compatible manner where practical.
- Existing relationships must not be invalidated without a controlled migration strategy.
- Deprecated behavior requires an explicit deprecation process.
- Historical information must remain understandable.

Future capabilities must be able to coexist with earlier records.

## 14. API and Domain Boundary

The domain model is independent of API presentation.

API contracts must not expose internal persistence details unnecessarily.

Future API capabilities should support:

- Stable identifiers.
- Explicit validation.
- Tenant-aware authorization.
- Pagination for collection endpoints.
- Controlled filtering/search.
- Consistent error handling.
- Backward-compatible additive evolution.

These API concerns will be implemented in the corresponding API stories.

## 15. Security Invariants

The following invariants apply:

1. No authenticated identity means no protected Contact or Customer operation.
2. No verified tenant context means no tenant-scoped Contact or Customer operation.
3. No active organization membership means no tenant context.
4. Client-provided organization ownership is never trusted.
5. Client-provided roles or permissions are never trusted.
6. Cross-tenant records must never be returned or modified.
7. Contact and Customer records must not contain authentication secrets.
8. Sensitive business information must be accessed only through authorized application paths.
9. Security-sensitive authorization decisions remain auditable.
10. Deactivation must not silently destroy historical business relationships.

## 16. Non-Goals

DF-31 does not implement:

- Contact database tables.
- Customer database tables.
- Contact APIs.
- Customer APIs.
- Lead management.
- Customer requirements.
- Property management.
- Property matching.
- Follow-ups.
- Site visits.
- Deals.
- Import processing.
- Duplicate detection engine.
- Contact activity history implementation.
- AI functionality.
- Advanced customer segmentation.
- Complex configurable lifecycle workflows.

Those capabilities belong to later stories or epics.

## 17. Consequences

### Positive

- Clear separation between reusable contact identity and customer-specific business context.
- Strong tenant ownership boundary.
- Supports future Lead and Requirement relationships without overloading the Contact entity.
- Allows gradual data enrichment.
- Supports imported/historical data without forcing it into active workflows.
- Provides a controlled foundation for future search, duplicate detection, activities, and customer workflows.
- Preserves backward-compatible evolution as DealFlow grows.

### Trade-offs

- Contact and Customer Profile are separate concepts and may require explicit relationships.
- Future Lead conversion rules must define when an existing Contact or Customer Profile is reused.
- Duplicate management requires a dedicated capability rather than being hidden in basic CRUD.
- Some customer information may require relationships to other domains instead of additional Customer Profile columns.

## 18. Implementation Guidance for S03

The following implementation order is established:

```text
DF-31
Define Contact and Customer Domain Model
        |
        v
DF-32
Create Contact Model
        |
        v
DF-33
Create Customer Profile Model
        |
        v
DF-34
Add Contact and Customer Migrations
        |
        v
DF-35
Contact Creation and Retrieval APIs
        |
        v
DF-36
Contact and Customer List/Search
        |
        v
DF-37
Contact and Customer Update/Lifecycle
```

DF-32 and DF-33 must follow the domain boundaries established by this ADR.

## 19. Acceptance Traceability

DF-31 is complete when:

- Contact and customer concepts are clearly defined.
- Ownership relationships between organization, contact, and customer are documented.
- Contact and customer lifecycle boundaries are documented.
- Tenant isolation rules are documented.
- Relationships with future leads and requirements are documented.
- Data ownership and responsibility boundaries are defined.
- Backward-compatibility considerations are documented.
- ADR is created and accepted where architectural decisions are required.

## 20. Related Architecture

This ADR builds on:

- ADR-0002 — Identity and Tenant Architecture.
- ADR-0004 — Tenant Context Architecture.
- ADR-0005 — Authorization Model Architecture.
- ADR-0006 — Authorization Audit Events Architecture.

It must remain consistent with the DealFlow product strategy, Domain & Data Model documentation, security architecture, API standards, testing strategy, and documentation governance.

## 21. Decision Outcome

DealFlow will implement Contacts & Customers as a tenant-scoped domain with a clear separation between reusable Contact identity and Customer-specific business context.

The domain is intentionally small for the initial V1 implementation while preserving explicit extension points for Leads, Requirements, Properties, Activities, Deals, Imports, Automation, and future AI-assisted capabilities.

This decision is accepted as the architectural baseline for DF-31 and the subsequent S03 Contact and Customer implementation stories.

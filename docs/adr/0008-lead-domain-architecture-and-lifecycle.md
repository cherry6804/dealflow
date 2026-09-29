# ADR-0008: Lead Domain Architecture and Lifecycle

- Status: Accepted
- Date: 2026-09-29
- Decision Type: Domain Architecture
- Scope: Lead Management
- Related Sprint: S04
- Related Stories: DF-39, DF-40, DF-41, DF-42, DF-43, DF-44, DF-45, DF-46, DF-47

## Context

DealFlow already provides a tenant-scoped Contact and Customer foundation.

A Contact represents a reusable person or business contact identity. A Contact is not automatically an active business opportunity.

DealFlow now requires a Lead domain to represent an actively managed real-estate business opportunity.

The Lead domain will become the foundation for later capabilities including:

- customer requirements
- property matching
- property shortlisting
- follow-ups
- site visits
- negotiation
- documentation
- booking
- payment
- commission
- automation
- AI-assisted operations

The Lead domain therefore needs a stable and extensible architecture before implementation begins.

The Lead domain must also preserve the tenant-isolation and authorization principles already established in the platform.

## Decision

DealFlow will introduce Lead as a separate tenant-scoped business entity.

A Lead represents an active business opportunity associated with an existing Contact.

A Contact does not automatically become a Lead.

Lead creation must be an explicit business operation.

Each Lead belongs to exactly one Organization and references a Contact belonging to that same Organization.

The Lead domain will separate business concepts that have different meanings:

- lifecycle status
- interest
- outcome
- owner
- next action

These concepts must not be collapsed into a single status field.

## Lead and Contact Relationship

The relationship is:

Contact
→ may have zero or more Leads over time

A Contact can exist without a Lead.

A Contact can become a Lead through an explicit operation.

Historical Contacts imported into DealFlow must not automatically become active Leads.

The Lead must reference a Contact from the same tenant.

Cross-tenant Contact relationships are prohibited.

## Tenant Ownership

Lead is a tenant-owned entity.

Every Lead must contain an explicit Organization reference.

Application operations must derive organization ownership from the authenticated tenant context.

Clients must not be able to choose an arbitrary organization when creating or updating a Lead.

All Lead queries must be scoped to the authorized Organization.

Cross-tenant Lead access must be denied.

The existing tenant-context and authorization mechanisms remain the source of truth for tenant access.

## Lead Lifecycle

The initial Lead lifecycle is:

1. NEW
2. CONTACTED
3. QUALIFIED
4. MATCHING
5. VISIT
6. NEGOTIATION
7. WON
8. LOST
9. ON_HOLD

These states provide the initial operational lifecycle required for DealFlow V1.

The lifecycle is intentionally extensible so additional states or domain-specific workflows can be introduced later without invalidating existing Lead records.

## Lifecycle Meaning

### NEW

The Lead has been created but meaningful engagement has not yet been completed.

### CONTACTED

Initial communication or outreach has occurred.

### QUALIFIED

The opportunity has been sufficiently understood to continue active business handling.

### MATCHING

DealFlow is actively identifying or evaluating suitable properties for the Lead.

### VISIT

A property visit or visit-related activity is part of the current Lead workflow.

### NEGOTIATION

The opportunity has progressed to negotiation.

### WON

The opportunity has successfully reached a business-success state.

### LOST

The opportunity is no longer expected to proceed.

### ON_HOLD

The opportunity is temporarily paused but remains retained in the system.

ON_HOLD is not equivalent to deletion or permanent loss.

## Status and Outcome

Lead status and Lead outcome are separate concepts.

Status represents the current position in the Lead workflow.

Outcome represents the business result associated with the opportunity.

A status change must not automatically overwrite unrelated business information.

This separation allows DealFlow to represent states such as:

- QUALIFIED + no outcome
- NEGOTIATION + no outcome
- WON + successful outcome
- LOST + unsuccessful outcome

The exact outcome vocabulary may evolve as DealFlow's deal domain becomes more mature.

## Interest

Interest is independent from lifecycle status.

Interest represents the current level or nature of customer interest as required by the Lead workflow.

Interest may change while the lifecycle status remains unchanged.

Updating interest must not implicitly change lifecycle status or outcome.

The initial implementation should use a controlled representation rather than unrestricted arbitrary text.

The exact controlled values will be finalized during DF-40.

## Lead Ownership

A Lead may have an assigned owner.

The owner represents the user responsible for managing the opportunity.

An assigned owner must belong to the same Organization as the Lead.

Cross-tenant ownership is prohibited.

Ownership changes must remain auditable.

The Lead architecture must allow Leads to exist without an owner where the business workflow permits unassigned Leads.

## Next Action

Every actively managed Lead should support a clear next action.

Next action represents what the responsible user should do next for the opportunity.

Next action is independent from lifecycle status.

The Lead architecture must support the information required to determine:

- what should happen next
- when it should happen
- who is responsible

Later follow-up and automation capabilities will build on this foundation.

An active Lead without a meaningful next action must be detectable by future operational views.

## Historical Data

Lead records must not be silently destroyed when the business opportunity ends.

Lost, won, and on-hold Leads retain their historical information.

The Lead lifecycle must therefore support operational closure without requiring destructive deletion.

Future archival capabilities may be introduced without changing the meaning of existing Lead records.

## Cross-Tenant Security

All Lead operations are tenant-scoped.

The following are prohibited:

- accessing another tenant's Lead
- creating a Lead for another tenant
- associating a Lead with another tenant's Contact
- assigning a Lead to a user from another tenant
- modifying another tenant's Lead

Authorization is evaluated separately from authentication.

Lead permissions will be introduced through the existing permission architecture.

Expected permissions include:

- leads.create
- leads.read
- leads.update

Additional permissions may be introduced if later workflows require finer-grained controls.

## Auditability

Important Lead operations should remain auditable.

At minimum, the architecture must support auditability for security-sensitive and ownership-sensitive actions.

Future Lead history should be capable of representing meaningful changes such as:

- Lead creation
- status changes
- ownership changes
- important lifecycle transitions
- outcome changes

The existing audit architecture remains the foundation for security authorization events.

## API Boundary

Lead APIs must not expose internal tenant ownership as a client-controlled value.

The organization is derived from authenticated tenant context.

Lead APIs will follow the existing DealFlow API conventions:

- explicit Pydantic request schemas
- explicit response schemas
- tenant dependency
- permission dependency
- service-layer business logic
- deterministic list ordering
- explicit validation
- predictable HTTP errors

## Database Boundary

Lead database relationships must enforce tenant-safe relationships where practical.

The Lead model must prevent application-level operations from creating relationships between:

- Lead in Organization A
- Contact in Organization B

Database constraints should be used where they provide meaningful protection.

Application validation remains necessary in addition to database constraints.

## Future Compatibility

The Lead model must be designed so future capabilities can be added without destructive redesign.

Future capabilities include:

- Customer Requirements
- Property Matching
- Property Shortlists
- Follow-ups
- Site Visits
- Negotiation
- Documents
- Booking
- Payment
- Commission
- Automation
- AI assistance

The Lead domain must not embed implementation details from these future capabilities prematurely.

Future domain entities should reference the Lead rather than forcing all future functionality into the Lead table.

## AI Compatibility

Future AI capabilities must operate within the same identity, tenant, permission, policy, and audit boundaries as human users.

AI must not receive unrestricted Lead access.

AI-generated actions involving Leads must respect:

- tenant scope
- user permissions
- policy
- approval requirements
- audit requirements

The Lead architecture therefore cannot rely on implicit or unrestricted access patterns.

## Data Integrity Rules

The following rules are mandatory:

1. Every Lead belongs to exactly one Organization.
2. Every Lead references a Contact from the same Organization.
3. Contact creation does not automatically create a Lead.
4. Lead creation is explicit.
5. Lead status is separate from interest.
6. Lead status is separate from outcome.
7. Lead ownership is separate from status.
8. Next action is separate from status.
9. Cross-tenant relationships are prohibited.
10. Closed Lead information is retained.
11. Organization ownership cannot be changed by normal client updates.
12. Lead history must not depend on destructive deletion.

## Implementation Order

The Lead domain will be implemented in the following order:

1. DF-39 — Lead Domain Architecture & Lifecycle Definition
2. DF-40 — Lead Data Model
3. DF-41 — Lead Migration
4. DF-42 — Lead Create & Retrieve API
5. DF-43 — Lead List, Search & Filtering
6. DF-44 — Lead Update & Lifecycle Management
7. DF-45 — Lead Assignment & Ownership
8. DF-46 — Lead Next Action & Outcome Management
9. DF-47 — Lead API Security & Regression Coverage

Each later implementation must remain consistent with the decisions in this ADR.

## Consequences

### Positive

- Lead has a clear business meaning.
- Contacts and active opportunities remain separate.
- Tenant isolation remains foundational.
- Lifecycle behavior is explicit.
- Status, interest, outcome, owner, and next action remain independently evolvable.
- Future real-estate workflows can build on Lead without overloading the Contact domain.
- Future automation and AI capabilities have a defined domain boundary.
- Historical opportunities can be retained safely.

### Trade-offs

- The Lead model is more structured than a simple generic status record.
- Additional fields and validation are required.
- Future workflow changes may require controlled lifecycle evolution.
- Some functionality intentionally remains outside Lead and will require additional domain entities.

## Rejected Alternatives

### Automatically Create a Lead for Every Contact

Rejected because a Contact is not necessarily an active business opportunity.

### Store All Lead Information in Contact

Rejected because Contact represents reusable identity information while Lead represents an active business process.

### Use One Generic Status Field for Everything

Rejected because lifecycle status, interest, outcome, ownership, and next action have different meanings and change independently.

### Allow Client-Controlled Organization IDs

Rejected because tenant ownership must come from authenticated and authorized tenant context.

### Hard Delete Closed Leads

Rejected because business history and operational traceability must be preserved.

## Acceptance Criteria Mapping

DF-39 is complete when:

- Lead is explicitly defined.
- Contact and Lead responsibilities are separated.
- Tenant ownership is defined.
- Lead lifecycle is defined.
- Status, interest, outcome, owner, and next action are separated.
- Cross-tenant rules are defined.
- Historical data behavior is defined.
- Future compatibility requirements are defined.
- AI security boundaries are defined.
- Implementation order is documented.

## Related Architecture

- ADR-0001 — Repository and Engineering Foundation
- ADR-0002 — Authentication and Session Architecture
- ADR-0003 — Tenant and Organization Architecture
- ADR-0004 — Authorization Architecture
- ADR-0005 — Audit Architecture
- ADR-0006 — Identity and Membership Architecture
- ADR-0007 — Contact and Customer Domain Architecture
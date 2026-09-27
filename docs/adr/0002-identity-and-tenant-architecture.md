# ADR-0002: Identity and Tenant Architecture

- Status: Accepted
- Date: 2026-09-27
- Decision owners: DealFlow engineering
- Related story: DF-17

## Context

DealFlow is a multi-tenant real-estate business platform.

The platform must support multiple organizations while preventing one organization's users or business data from being accessed by another organization.

Identity and tenancy must therefore be established before implementing business domains such as contacts, leads, properties, requirements, and deals.

The architecture must also support future roles, permissions, approvals, audit history, automation, integrations, and AI-assisted workflows without requiring destructive changes to the underlying tenant model.

## Decision

DealFlow will use an organization-based multi-tenant architecture.

The core relationship is:

User -> Membership -> Organization/Tenant

### User

A User represents an authenticated human identity.

A user is not itself a tenant and does not directly own tenant-scoped business data.

### Organization

An Organization represents a customer business using DealFlow.

An Organization is the tenant boundary for business data.

All tenant-scoped business records must belong to an Organization.

### Membership

A Membership connects a User to an Organization.

Membership is the source of the user's relationship with a tenant and will later carry role and authorization information.

A user may have memberships in multiple organizations.

## Tenant isolation

All tenant-scoped data must contain an explicit organization/tenant reference.

Application services and repositories must enforce tenant scope server-side.

Clients must not be trusted to select an arbitrary organization when accessing tenant-scoped resources.

Tenant context must be derived from authenticated identity and authorized membership.

Cross-tenant access is denied by default.

## Authentication and authorization

Authentication answers:

> Who is the user?

Authorization answers:

> What may this user do within this organization?

These concerns remain separate.

Authentication establishes the current user.

Membership establishes the user's relationship to an organization.

Authorization evaluates permissions within that organization.

## Future roles and permissions

Roles and permissions will be attached to the membership/organization relationship rather than directly to global user identity.

This allows the same user to have different permissions in different organizations.

The authorization system will follow a default-deny model.

## Audit context

Security-sensitive actions should be attributable to:

- authenticated user
- organization/tenant
- action
- timestamp
- relevant resource

Audit information must not bypass tenant boundaries.

## Business data rule

Business records such as contacts, leads, requirements, properties, visits, documents, and deals must be tenant-scoped.

No business domain should be implemented with an implicit or global tenant context.

## Security principles

The identity and tenant foundation follows these principles:

1. Tenant isolation is enforced server-side.
2. Client-provided tenant identifiers are not trusted for authorization.
3. Cross-tenant access is denied by default.
4. Authentication and authorization remain separate.
5. Membership determines tenant access.
6. Authorization is evaluated within tenant context.
7. Security-sensitive actions are auditable.
8. Secrets are configuration-driven and never stored in source code.
9. Future roles and permissions must not weaken tenant isolation.
10. AI-assisted actions must use the same identity, tenant, permission, policy, and audit boundaries as human actions.

## Consequences

### Positive

- Clear tenant isolation boundary.
- Supports multiple organizations per user.
- Supports organization-specific roles and permissions.
- Provides a stable foundation for all future business domains.
- Supports auditability and future AI authorization requirements.
- Avoids embedding tenant assumptions separately into every business feature.

### Trade-offs

- Tenant context must be carried through application layers.
- Database models require explicit tenant relationships.
- Authorization adds complexity compared with a single-tenant application.
- Cross-tenant reporting and platform administration require explicit privileged boundaries.

These trade-offs are accepted because tenant isolation is a foundational security requirement.

## Rejected alternatives

### Global user-owned business records

Rejected because business data must belong to an organization rather than directly to a user.

### Client-selected tenant without server-side authorization

Rejected because a client-controlled tenant identifier cannot be trusted as an authorization boundary.

### Separate database architecture for every customer

Not selected for the initial DealFlow architecture because it introduces operational complexity that is not required for the initial product scale.

The application-level tenant boundary must nevertheless remain strong enough to support future infrastructure evolution.

## Future compatibility

The architecture must allow future evolution toward:

- advanced RBAC
- organization-level policies
- approvals
- SSO
- MFA
- enterprise identity providers
- delegated administration
- service identities
- API clients
- integrations
- automation
- AI agents

These capabilities must inherit the same identity, tenant, permission, policy, and audit boundaries.

## Validation

Before business-domain development depends on this architecture, the implementation must demonstrate:

- users can belong to organizations through memberships
- tenant context is derived from authenticated identity
- tenant-scoped data cannot cross organization boundaries
- unauthorized access is denied
- authorization is evaluated within the tenant
- security-sensitive actions can be audited
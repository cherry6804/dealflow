# ADR-0004: Tenant Context Architecture

- Status: Accepted
- Date: 2026-09-29
- Decision owners: DealFlow Engineering
- Scope: Identity & Tenant Foundation
- Related stories: DF-22
- Related ADRs: ADR-0002 Identity and Tenant Architecture, ADR-0003 Authentication Security Architecture

## 1. Context

DealFlow uses an organization-based multi-tenant architecture.

A user is an identity. An organization is a tenant. An organization membership connects a user to an organization.

A user may belong to multiple organizations. Therefore, authentication of a user does not by itself determine which tenant the current request is operating on.

Tenant context must be resolved explicitly after authentication and must be verified server-side before tenant-scoped business operations are allowed.

The system must prevent a client from selecting an organization and gaining access merely by supplying an organization identifier. Tenant selection is a request input; tenant access is determined by server-side membership and organization state.

## 2. Decision

DealFlow will use an explicit organization identifier to select the tenant for tenant-scoped requests.

The initial transport mechanism for tenant selection is the HTTP header:

`X-Organization-ID: <organization UUID>`

The header is only a tenant-selection signal. It is never treated as proof of authorization.

The server will resolve tenant context using the following sequence:

1. Authenticate the request and establish the current user context.
2. Read the requested organization identifier.
3. Find the membership for the authenticated user and requested organization.
4. Require the membership to be active.
5. Require the organization to be active.
6. Create the tenant context from the verified organization and membership.
7. Allow downstream tenant-scoped operations to use the resolved tenant context.

If any required condition fails, the request will not receive a tenant context.

## 3. Tenant Context

The tenant context will represent the verified organization operating context for the current request.

The conceptual context is:

```text
TenantContext
├── organization
├── organization_id
└── membership
```

The membership is retained in the context because membership-level attributes will be relevant to later authorization and permission decisions.

DF-22 will not implement roles or permissions. Those concerns remain part of the authorization work defined by DF-24 and DF-25.

## 4. Security Boundaries

### 4.1 Authentication is separate from tenant selection

Authentication answers:

> Who is making this request?

Tenant selection answers:

> Which organization is the request intended to operate on?

These are separate concerns.

A successfully authenticated user must not automatically gain access to every organization.

### 4.2 Tenant selection is not authorization

The client-provided `X-Organization-ID` value must never be trusted as authorization.

The server must verify:

```text
authenticated user
        +
active membership
        +
requested organization
        +
active organization
        =
valid tenant context
```

### 4.3 Cross-tenant access is denied by default

If the authenticated user does not have an active membership in the requested organization, the request must not receive a tenant context.

A user must not be able to access another organization by changing only the organization identifier.

### 4.4 Inactive memberships are denied

A membership with `is_active = false` does not grant tenant access.

### 4.5 Inactive organizations are denied

An organization with `is_active = false` does not provide an active tenant context, even if the user has a membership record.

### 4.6 No implicit tenant selection

The system must not silently select an arbitrary organization when a tenant-scoped operation requires an organization context.

A future product-level default-organization feature may be introduced separately, but such behavior must still resolve to a verified active membership.

## 5. Tenant-Scoped Data Rule

Tenant-scoped business operations must use the organization identifier from the verified tenant context.

Business code must not treat an arbitrary client-provided organization identifier as the authoritative tenant identifier after tenant resolution.

The authoritative tenant identifier for a request is:

`TenantContext.organization_id`

This establishes the foundation for consistent tenant isolation across contacts, leads, properties, requirements, follow-ups, documents, deals, and other future tenant-scoped resources.

## 6. Dependency and Application Boundary

The intended request-processing boundary is:

```text
HTTP Request
    │
    ▼
Authentication
    │
    ▼
CurrentUserContext
    │
    ▼
Tenant Selection
    │
    ▼
Membership Verification
    │
    ▼
Organization State Verification
    │
    ▼
TenantContext
    │
    ▼
Authorization
    │
    ▼
Business Operation
```

Tenant context is established after authentication and before tenant-scoped authorization and business operations.

This keeps the responsibilities separated:

- Authentication establishes identity.
- Current-user context exposes the authenticated identity.
- Tenant context establishes the verified organization context.
- Authorization determines whether the identity may perform a particular action.
- Business services execute the operation using the verified context.

## 7. Error and Failure Behavior

Tenant resolution must fail safely.

The system must not reveal unnecessary information about another organization's existence or membership state.

At the API boundary, tenant-context failures should use a consistent client-facing error contract while avoiding detailed disclosure that could enable organization or membership enumeration.

The exact public error codes and HTTP responses will be defined and tested as part of DF-22 implementation.

## 8. Future Compatibility

This decision must remain compatible with:

- users belonging to multiple organizations;
- organization switching;
- RBAC;
- permission-based authorization;
- approval workflows;
- service accounts;
- API integrations;
- background jobs;
- automation;
- audit logging;
- AI-assisted operations;
- future enterprise identity providers;
- future tenant-level policies.

Future mechanisms may introduce additional ways to select or carry tenant context, but every mechanism must ultimately resolve to a verified organization membership before tenant-scoped access is granted.

## 9. Audit and Observability

Future tenant-scoped audit events should include the resolved organization identifier together with the authenticated actor.

Tenant context must be available to application observability and audit layers without logging sensitive authentication credentials or raw session tokens.

Tenant identity should be represented using stable identifiers rather than relying only on organization display names.

## 10. Testing Requirements

DF-22 implementation must include tests covering at least:

1. Valid authenticated user with active membership and active organization.
2. Missing organization identifier.
3. Invalid organization identifier format.
4. User without membership in the requested organization.
5. Inactive membership.
6. Inactive organization.
7. User with memberships in multiple organizations.
8. Correct selection of the requested authorized organization.
9. Cross-tenant access rejection.
10. Tenant context exposing the verified organization identifier.
11. Tenant context exposing the verified membership.
12. Existing authentication behavior remaining unchanged.

## 11. Non-Goals

DF-22 does not implement:

- roles;
- permissions;
- RBAC;
- authorization policies;
- approval workflows;
- organization switching UI;
- SSO;
- MFA;
- business-resource authorization;
- tenant-scoped business models;
- audit event implementation.

Those capabilities will be addressed by their respective stories and phases.

## 12. Consequences

### Positive consequences

- Establishes a clear tenant isolation boundary.
- Supports users belonging to multiple organizations.
- Prevents arbitrary client-selected organization access.
- Keeps authentication, tenant context, and authorization separate.
- Provides a stable foundation for all future tenant-scoped business modules.
- Makes tenant identity explicit and auditable.
- Supports future enterprise authorization and policy features.

### Trade-offs

- Tenant-scoped requests require explicit tenant context.
- Each tenant-scoped request may require membership and organization validation unless safely optimized later.
- The API contract must carry organization selection.
- Future authorization layers must consistently consume the verified tenant context.

These trade-offs are intentional because tenant isolation is a security-critical platform concern.

## 13. Rejected Alternatives

### 13.1 Trust organization ID from the client

Rejected because a client-controlled identifier is not proof of membership or authorization.

### 13.2 Store the current organization only in the authentication session

Rejected because authentication and tenant selection are separate concerns, and a user may operate across multiple organizations.

### 13.3 Infer the organization automatically from the user

Rejected because a user may belong to multiple organizations and an implicit selection could produce ambiguous or unsafe behavior.

### 13.4 Put authorization logic directly into tenant resolution

Rejected because tenant resolution and authorization have different responsibilities. Tenant resolution establishes the verified organization context; authorization determines what the user may do within that context.

## 14. Decision Summary

DealFlow will establish tenant context only after authentication and server-side membership verification.

The client may request an organization using `X-Organization-ID`, but the server remains authoritative.

The resulting security invariant is:

```text
No verified active membership
        =>
No tenant context
        =>
No tenant-scoped operation
```

This decision provides the foundation for DF-22 and the subsequent authorization architecture.

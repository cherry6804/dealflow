# ADR-0005: Authorization Model Architecture

- **Status:** Accepted
- **Date:** 2026-09-29
- **Scope:** Identity & Tenant Foundation
- **Related Stories:** DF-24, DF-25, DF-26, DF-27
- **Related ADRs:** ADR-0002 Identity and Tenant Architecture, ADR-0003 Authentication Security Architecture, ADR-0004 Tenant Context Architecture

## 1. Decision Summary

DealFlow will use a server-enforced, tenant-scoped authorization model based on:

**User → Organization Membership → Role → Permission → Authorization Decision**

Authentication establishes who the caller is.

Tenant context establishes which organization the request is operating within.

Authorization determines whether that authenticated member is allowed to perform a specific action on a resource within that tenant.

Authorization is deny-by-default and must be enforced server-side at protected business-operation boundaries.

The client must never be treated as the authority for authorization decisions.

## 2. Context

DealFlow is a multi-tenant SaaS platform in which one user may belong to multiple organizations.

ADR-0002 established:

- User as the identity.
- Organization as the tenant.
- Membership as the relationship between user and organization.
- Explicit tenant isolation.
- Server-side tenant verification.

ADR-0003 established authentication as a separate security boundary.

ADR-0004 established that a verified `TenantContext` requires:

1. An authenticated user.
2. An explicitly selected organization.
3. An active membership for that user and organization.
4. An active organization.

The next security boundary is authorization.

A valid authenticated user with a valid tenant context must not automatically receive permission to perform every operation within that tenant.

## 3. Architectural Model

The authorization relationship is:

```text
User
  │
  └── Membership
        │
        └── Role
              │
              └── Permission
```

The request boundary is:

```text
Authentication
      ↓
CurrentUserContext
      ↓
TenantContext
      ↓
Authorization
      ↓
Business Operation
```

Authorization decisions must use the verified server-side identity and tenant context.

## 4. Core Terminology

### 4.1 User

A `User` represents an authenticated human identity.

A user may belong to zero, one, or multiple organizations.

A user identity alone does not grant tenant-scoped business permissions.

### 4.2 Organization

An `Organization` represents a DealFlow tenant.

Business resources are normally owned by or scoped to an organization.

### 4.3 Membership

A `Membership` represents a user's relationship with an organization.

Membership establishes tenant participation.

Membership does not, by itself, imply unrestricted access to tenant resources.

### 4.4 Role

A `Role` is a named collection of permissions assigned to a membership.

Examples may include:

- Owner
- Administrator
- Manager
- Agent
- Viewer

These names are examples of role concepts, not a final mandatory product role catalogue.

### 4.5 Permission

A `Permission` represents an allowed capability.

Permissions should be expressed using a stable resource/action model.

Examples:

```text
contacts.read
contacts.create
contacts.update
contacts.delete

leads.read
leads.create
leads.update
leads.assign

properties.read
properties.create
properties.update

deals.read
deals.create
deals.update
deals.close
```

The initial implementation should define only permissions required by actual product operations.

Unused speculative permissions should not be created merely for completeness.

### 4.6 Authorization Decision

An authorization decision answers:

> Is this authenticated member allowed to perform this action on this resource in this tenant under the applicable policy?

The answer must be determined by server-side policy and verified context.

## 5. Tenant-Scoped Authorization

Authorization is evaluated inside the verified tenant context.

The minimum conceptual inputs are:

```text
authenticated user
+
verified organization
+
active membership
+
assigned role(s)
+
requested permission
+
resource context where applicable
+
applicable policy
```

The organization identifier supplied by the client is never sufficient evidence of authorization.

The authorization layer must consume the verified `TenantContext` created by ADR-0004.

## 6. Default Deny

DealFlow authorization follows a default-deny model.

If a request cannot establish that the caller has the required permission, the operation must be denied.

The system must not infer permission from:

- client-side UI state
- URL structure
- organization ID supplied by the client
- hidden form fields
- request metadata controlled by the caller
- assumed role names
- absence of an explicit denial
- frontend route visibility

Frontend controls are usability mechanisms, not security boundaries.

## 7. Least Privilege

Users should receive only the permissions required for their role and responsibilities.

The model must support progressively granting capabilities without requiring broad administrative access.

Permissions should be specific enough to avoid unnecessary privilege while remaining understandable and maintainable.

## 8. Role-Based Foundation

The initial authorization foundation will use role-based access control.

Conceptually:

```text
Membership
    ↓
Role assignment
    ↓
Role
    ↓
Permission assignments
```

This provides a predictable foundation for the first product releases.

The architecture must remain compatible with future policy layers without requiring a destructive replacement of the initial RBAC model.

## 9. Future Authorization Layers

The initial implementation must not attempt to implement every possible authorization mechanism.

However, the architecture must remain compatible with future:

- custom roles
- resource-level permissions
- ownership rules
- team-level access
- approval policies
- attribute-based policies
- organization policies
- temporary elevated access
- service identities
- API clients
- integration identities
- automated workflows
- AI agents

Future policy evaluation must not bypass the same identity, tenant, permission, audit, and security boundaries.

## 10. Resource-Level Authorization

A permission such as:

```text
leads.update
```

does not necessarily mean every lead can be modified by every member holding that permission.

Future resource-level rules may additionally consider:

- record ownership
- team ownership
- assigned agent
- organization policy
- record state
- approval requirements

Therefore the authorization architecture distinguishes:

```text
Capability authorization
        +
Resource/policy authorization
```

DF-24 defines the architecture for this distinction but does not require all resource-level policy rules to be implemented immediately.

## 11. Separation of Authentication, Tenant Context, and Authorization

These concerns must remain separate.

### Authentication

Answers:

> Who is the caller?

### Tenant Context

Answers:

> Which organization is this request operating within, and is the caller an active member?

### Authorization

Answers:

> What is this member allowed to do within that organization?

The system must not collapse these three concepts into a single security check.

## 12. Authorization Enforcement

Authorization must be enforced on the server.

Protected business operations should depend on an authorization mechanism that receives the verified:

```text
CurrentUserContext
TenantContext
```

and evaluates the required permission.

Authorization must occur before the protected operation performs a security-sensitive business action.

Examples include:

- reading protected tenant data
- creating records
- modifying records
- deleting records
- assigning ownership
- exporting data
- changing configuration
- managing members
- changing roles
- performing administrative operations

## 13. Cross-Tenant Protection

Cross-tenant access remains denied by default.

A valid permission in organization A does not authorize access to organization B.

The authorization layer must never replace tenant verification with a global permission check.

The effective security boundary is:

```text
Authenticated User
        ↓
Verified Tenant Membership
        ↓
Tenant-Scoped Permission
        ↓
Tenant-Scoped Resource
```

## 14. Inactive State Handling

Authorization must deny access when required identity or tenant state is inactive.

At minimum:

- inactive user → authentication denied
- revoked/expired session → authentication denied
- inactive membership → tenant context denied
- inactive organization → tenant context denied
- missing required permission → authorization denied

Authorization must not attempt to reactivate or override these states.

## 15. Role Assignment Scope

Roles are assigned in the context of an organization membership.

This means the same user may have different roles in different organizations.

Example:

```text
User A
 ├── Organization X → Manager
 └── Organization Y → Viewer
```

The role used for authorization must therefore be resolved from the verified membership for the current tenant.

A global user role must not accidentally grant tenant-wide access.

## 16. Administrative Privilege

Administrative capabilities must be explicit.

An administrative role must not automatically imply unrestricted access to every future capability unless that behavior is intentionally defined.

High-impact permissions should be independently identifiable and auditable.

Examples include:

- managing organization members
- assigning roles
- changing security settings
- exporting sensitive business data
- deleting organizational data
- changing billing or entitlement configuration

## 17. Authorization Failure Behavior

Authorization failures must fail safely.

The API must not reveal unnecessary information about:

- roles
- permissions
- internal authorization policies
- existence of protected resources
- other tenants
- membership configuration

The implementation should use consistent public authorization errors while keeping detailed internal security information available for audit and observability where appropriate.

Exact HTTP status codes and response contracts will be finalized and tested during DF-25 and DF-26.

## 18. Audit and Observability

Security-sensitive authorization events should be auditable.

The future authorization audit foundation should support information such as:

- actor/user
- organization/tenant
- membership
- action
- permission evaluated
- resource type
- resource identifier where appropriate
- decision
- timestamp
- request/correlation identifier where appropriate
- reason or policy identifier where appropriate

Sensitive credentials, session tokens, and other secrets must never be written to logs.

DF-27 will define authorization audit events in greater implementation detail.

## 19. AI and Automation Compatibility

Future automation and AI capabilities must use the same authorization boundary as human users.

An AI agent, workflow, integration, or automated process must not receive implicit unrestricted access merely because it operates inside DealFlow.

Future machine identities must have:

- explicit identity
- explicit tenant scope
- explicit permissions
- policy enforcement
- auditability
- revocation capability

AI actions should be attributable to the initiating identity and/or approved machine identity according to the eventual audit model.

## 20. Backward Compatibility and Evolution

The authorization model must evolve without silently changing existing customer access.

Future authorization changes should avoid:

- silent privilege escalation
- silent privilege removal without an intentional migration or policy decision
- destructive role replacement
- ambiguous permission semantics
- uncontrolled tenant access

Permission identifiers should remain stable once released unless an explicit compatibility strategy exists.

Changes to roles or permissions must be version-aware where required by future platform evolution.

## 21. Security Invariants

The following invariants are mandatory:

```text
No authenticated identity
    => no protected operation

No verified tenant context
    => no tenant-scoped operation

No active membership
    => no tenant context

No required permission
    => authorization denied

Permission in tenant A
    => does not authorize tenant B

Client-provided role/permission claims
    => never trusted as authorization authority

Frontend visibility
    => never considered a security boundary
```

## 22. Testing Requirements

Authorization implementation must include tests for at least:

- authenticated user with required permission
- authenticated user without required permission
- multiple roles
- different roles across organizations
- inactive membership
- inactive organization
- inactive user
- missing tenant context
- cross-tenant access
- permission boundary enforcement
- administrative permission boundaries
- protected resource access
- denial behavior
- future policy/resource-level checks

Security-critical authorization tests must remain part of the regression suite.

## 23. DF-24 Scope

DF-24 defines the authorization architecture and principles.

Included:

- terminology
- RBAC foundation
- membership-scoped roles
- permission model
- default deny
- least privilege
- tenant-scoped authorization
- authorization boundary
- failure principles
- audit principles
- future extensibility
- AI/automation compatibility
- testing requirements

## 24. DF-24 Non-Goals

DF-24 does not implement:

- role database models
- permission database models
- role assignment persistence
- authorization dependencies
- authorization APIs
- admin UI
- custom roles
- resource-level policy engine
- approval workflows
- MFA
- SSO
- AI authorization execution

Those belong to later implementation stories or future releases.

## 25. Consequences

### Positive

- Clear separation between identity, tenant context, and authorization.
- Strong default-deny security boundary.
- Tenant-scoped role assignment.
- Supports users with different responsibilities across organizations.
- Provides a foundation for future resource-level policies.
- Compatible with automation and AI authorization.
- Enables auditable security decisions.
- Avoids coupling authorization to frontend behavior.

### Trade-offs

- Authorization requires additional server-side checks.
- More precise permissions increase policy-management complexity.
- Future resource-level rules will require additional policy evaluation.
- Role and permission changes require careful compatibility management.
- Security testing becomes a permanent part of product development.

These trade-offs are intentional because authorization is a security-critical subsystem.

## 26. Rejected Alternatives

### Global user roles

Rejected because users may belong to multiple organizations with different responsibilities.

### Organization ID as authorization

Rejected because tenant selection is not proof of membership or permission.

### Frontend-only authorization

Rejected because clients cannot be trusted to enforce security boundaries.

### Unrestricted administrator bypass

Rejected because it creates an uncontrolled security path and makes future auditing and policy enforcement difficult.

### Full policy engine in the first authorization story

Rejected for DF-24 because it would introduce unnecessary complexity before core RBAC and permission enforcement are established.

## 27. Final Decision

DealFlow will use:

```text
User
  ↓
Organization Membership
  ↓
Role
  ↓
Permission
  ↓
Authorization Decision
  ↓
Tenant-Scoped Business Operation
```

with:

- server-side enforcement
- default deny
- least privilege
- tenant-scoped roles
- explicit permissions
- future resource/policy evaluation
- auditability
- AI/automation compatibility
- backward-compatible evolution

The final security boundary is:

```text
Authentication
      ↓
CurrentUserContext
      ↓
TenantContext
      ↓
Authorization
      ↓
Business Operation
```

**No permission decision may bypass verified identity or verified tenant context.**

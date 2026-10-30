# ADR-0006: Authorization Audit Events Architecture

- **Status:** Accepted
- **Date:** 2026-09-29
- **Decision Owners:** DealFlow Engineering
- **Related Stories:** DF-27
- **Related Architecture:** ADR-0002, ADR-0003, ADR-0004, ADR-0005

## 1. Context

DealFlow requires an auditable security foundation so that important authentication, authorization, tenant-security, and account-security events can be recorded and investigated without weakening the security boundaries established by the platform.

DF-25 established the role and permission foundation.

DF-26 established the server-side authorization dependency:

Authentication → CurrentUserContext → TenantContext → Authorization → Business Operation

DF-27 establishes the audit-event architecture for authorization decisions and creates a reusable foundation for future security and business audit events.

The audit system must support accountability and investigation while avoiding passwords, session tokens, secrets, or unnecessary sensitive request information.

## 2. Decision

DealFlow will use a generic, persistent `AuditEvent` foundation rather than creating a one-off authorization-only audit table.

Authorization events will be represented as structured audit events within that common audit model.

The audit architecture will preserve the following security boundary:

Authentication → CurrentUserContext → TenantContext → Authorization → Audit Event

Authorization remains responsible for the authorization decision. The audit service is responsible for recording the security-relevant event.

Audit persistence must not become a mechanism for bypassing authentication, tenant isolation, or authorization.

## 3. Audit Event Model

An audit event will have a stable event identity and sufficient structured information to answer:

- Who performed or triggered the event?
- Which organization/tenant was involved?
- What event occurred?
- What action or permission was involved?
- Was the authorization decision allowed or denied?
- When did the event occur?
- Which resource was involved, when applicable?
- What request/correlation context is available, when applicable?

The model should be extensible so future event categories can use the same audit foundation.

Authorization-specific information should be represented through explicit structured fields rather than unstructured log messages wherever practical.

## 4. Actor and Tenant Association

For authenticated authorization events:

- The actor is derived from the authenticated server-side identity.
- The organization is derived from the verified `TenantContext`.
- Client-provided actor identifiers, roles, permissions, or tenant identifiers are never trusted as proof of identity or authorization.
- An authorization event must not be used to establish tenant access.

The audit record therefore reflects the already-established security context rather than creating that context.

## 5. Authorization Events

The authorization layer may produce events for relevant authorization decisions.

At minimum, the architecture supports:

- authorization allowed
- authorization denied

An authorization event should identify the permission/action evaluated and the tenant context in which the decision occurred.

The implementation must avoid recording sensitive request content merely because an authorization decision occurred.

## 6. Security and Privacy Requirements

Audit events must never contain:

- plaintext passwords
- password hashes
- session tokens
- authentication cookies
- API secrets
- private keys
- credentials
- raw authorization headers
- unnecessary sensitive request bodies

Audit records should contain only the information required for security accountability, investigation, and operational requirements.

Audit storage itself is security-sensitive and must follow the platform's access-control model.

Audit records must not be editable through ordinary business workflows.

Deletion or retention behavior must be explicitly governed rather than implemented implicitly by unrelated entity deletion.

## 7. Failure Behavior

Authorization must remain secure if audit persistence encounters a failure.

The implementation must explicitly define whether an audit persistence failure:

- fails the protected operation, or
- is handled through a controlled reliability mechanism.

For DF-27, the authorization decision must never be changed from DENY to ALLOW because audit persistence failed.

No audit failure may bypass the authorization boundary.

Operational handling of audit persistence failures must be observable and testable.

## 8. Separation of Concerns

The following responsibilities remain separate:

### Authentication

Determines whether the caller is authenticated.

### Tenant Context

Determines whether the authenticated user has an active membership in the selected organization.

### Authorization

Determines whether the current tenant membership has the required permission.

### Audit

Records relevant security events after the applicable identity, tenant, and authorization context has been established.

This separation prevents audit code from becoming an alternate authorization mechanism.

## 9. Audit Service Abstraction

Business and security components should use an audit service abstraction rather than directly constructing persistence operations throughout the application.

The abstraction should make it possible to:

- create structured audit events
- associate events with actor and tenant context
- record authorization decisions
- add future event categories
- test audit behavior independently
- evolve persistence without rewriting authorization logic

The authorization dependency should remain small and focused on authorization.

## 10. Tenant Isolation

Audit events are tenant-sensitive.

A user authorized in organization A must not gain access to audit records belonging to organization B.

Tenant association must come from verified server-side context.

Cross-tenant audit access is denied by default.

Future administrative or platform-level audit access must use an explicitly defined privileged authorization model.

## 11. Auditability and Traceability

Where request correlation information is available, audit events may include a non-secret correlation/request identifier to connect related application activity.

Correlation identifiers must not contain credentials or sensitive authentication material.

Timestamps must be generated server-side.

Event identity must be generated server-side.

Audit records must preserve sufficient information to distinguish separate authorization decisions.

## 12. Backward Compatibility and Future Evolution

The audit model must be designed for future event categories without requiring destructive migrations or breaking existing audit records.

Future capabilities may include:

- authentication security events
- account security events
- tenant security events
- role and permission changes
- administrative actions
- business record changes
- automation actions
- AI-assisted actions

Future AI and automation operations must use the same identity, tenant, authorization, and audit boundaries as human-initiated operations.

## 13. Testing Requirements

DF-27 must include tests covering at least:

1. audit event creation
2. stable event identity
3. server-side timestamp
4. actor association
5. tenant association
6. authorization action/permission association
7. allowed decision recording
8. denied decision recording
9. tenant isolation
10. absence of prohibited sensitive data
11. safe behavior when required context is unavailable
12. audit service behavior independently of HTTP transport

Tests must verify security invariants rather than only happy-path persistence.

## 14. Non-Goals

DF-27 does not implement:

- a complete enterprise SIEM
- external log shipping
- advanced audit analytics
- retention-policy automation
- compliance certification
- MFA
- SSO
- passkeys
- approval workflows
- AI authorization
- business workflow auditing beyond the foundation required here

These may be introduced in later phases without changing the core security boundaries defined by this ADR.

## 15. Security Invariants

The following invariants apply:

- No authenticated identity → no protected operation.
- No verified tenant context → no tenant-scoped operation.
- No active membership → no tenant context.
- No required permission → authorization denied.
- Permission in tenant A does not authorize tenant B.
- Client-provided authorization claims are never trusted.
- Audit records do not grant authorization.
- Audit failures never convert a DENY decision into ALLOW.
- Sensitive authentication material is never written to audit records.
- Audit access itself requires authorization.
- Audit event identity and timestamps are server-generated.

## 16. Consequences

### Positive

- Creates a reusable audit foundation.
- Makes authorization decisions traceable.
- Preserves tenant isolation.
- Separates security decisions from audit persistence.
- Provides a foundation for future security and business auditing.
- Supports future automation and AI accountability.
- Reduces the risk of fragmented, inconsistent security-event recording.

### Trade-offs

- Adds persistent storage and schema complexity.
- Requires careful retention and access-control design.
- Audit writes introduce additional operational considerations.
- Future high-volume systems may require asynchronous or specialized audit infrastructure.

These trade-offs are accepted because security accountability is a foundational platform requirement.

## 17. Final Architectural Boundary

DealFlow security architecture remains:

Authentication
→ CurrentUserContext
→ TenantContext
→ Authorization
→ Audit Event
→ Business Operation

The audit layer records the security decision and context; it does not establish identity, tenant membership, or authorization.

This ADR establishes the architectural foundation for DF-27.

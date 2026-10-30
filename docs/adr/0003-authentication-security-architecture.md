# ADR-0003: Authentication Security Architecture

- Status: Accepted
- Date: 2026-09-28
- Decision Owners: DealFlow Engineering
- Scope: Identity and authentication foundation

## Context

Authentication is a security-critical subsystem of DealFlow.

DealFlow is a multi-tenant real-estate business platform. Authentication must establish a trusted application identity before authorization and tenant access decisions are made.

The authentication foundation must protect customer accounts, credentials, sessions, tenant boundaries, and security-sensitive operations while remaining compatible with future enterprise capabilities.

Authentication must therefore be designed as a security subsystem rather than as a simple login endpoint.

## Decision

DealFlow will use a layered identity security architecture:

```text
Authentication
      |
      v
Authenticated User Identity
      |
      v
Organization Membership
      |
      v
Authorized Tenant Context
      |
      v
Application Authorization
      |
      v
Business Data

Authentication and authorization are separate concerns.

Authentication establishes who the user is.

Authorization determines what the authenticated user is allowed to do.

Tenant context is derived from authenticated identity and an authorized organization membership. Client-provided organization identifiers must never be treated as sufficient proof of tenant access.

Security Principles
1. Passwords are never stored directly

DealFlow will never store plaintext passwords.

Passwords will be processed using a modern, purpose-built password hashing mechanism with appropriate security parameters.

Password hashes will never be returned through API responses.

2. Secrets are never committed

Passwords, signing secrets, session secrets, API credentials, recovery tokens, and other sensitive credentials must not be committed to source control.

Secrets must be supplied through the application's secure configuration mechanism.

3. Authentication tokens and sessions have controlled lifecycles

Authentication credentials must have explicit:

creation rules
expiration rules
validation rules
revocation rules
logout behavior
rotation behavior where applicable

Authentication credentials must not be treated as permanent application credentials.

4. Authentication responses must minimize information disclosure

Authentication-related endpoints must avoid unnecessarily revealing whether an account exists.

Error responses must not expose:

password values
authentication secrets
token values
password hashes
internal security implementation details
unnecessary account information
5. Brute-force and automated abuse must be considered

Authentication endpoints must have protection against repeated automated attempts.

The design must support controls for:

login attempts
password reset requests
verification attempts
credential abuse
suspicious authentication activity

Rate limiting and related abuse controls will be implemented without creating unnecessary denial-of-service opportunities.

6. Account recovery is an authentication mechanism

Password recovery and account verification are security-sensitive authentication flows.

Recovery mechanisms must use:

short-lived credentials
single-use credentials where appropriate
explicit expiration
secure invalidation
abuse protection
security event logging

A recovery flow must not provide a weaker authentication boundary than normal login.

7. Authentication security events are auditable

Important authentication events must be represented as security events.

Initial event categories include:

LOGIN_SUCCEEDED
LOGIN_FAILED
LOGOUT
PASSWORD_CHANGED
PASSWORD_RESET_REQUESTED
PASSWORD_RESET_COMPLETED
EMAIL_VERIFIED
SESSION_REVOKED

Future MFA, passkey, SSO, and identity-provider events must follow the same security-event model.

8. Sensitive authentication data must not enter normal logs

Application logs must never contain:

plaintext passwords
password hashes
access tokens
refresh tokens
password-reset credentials
verification credentials
session secrets

Logs may contain safe operational metadata necessary for troubleshooting and security monitoring.

9. Tenant isolation begins after authentication

An authenticated user does not automatically have access to every organization.

The access chain is:

Authenticated User
      |
      v
Organization Membership
      |
      v
Authorized Organization
      |
      v
Tenant-scoped operation

Cross-tenant access is denied by default.

10. Authentication failures must fail safely

Unexpected authentication errors must not expose implementation details.

The external response should contain only information required by the client.

Detailed diagnostic information belongs in controlled internal logging and security monitoring.

11. Use established security mechanisms

DealFlow will use mature, well-reviewed security libraries and established security standards.

DealFlow will not invent:

custom password hashing algorithms
custom encryption algorithms
custom authentication protocols
custom token cryptography

Cryptographic primitives and security-sensitive protocol behavior must come from established implementations.

Authentication Foundation Scope

DF-20 establishes the foundation for:

User authentication
Password credential handling
Login
Logout
Authentication state
Secure session/token lifecycle
Current authenticated-user context
Authentication error handling
Basic abuse protection
Security event foundation
Password/account recovery architecture
Email verification architecture

The implementation must remain compatible with future:

Multi-factor authentication
TOTP
WebAuthn/passkeys
Enterprise SSO
External identity providers
Session management improvements
Device/session visibility
Advanced risk detection
Authentication and Authorization Boundary

Authentication must not make authorization decisions beyond establishing identity.

Example:

Login
  |
  +--> Verify credentials
  |
  +--> Establish authenticated identity
  |
  +--> Establish secure authentication state
  |
  v
Authorization
  |
  +--> Verify membership
  |
  +--> Verify role/permission
  |
  +--> Verify tenant context
  |
  v
Business operation

Role and permission implementation remains a separate concern and is covered by the authorization work in DF-24 and DF-25.

User Identity

The existing User entity represents application identity.

A user may belong to multiple organizations through the existing membership model:

User
  |
  +--> Membership --> Organization A
  |
  +--> Membership --> Organization B

Authentication identifies the user.

Membership determines which organizations the user can access.

Authorization determines what the user may do within those organizations.

Session Security

The authentication implementation must define:

authentication credential lifetime
expiration behavior
logout behavior
revocation behavior
invalidation after security-sensitive credential changes
protection against credential replay
secure client-side storage expectations

The implementation must avoid unnecessarily long-lived authentication credentials.

Password Security

Password handling must include:

secure password hashing
password verification through the hashing library
minimum password requirements appropriate for the product
protection against common credential attacks
secure password change
secure password reset
credential invalidation after password changes where appropriate

Passwords must never be logged or returned in API responses.

Account Recovery

Account recovery must be designed as a security-sensitive flow.

Recovery credentials must:

expire
be difficult to guess
be single-use where appropriate
be invalidated after successful use
not reveal unnecessary account information
be protected against repeated requests
Email Verification

Email verification must establish ownership of the configured email address before relying on email as a trusted recovery or communication mechanism.

Verification credentials must be:

time limited
single-use where appropriate
protected against brute force
invalidated after successful verification
Abuse Protection

Authentication endpoints must be designed for abuse resistance.

Protection must consider:

repeated login attempts
credential stuffing
password reset abuse
verification abuse
automated account creation
suspicious request patterns

The implementation must avoid relying on a single control for abuse prevention.

Security Event Design

Security events should capture sufficient metadata for investigation without recording secrets.

Potential metadata includes:

event type
actor/user identifier when known
organization identifier when applicable
timestamp
request correlation identifier
source/network metadata where appropriate
success/failure state
safe failure category

Secrets and credentials must never be included.

Testing Requirements

Authentication must have automated tests covering at least:

Positive cases
valid authentication
valid password verification
valid logout
valid authenticated-user context
Negative cases
invalid password
unknown account
inactive account
expired credential
invalid credential
revoked credential
malformed authentication input
Security cases
password is never returned
password hash is never returned
authentication secrets are not logged
account enumeration is minimized
duplicate/replay-sensitive credentials are rejected
tenant access cannot be established from arbitrary client input
Regression cases

Every discovered authentication security defect must receive a regression test before the defect is considered closed.

Future Compatibility

The authentication foundation must allow future security capabilities without replacing the underlying identity model.

Future capabilities include:

Password
   |
   +--> MFA
   |
   +--> Passkeys / WebAuthn
   |
   +--> Enterprise SSO
   |
   +--> External Identity Providers

All authentication methods must ultimately resolve to the same application identity and authorization boundaries.

Consequences
Positive
Strong separation between authentication and authorization
Clear tenant isolation boundary
Security-sensitive behavior is explicitly defined
Future MFA, passkeys, and SSO can be added without redesigning the identity model
Authentication security events can support future auditing and monitoring
Security testing becomes part of the authentication implementation rather than an afterthought
Trade-offs
Authentication requires more engineering than a basic login implementation
Session and recovery lifecycle management adds complexity
Abuse protection requires additional infrastructure and testing
Security controls must be continuously reviewed as threats evolve

These costs are intentional because authentication is a security-critical foundation of the product.

Non-Goals

This ADR does not fully implement:

enterprise SSO
MFA
WebAuthn/passkeys
advanced risk-based authentication
external identity-provider federation
complete authorization/RBAC

Those capabilities will build on this foundation in later work.

Security Constraint

No authentication feature is considered complete solely because the happy-path login works.

Authentication work is complete only when the associated security controls, failure behavior, lifecycle behavior, audit requirements, and automated tests satisfy the applicable Definition of Done.
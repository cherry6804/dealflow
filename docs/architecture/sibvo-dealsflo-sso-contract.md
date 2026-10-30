# SIBVO and Dealsflo SSO contract

## Ownership

- SIBVO owns account identity, organization status and membership, product membership, subscription status, trial dates, plan versions, and product entitlements.
- Dealsflo owns CRM records, Dealsflo users and roles, local sessions, and the mapping from a SIBVO subject or organization to an existing Dealsflo user or tenant.
- The applications keep separate deployments and databases. Neither application reads the other application's database.
- Email equality is not an identity or organization mapping rule. The mapping tables are `sibvo_identity_links` and `sibvo_organization_links` in the Dealsflo database.

## Current authorization flow

1. A user opens Dealsflo from the SIBVO product catalogue, which calls the registered Dealsflo `/api/v1/sso/start` endpoint with the selected SIBVO organization ID.
2. Dealsflo creates random `state` and PKCE verifier values and stores them in a short-lived, HttpOnly flow cookie. It redirects to the configured SIBVO authorization endpoint.
3. SIBVO validates the registered client, exact callback URI, state shape, authenticated browser session, active organization membership, and the authoritative Dealsflo product access decision.
4. SIBVO stores a hash of a short-lived, single-use authorization code, bound to the callback URI, PKCE challenge, state, subject, and organization. It redirects to the registered Dealsflo callback.
5. The Dealsflo backend exchanges the code using its confidential client credentials and PKCE verifier through a URL-encoded OAuth2 token request. SIBVO rechecks the user, organization, membership, and entitlement before consuming the code.
6. SIBVO returns an RS256-signed, five-minute ID token. Dealsflo fetches the registered SIBVO JWKS over the configured HTTPS origin and validates the signature, issuer, audience, expiry, issue time, nonce, and verified email claim.
7. Dealsflo resolves both explicit mapping rows, checks the local user, tenant, and membership are active, then creates its existing local session cookie.

Configuration values must agree across both applications:

| Setting | SIBVO | Dealsflo |
| --- | --- | --- |
| Client ID | `SSO_DEALSFLO_CLIENT_ID` | `SSO_DEALSFLO_CLIENT_ID` |
| Client secret | `SSO_DEALSFLO_CLIENT_SECRET` | `SSO_DEALSFLO_CLIENT_SECRET` |
| Callback URI | `SSO_DEALSFLO_REDIRECT_URI` | `SSO_DEALSFLO_REDIRECT_URI` |
| Product key | `SSO_DEALSFLO_PRODUCT_KEY` | SIBVO checks its configured product key |
| SIBVO API base URL | N/A | `SSO_SIBVO_BASE_URL`, including `/api/v1` |
| OIDC issuer | `SSO_ISSUER` | Must exactly match `SSO_SIBVO_BASE_URL` |
| OIDC signing keys | `SSO_SIGNING_PRIVATE_KEY`, `SSO_SIGNING_PUBLIC_KEY` | Public key is fetched from `{SSO_SIBVO_BASE_URL}/sso/jwks` |
| SIBVO web origin | `FRONTEND_BASE_URL` | `VITE_SIBVO_AUTH_URL` |
| Dealsflo web origin | N/A | `VITE_DEALSFLO_URL` |

Production deployments must use HTTPS, the same exact callback URI on both
servers, a strong client secret kept in backend-only configuration, and an
RSA signing key pair kept in SIBVO's secret manager. Rotate keys by publishing
the next public key before switching the active signing `kid`. Set
`VITE_SIBVO_AUTH_URL` to the SIBVO web origin (without a path); its local
development default is `http://localhost:5173`.

## Workspace and access behavior

SIBVO authorizes one organization per authorization request. Dealsflo only
opens the organization included in that authorization code and only when its
SIBVO organization mapping, identity mapping, local membership, and active
tenant all resolve. A caller cannot select a Dealsflo tenant by submitting a
Dealsflo organization ID.

The current launch button starts SSO from the organization selected in the
SIBVO catalogue. Dealsflo does not yet implement an eligible-workspace
discovery endpoint or a multi-workspace selector. A direct unauthenticated
visit is sent to SIBVO sign-in; after signing in, the user must open Dealsflo
from the SIBVO catalogue. Saved workspace selection is not an authorization
grant.

The resulting Dealsflo session is bound to the one mapped Dealsflo
organization authorized in that code. Protected requests recheck the SIBVO
session, organization membership, and entitlement every 30 seconds; they fail
closed if SIBVO cannot be reached. Tenant-protected APIs reject a
different `X-Organization-ID`, and organization discovery returns only the
bound workspace. Production rejects unbound legacy sessions and disables the
old local login and general signup endpoints.

## Plans, billing, and entitlements

SIBVO owns subscriptions, payments, plan versions, and entitlements. Each
successful revalidation stores SIBVO's access snapshot (subscription status,
plan version, product role, entitlements) on the Dealsflo session in
`auth_sessions.sibvo_access`; a session without a snapshot revalidates on its
next request. Feature checks for SSO sessions read only this snapshot, so a
locally configured plan can neither grant nor extend access. A malformed
snapshot fails closed. The snapshot must name the SIBVO organization and
product it authorizes (`organization_id`, `product_key`); a snapshot for another
organization or product, or one without that binding, is rejected and the
session fails closed. Dealsflo no longer accepts payment-provider webhooks;
providers deliver to SIBVO. The legacy `subscriptions`, `plans`,
`plan_entitlements`, and billing audit tables remain for history. They decide
access for unattested sessions only when `LOCAL_ENTITLEMENT_FALLBACK_ENABLED` is
set, which is allowed only in `development` and `test`. Staging and production
refuse to start with that flag set, and deny unattested feature access without
it. See `docs/architecture/sibvo-dealsflo-entitlement-contract.md`.

## Provisioning and invitations

SIBVO is the identity and organization source of truth. The first SSO login by
an entitled SIBVO organization owner creates the matching Dealsflo tenant,
identity mapping, organization mapping, owner membership, baseline roles, and
audit records in one transaction. The owner mapping is unique on both SIBVO
subject and SIBVO organization; no CRM rows are reassigned.

For an existing Dealsflo organization, the user must accept a pending Dealsflo
team invitation addressed to the exact verified SIBVO email. The invitation
token is submitted by POST body to the SSO start endpoint, held in a short-lived
HttpOnly flow cookie, and removed from the visible URL before authorization.
An email match by itself never links existing local accounts. Once accepted,
the explicit identity and organization mappings and invited role are created;
retries by that same mapped identity are idempotent.

SIBVO organization invitations are owner-created, seven-day, one-use links.
The server stores only a token hash; the authenticated owner receives the
invitation URL once and must hand it to the intended invitee. Acceptance
requires an active account with a verified email matching the invitation.
Automatic email delivery is not enabled. This was held by security review
because the message would export a bearer authentication token to an
invitee-supplied address; enabling mail delivery requires an approved secure
delivery design.

## Current limitations and follow-up

- The token endpoint and JWKS use the maintained `joserfc` library. The client pins
  the expected issuer to its configured SIBVO API origin and only accepts
  RS256. Discovery metadata is published, but automated signing-key rotation
  is not implemented; configure key rotation as an operational step before
  production use.
- Active Dealsflo sessions recheck SIBVO every 30 seconds by default. The
  interval is configurable, and protected access fails closed during SIBVO
  outages.
- Normal Dealsflo `/login` and `/signup` routes redirect to SIBVO. Legacy
  invitation password signup is disabled in production; the invitation is
  accepted through SIBVO identity and the verified-email mapping flow above.
  The old local login and general signup handlers return `410 Gone` in
  production. Existing sessions without an SSO-bound organization must sign
  in again after deployment.
- Browser end-to-end verification against both deployed origins, automated
  SIBVO invitation email delivery, and automated signing-key rotation remain
  operational follow-ups. The local build and backend suite do not establish
  those deployment properties.

## Data and migration safety

The migrations add `sibvo_identity_links`, `sibvo_organization_links`, a
nullable organization reference on `auth_sessions`, and an SSO nonce on
SIBVO authorization codes. They do not infer
mappings from email, rewrite existing CRM data, or drop existing tables.
Populate mappings only through a reviewed administrative process that
verifies both identities and tenant ownership.

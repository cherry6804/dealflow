# Backend proposal: customization persistence

Status: PROPOSAL. Not approved for implementation. No backend code, API, database schema or migration is changed by this document. Submit for separate review.

## 1. What exists today

- Per-user notification preferences: `GET` and `PATCH /api/v1/notifications/preferences`, stored per user and organization.
- Dashboard metrics: `GET /api/v1/dashboard/summary`. Read-only. No layout is stored.
- Organization, team and governance settings: read and manage endpoints under `/api/v1/organizations`, `/api/v1/team` and `/api/v1/governance`.
- Grid view settings: not stored on the server. The current frontend keeps them in browser `localStorage`. That is per device and per browser, and it is not shared.

## 2. What is missing

Dashboard layouts, widget configuration, saved views, grid column and density preferences, workspace settings, team and organization defaults, and configuration inheritance. None has an endpoint, table or migration.

## 3. Proposed data model (conceptual)

Each configuration is a versioned document with an owner scope.

- `layout_configuration`: id, organization_id, scope (`platform`, `organization`, `team`, `user`), scope_id, kind (`dashboard`, `workspace`, `grid_view`), name, body (JSON), schema_version, version, is_default, created_by, updated_by, created_at, updated_at, archived_at.
- `layout_configuration_revision`: append-only copy on every save, with actor and time. Supports rollback and audit.
- `saved_view`: a grid view with a reference to its owning scope and the grid id. Shared views use the team or organization scope.

The body is validated on write against a per-kind JSON schema. Unknown widget types and unsupported fields are rejected, not stored.

## 4. Endpoints (proposed)

| Method and path | Purpose | Permission |
|---|---|---|
| `GET /api/v1/configurations?kind=&scope=` | List configurations visible to the caller, with the effective resolved configuration | authenticated member |
| `GET /api/v1/configurations/effective?kind=dashboard&key=` | Resolve the configuration after inheritance | authenticated member |
| `POST /api/v1/configurations` | Create a configuration in a scope | per scope: user (self), team (team admin), organization (org admin) |
| `PUT /api/v1/configurations/{id}` | Replace the body. Requires the current version (optimistic concurrency) | owner of the scope |
| `POST /api/v1/configurations/{id}/duplicate` | Copy into the caller's scope | read access to the source |
| `POST /api/v1/configurations/{id}/reset` | Remove the caller's override and fall back to the inherited configuration | owner of the override |
| `DELETE /api/v1/configurations/{id}` | Archive, not hard-delete | owner of the scope |
| `GET /api/v1/configurations/{id}/revisions` | Revision history | owner of the scope |
| `GET` and `PUT /api/v1/users/me/preferences` | Personal preferences (density, default landing page, theme) | self |

Saved views use the same endpoints with `kind=grid_view`.

## 5. Inheritance and precedence

Highest to lowest precedence: user, team, organization, platform. A lower scope can override a higher one only for the fields the higher scope marks as customizable. Organization administrators can lock fields. Locked fields cannot be overridden.

Security permissions, subscription entitlements and platform policies are never configurable. A layout cannot make an unauthorized module reachable. The effective configuration is filtered by the server against the caller's permissions and entitlements before it is returned.

## 6. Validation and versioning

- Schema validation on every write. Unknown fields are rejected.
- Optimistic concurrency with the `version` field. A stale write returns 409 with the current version.
- Revisions are append-only, so every change has an actor and a time.
- Maximum body size and widget count, set in configuration, to bound storage.

## 7. Tenant isolation and authorization

- Every row is scoped by organization_id. Queries always filter by the caller's organization, as the existing services do.
- Team scope is checked against team membership. Organization scope is checked against the organization administrator permission.
- Platform scope is writable by SIBVO platform administrators only, through the existing platform admin path.
- Cross-tenant identifiers return 404, the same as other tenant-scoped resources.

## 8. Frontend contracts

The frontend will define typed contracts and an adapter layer for these endpoints. Until they exist, the frontend must:

- show customization controls as available only when the endpoint is present, or label them "Saved on this device only" when they are temporary;
- never present local state as organization or team persistence;
- keep the existing `localStorage` grid preferences, labelled as per-device.

## 9. Requested decisions

1. Approve the scope model (user, team, organization, platform) and the precedence rules.
2. Approve the endpoint set and the optimistic concurrency approach.
3. Approve whether team scope is required for release, or organization and user scopes are enough for the first release.
4. Approve the revision retention rule. No retention period is proposed here.
5. Confirm the permission keys for configuration management, and whether they reuse existing role permissions.

## 10. Out of scope for this proposal

Real-time collaborative editing, widget data-source configuration beyond the existing APIs, and any new analytics endpoints.

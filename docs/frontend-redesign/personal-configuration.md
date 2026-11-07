# Personal configuration

Rule: a change made by one user affects only that user's experience. It never changes another user's, a teammate's, or the organization's configuration.

## Architecture

- `frontend/src/lib/personalPreferences.ts` is the one store. It builds keys, reads and writes values, removes them, and notifies listeners.
- Key: `dealflow:<namespace>:<organizationId or "-">:<userId>[:<part>]`. Every key carries the signed-in user's id. Without a user, no key exists and nothing is read or written.
- Stored value: `{ "v": 1, "data": ... }`. A value with a different version, a wrong shape or invalid JSON is ignored and the caller's default is used. Values saved before the envelope existed are accepted and migrate on the next save.
- `frontend/src/hooks/usePersonalPreference.ts` reads one preference reactively, with `set` and `reset`. It follows the key, so a change of user or organization changes the value, and a change in this tab or another tab is picked up.

Ownership fields (as applied here):

| Field | Source |
|---|---|
| user_id | `AppContext.user.id` |
| organization_id | `AppContext.selectedOrganization.id` (theme uses none) |
| configuration_type | namespace: `workspace-preferences`, `grid-view`, `theme` |
| configuration_key | part: the grid id for grid columns; none for the others |
| configuration_value | the envelope's `data` |
| updated_at | not stored. Browsers do not provide it in this store; add it if a backend store is approved |

## What is personal today

| Configuration | Namespace | Scope | Notes |
|---|---|---|---|
| Sidebar collapse, space order, collapsed spaces, pinned and hidden modules, navigation order, table density | `workspace-preferences` | user + organization | Existing keys preserved |
| Grid column visibility, order, and pinning | `grid-view` | user + organization + grid | Column widths and pinning are not yet configurable; see limits |
| Theme (light, dark, system) | `theme` | user | Signed-out visitors use the device choice under the earlier key |

## Persistence and its limits

- Only browser storage is available. The backend has no general user-preference endpoint; the only per-user endpoint is notification preferences, which carry fixed fields. No backend endpoint or schema was added.
- Browser storage is per browser and per device. It does not synchronize across devices, and clearing site data removes it.
- If storage is refused or full, the choice applies for the current session and the UI says it is not remembered (theme). Other settings fall back to defaults on the next load.
- Sign-out: the next user reads only their own keys. Theme falls back to the device choice when no one is signed in.

## Not built (needs separate approval or does not exist yet)

- Saved grid views: no saved-view feature exists in the frontend, and no backend endpoint exists. Not built.
- Dashboard layouts and widget settings: the dashboard is not rebuilt yet. The store supports a `dashboard` namespace, and a test shows its isolation, but no UI uses it.
- Grid filters, sorting, pagination: held in page state only, not persisted. Persisting them is a product decision.
- Column widths and pinning: no grid implementation exists yet to configure them.
- Organization and team defaults: not implemented. Future shared configuration needs an authorized administrative workflow, and personal values must stay independent.
- Backend persistence of any configuration: pending separate approval.

## Tests

`frontend/src/lib/personalPreferences.isolation.test.tsx` covers the requested behaviours:
1. Grid: user A hides a column; user B is unaffected.
2. Dashboard: a layout saved for user A is not read for user B (store level).
3. Spaces: user A collapses a space and reorders spaces; user B keeps defaults.
4. Theme: user A's theme does not change user B's.
5. Organizations: preferences in one organization are not visible in another.
6. Sign-in and sign-out: no preference from the previous user is shown; theme falls back to the device choice.
7. Organization switching: the grid re-reads the new organization's values.
8. Reset: removing user A's workspace preferences leaves user B's.
9. Unavailable storage: defaults on read, no throw on write, the theme choice applies for the session, and corrupted values fall back.
10. Existing behaviour: the device theme key is unchanged, and legacy workspace values still load.

Existing tests for workspace preferences, grid columns and theme continue to pass.

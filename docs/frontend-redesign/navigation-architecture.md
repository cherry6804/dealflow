# Navigation architecture (DFR-UI-001)

Status: implemented behind `VITE_DEALSFLO_NEW_SHELL`, which stays off by default. The existing layout is still the default.

## Layers

| Layer | Location | Responsibility |
|---|---|---|
| Space configuration | `layouts/workspace/spaces/spaceConfig.ts` | The six spaces, their tabs, routes and placeholders. Adding a space or tab is a change to this file only. |
| Personal layout model | `spaces/spacePreferences.ts` | Pure functions: normalize stored data, arrange spaces, reorder, pin, hide, mode and density. No storage, no React. |
| Personal storage | `spaces/useSpacePreferences.ts` over `lib/personalPreferences.ts` | Keys are `dealflow:workspace-spaces:<organization>:<user>`. Without a user, defaults apply and nothing is written. |
| Shell | `components/shell/AppShell.tsx` | Header, drawer, breadcrumbs, command palette. Accepts the custom sidebar and header actions through slots. |
| Spaces UI | `spaces/WorkspaceSidebar`, `SpaceLayout`, `SpaceFrame`, `SpacePlaceholder`, `SidebarCustomizer`, `SettingsMenu` | Sidebar, space bar and secondary navigation, placeholders, customization dialog, settings menu. |
| Wiring | `layouts/workspace/WorkspaceShellBridge.tsx` | Connects the session, notifications and the layers above. |

## Routing

- Existing routes are unchanged. A space tab opens its existing route (`/leads`, `/contacts`, and so on).
- The space is derived from the path (`resolveSpaceLocation`), so direct links, reloads and browser back/forward all show the correct space and tab.
- Placeholder tabs have routes under `/spaces/<space>/<tab>` and show a "not available yet" state. They show no data.
- Routes that no space lists stay reachable from the command palette (`UNLISTED_ROUTES`): Billing, Settings, governance and AI provider settings, Agents, Workflows, Automation history, Approvals, Lead intake. Nothing is removed.

## Spaces and tabs

| Space | Tabs (route) |
|---|---|
| Overview | Dashboard (`/`), Follow-ups (`/follow-ups`), My Day (placeholder), Trends (placeholder) |
| Sales | Contacts, Customers, Leads, Pipeline, Site Visits |
| Properties | Properties, Requirements |
| Deals | Deals, Commissions |
| Partners | Referrals |
| Operations | Activities (placeholder), Documents, Automation (`/automation-rules`), Imports |

Dashboard is the existing home page (`TodayPage`). The dashboard story will replace its content; this story adds no metrics.

## Personal sidebar

- Order, pinned spaces, hidden spaces, sidebar mode (expanded or icons only) and row spacing are personal.
- Pinned spaces are listed first, in their order. Hidden spaces are removed from the sidebar but stay in the customizer so they can be restored.
- Overview cannot be hidden. Pinning a hidden space shows it; hiding a pinned space unpins it.
- Reordering works by dragging (pointer or keyboard, via dnd-kit) and by Move up / Move down buttons, which are the non-drag alternative.
- Restore default arrangement removes only the current user's key for the current organization.
- Table density is also set in the customizer. It is read by the data grids and stored in the existing workspace preference store, per user and organization.

## Settings menu

- Notification settings: a link to the existing notification preferences page (`/notification-preferences`). No new notification settings are implemented.
- Appearance: the existing `ThemeToggle`, which stores the theme per signed-in user (see `personal-configuration.md`).

## Limits

- **Permissions:** the session has no per-user permission list, so no space or module is hidden for permissions. Route guards still enforce access. A permission hook is the place to add this once the backend exposes permissions.
- **Persistence:** browser storage only. It is per browser and device and does not sync across devices. Organization or team layouts are not implemented.
- **Translations:** labels are English, as in the existing layout.
- **Placeholders:** My Day, Trends and Activities have no backend or page yet.
- **Mobile:** on narrow screens the sidebar opens in the shell's drawer. The drawer closes on navigation.
- **Verification:** unit and component tests cover navigation, personal isolation, customization, settings and theme. Browser checks need an authenticated session with the flag on.

# Route migration tracker

Status key: NOT STARTED, IN PROGRESS, REDESIGNED (rebuilt, not yet verified), VERIFIED (rebuilt, tests, both themes, responsive and states checked). Old implementation is removed only after VERIFIED.

Current foundation: theme layer (dark and system) committed in `e308d0c`. Shell, shared components, grids, forms and dashboard customization: NOT STARTED.

| Route | Module | Status | Blocking dependency |
|---|---|---|---|
| / | Dashboard (Today) | NOT STARTED | Shell, KPI and widget components |
| /login | Auth | NOT STARTED | Redirects to SIBVO; not redesigned until the public experience phase |
| /signup | Auth | NOT STARTED | Public experience phase |
| /forgot-password | Auth | NOT STARTED | Public experience phase |
| /reset-password | Auth | NOT STARTED | Public experience phase |
| /verify-email | Auth | NOT STARTED | Public experience phase |
| /accept-invitation | Auth | NOT STARTED | Public experience phase |
| /access-required | Auth | NOT STARTED | Public experience phase |
| /sso/callback | Auth | NOT STARTED | Must keep working; visual change only |
| /onboarding | Onboarding | NOT STARTED | Shell |
| /pipeline | CRM | NOT STARTED | Kanban foundation |
| /deals | CRM | NOT STARTED | Grid foundation |
| /leads | CRM | NOT STARTED | Grid foundation |
| /lead-intake | CRM | NOT STARTED | Forms foundation |
| /contacts | CRM | NOT STARTED | Grid foundation |
| /customers | CRM | NOT STARTED | Grid foundation |
| /properties | CRM | NOT STARTED | Grid and card foundation |
| /requirements | CRM | NOT STARTED | Grid and forms foundation |
| /follow-ups | Operations | NOT STARTED | Grid foundation |
| /site-visits | Operations | NOT STARTED | Grid and calendar |
| /referrals | Operations | NOT STARTED | Grid foundation |
| /commissions | Operations | NOT STARTED | Grid foundation |
| /documents | Operations | NOT STARTED | Grid and upload |
| /imports | Operations | NOT STARTED | Upload and progress |
| /agents | AI | NOT STARTED | Grid and detail |
| /workflows | Automation | NOT STARTED | Grid and detail |
| /automation-rules | Automation | NOT STARTED | Grid and forms |
| /automation-history | Automation | NOT STARTED | Grid |
| /approvals | Automation | NOT STARTED | Human task grid |
| /notification-preferences | Settings | NOT STARTED | Forms foundation |
| /settings | Settings | NOT STARTED | Forms foundation |
| /settings/ai-providers | Settings | NOT STARTED | Forms and provider connections |
| /settings/governance | Settings | NOT STARTED | Forms and switches |
| /billing | Billing | NOT STARTED | Read-only views and entitlements |
| * | Not found | NOT STARTED | Shell |

Customization (dashboard builder, workspace customizer, grid views): NOT STARTED as a redesign. Existing device-only workspace preferences and grid view settings remain in local storage and must be labelled as device-only. Backend persistence: awaiting approval of `backend-customization-api-proposal.md`.

## Theme migration status

- Tone tokens: 32 of the most frequent hard-coded colours are now `var(--df-tone-*)` tokens. Each keeps its exact light value, so light mode is unchanged. Each has a dark counterpart in `frontend/src/styles/theme.css`. A literal is replaced only in a property of its own role (text, surface or border), so a text colour is never used as a background.
- Result: 552 declarations migrated across 28 stylesheets. About 2,650 colour literals remain (including `#fff` and `#ffffff`, which need a per-component decision). About 900 distinct six-digit values remain.
- Still to do: map the remaining values, handle `#fff`/`#ffffff` in context, and review each migrated screen in dark mode. Only public screens have been checked in a browser; the authenticated workspace has not.

## Shared component foundation

Status: built and tested, not yet used by production routes.

| Component | Module | Tests | Notes |
|---|---|---|---|
| Button (primary, secondary, tertiary, danger; loading; icon-only) | components/ui/Button.tsx | yes | Loading blocks clicks and sets aria-busy |
| TextField, TextareaField, SelectField | components/ui/Field.tsx | yes | helper and error linked with aria-describedby; aria-invalid on error |
| Checkbox (indeterminate), RadioGroup (arrow keys) | components/ui/Choice.tsx | yes | |
| Badge (tones) | components/ui/Badge.tsx | yes | label carries the meaning |
| Dialog (native dialog; closeLabel required) | components/ui/Overlays.tsx | yes | Focus returns to opener |
| Menu (keyboard, Escape, Home/End) | components/ui/Overlays.tsx | yes | |
| Popover (disclosure) | components/ui/Overlays.tsx | no | Escape closes; needs a dedicated test |
| Tooltip (focus and hover) | components/ui/Overlays.tsx | yes | Escape hides |
| Tabs (APG pattern) | components/ui/Navigation.tsx | yes | Disabled tabs skipped |
| Notification (alert or status by tone) | components/ui/Notification.tsx | yes | |
| Drawer | not built | | Dialog with placement "end" covers the first case |
| Search and command palette, shell header, sidebar, notification and profile menus | not built | | |

Styles: `components/ui/ui.css` uses existing tokens only. Control heights, focus ring and touch targets follow the design-system sheet. Font weight 550 for controls, 600 for section headings, 650 for page titles, so Inter must be loaded before these values render as intended.

Dev-only preview: `/design-system`, registered only when `import.meta.env.DEV` is true. The production bundle does not include it (checked). Preview text is English fixture text and is not translated; this is dev-only.

Browser checks (dev server, fixtures): the preview renders in light and dark themes. Dialog opens as modal, closes on its close control, and returns focus. Hover and keyboard focus are checked by interaction, not by forced state. No backend is running, so API calls made by the app shell return 502; this does not affect the preview.

Not verified: responsive behaviour at 390px and 768px; Escape handling for dialogs and tooltips in a real browser; axe (no axe package is installed).

## Application shell

Status: built and tested in the development preview at `/design-system/shell/*`. Production routes still render through the existing `WorkspaceLayout`. Replacing it is the next step, and only after the production wiring is tested.

| Requirement | Component or module | Tests | Browser check (dev preview, fixtures) |
|---|---|---|---|
| Global header | components/shell/AppShell.tsx | yes | desktop, tablet, 390px |
| Organization switcher (listbox, keyboard, retry) | components/shell/HeaderMenus.tsx | yes | select with arrow keys and Enter; list closes |
| Expandable and collapsible sidebar, rail on tablet | components/shell/Navigation.tsx, AppShell.tsx | yes | collapse and expand on desktop; rail forced at 768 to 1023px |
| Permission-aware navigation | components/shell/shellModel.ts, AppShell.tsx | yes | gated module hidden from nav and commands; route shows permission state |
| Navigation groups, customizable sections | Navigation.tsx, sidebarSections.ts (existing) | indirectly | space disclosure toggles |
| Active route and breadcrumbs | Navigation.tsx, shellModel.ts | yes | aria-current on the active link |
| Contextual page actions | PageHeader.tsx | no | preview only |
| Global search and command palette | CommandPalette.tsx | yes | Ctrl+K and "/" open it; focus moves to the field; Enter runs the command |
| Notifications menu (loading, empty, error, retry, mark read) | NotificationsMenu.tsx | yes | loading, error and retry observed; panel fits 390px |
| Profile menu (settings, sign out) | HeaderMenus.tsx | no | preview only |
| Responsive mobile navigation (drawer) | AppShell.tsx, Dialog placement end | yes | drawer opens at 390px; Escape closes and returns focus |
| Loading, empty, error, permission states | RouteStates.tsx | no | seen in preview routes |

Not done:
- Record search. The shell has no search API, so the palette searches only modules and commands. The existing navigation-only search in `WorkspaceLayout` is unchanged.
- Production wiring. Organization switching, sign-out, notifications and preferences still use the existing context and storage code. The shell takes them as props, so wiring is a container change.
- Permissions. The session exposes no per-user permission list. `PERMISSION_BY_MODULE` is empty, so nothing is gated in production. The preview gates one module with a fixture permission.
- Preview fixtures. The preview uses fixture organizations and notifications. Text is English and not translated; it is dev-only.
- Not verified: keyboard tab order across the full header, reduced-motion behaviour in a browser, and an accessibility scan (no axe package installed).
- Console: duplicate-key warnings from the preview's command list were fixed. The remaining 502 responses come from the app's API calls, which have no backend in this environment.

## Phase 1: production shell integration

Status: integrated behind a build flag. Off by default, so production keeps the existing `WorkspaceLayout`.

- Switch: `VITE_DEALSFLO_NEW_SHELL=true` selects `WorkspaceShellBridge`. Both layouts render `<Outlet />`, so routes do not change.
- Data sources are the existing ones: `AppContext` for the user, organizations, organization switching and sign-out; the stored workspace preferences keyed by organization and user; and `notificationApi` for the list, unread count, mark read and mark all read.
- Notification routing moved to `components/notificationRoutes.ts`, shared by the existing bell and the new menu, so opening a notification routes to the same resource.
- The unread badge loads on mount, as the existing bell does. Mark read and mark all read update it.
- Customization: the existing workspace customizer is reachable from the command palette ("Customise navigation"), and the sidebar collapse and space disclosures persist as before.
- Permissions: `AppContext` exposes no permission list, so the shell hides nothing. Route guards and feature access checks are unchanged.
- Labels: the existing layout has no translation layer, so the shell's English labels match its wording (`workspaceShellLabels.ts`).

Not verified:
- Authenticated browser check. Production routes require a SIBVO session, which is not available here. The shell has been tested with unit tests against a mocked `AppContext` and mocked notification API, not end to end.
- Old page styling inside the new shell. Pages are unchanged, but the new shell does not reproduce the old `.workspace-*` layout classes. Each route needs a visual check with the flag on.
- Bundle size. The shell code is in the production bundle (behind the flag), so the build is larger.

## Phase 2: dashboard data gap report

Available from `GET /dashboard/summary` (already used by the Today page):
- Deals: counts by stage and open value by currency.
- Follow-ups: overdue, today and upcoming counts with items.
- Lead actions: overdue and today counts with items.
- Access flags per section, which the dashboard must use for permission states.

Available from list endpoints, which return totals and can supply counts:
- Site visits, properties, activities, leads, notifications.
- Agent metrics per agent (`/agents/{id}/metrics`) and agent executions per agent.
- Human tasks.

Not available as an aggregate. Each requires an API before the dashboard can show it without inventing values:
- Revenue: won or closed revenue, revenue trend and forecast. The summary has open value only.
- Conversion metrics, and lead performance by source or stage.
- Team performance (per member activity or targets).
- AI insights (a cross-agent summary). Metrics exist per agent only.
- Property inventory aggregates by status or availability.
- Activity aggregates over time.

Phase 2 is not started. The dashboard should use the summary endpoint plus list totals first, and show the gaps above as explicit "not yet available" states.

## Design system: single token source

Status: established. Module migration is progressive; see `design-system.md`.
- Tokens: `styles/tokens.css` (light, on `:root`) and `styles/theme.css` (dark). Shell geometry and motion timing now live in `tokens.css`.
- Contract tests (`styles/designTokens.test.ts`): new components reference only defined tokens; every colour token has a dark value; theme.css defines no undeclared token. The test environment now processes CSS so raw stylesheet imports can be read.
- Legacy: about 2,650 literal colours remain in legacy stylesheets. They are removed module by module as each module migrates.

## Personal configuration

Status: store and isolation tests in place. Details and limits: `personal-configuration.md`.
- Workspace preferences, grid columns and theme are personal (per user; organization where relevant).
- Not built: saved grid views, dashboard layouts, persisted filters, column widths and pinning, shared organization or team defaults. Each needs a product decision or separate backend approval.


## DFR-UI-001: redesigned shell and personal navigation

Status: implemented behind `VITE_DEALSFLO_NEW_SHELL` (off by default). Architecture: `navigation-architecture.md`.

| Acceptance area | Status |
|---|---|
| Common header (brand, organization, search, notifications, Customize, Settings, profile) | Implemented |
| Six spaces in the sidebar, with correct tabs | Implemented; placeholders for My Day, Trends and Activities |
| Tabs open existing routes; direct links and back/forward | Implemented, covered by tests |
| Reorder (drag and move buttons), pin, hide, restore | Implemented, covered by tests |
| Sidebar mode (expanded or icons only) and row spacing | Implemented |
| Personal isolation per user and organization | Implemented, covered by tests |
| Settings: notification settings and appearance | Implemented by reusing existing page and theme control |
| Light, dark and system themes | Shell components use tokens; browser check pending |
| Responsive and keyboard | Drawer on narrow screens; focus handling tested; browser check pending |
| Authenticated browser verification and screenshots | Pending: needs the flag on and a signed-in session |
| Permission-based visibility | Not implemented: no per-user permission list in the session |

## Sales workspace (DFR-UI-SALES-001)

Status: shared grid foundation and the Contacts pilot are built and tested. Browser verification of the pilot needs the dev server restarted with `VITE_DEALSFLO_SALES_CONTACTS=true`, which is not yet confirmed. The legacy pages remain the default.

| Page | Route | State | Feature flag | Notes |
|---|---|---|---|---|
| Shared grid | components/grid | Built, tested | none | EnterpriseDataGrid on react-data-grid. Search, personal column panel (show, order, pin, density, restore), resizing, sorting, states, footer with count and create action. |
| Contacts | /contacts | Pilot built, tested; not yet browser-verified | VITE_DEALSFLO_SALES_CONTACTS | Uses contactsApi list, create and update. Detail dialog with editable fields and status toggle. Owner and linked records are not in the contact contract, so they are not shown. |
| Leads | /leads | Not started | — | Legacy page. |
| Customers | /customers | Not started | — | Legacy page. |
| Site Visits | /site-visits | Not started | — | Legacy page. |
| Pipeline | /pipeline | Not started | — | Legacy page. Uses existing lead data per the approved plan. |

Gaps:
- Selection and bulk actions are not in the grid yet.
- Client-side paging: all contacts are loaded, as the legacy page does. Server-side paging is not used.
- Column widths are personal; pinning and reordering are personal too. Browser localStorage is device-specific and is not cross-device sync.
- The contact record detail has no comments or activity history; the contact API does not expose them.

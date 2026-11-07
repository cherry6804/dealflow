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

## Sales workspace (DFR-UI-SALES-001, corrected in DFR-UI-SALES-003)

Status: Contacts, Customers, Leads and Site Visits run on the shared EnterpriseDataGrid behind their own flags. Pipeline is a Kanban board only, behind its flag. Each flag is set in `.env.local` (git-ignored) and read at dev-server start, so restart the frontend after changing it. Legacy pages stay the default when a flag is off. Browser verification used the development database. Live write checks ran on the dev database on 2026-11-07 with QA records named "QA LiveCheck": contact created; customer registered and notes saved; lead created, stage changed to Contacted, interest set to High; board move to Qualified (persisted after reload); site visit scheduled and attendance recorded as Completed. One attendance was recorded by mistake on a pre-existing visit (Cherry Appala, 2026-11-08 10:00): status is now Completed with outcome Interested and feedback text; the API cannot return it to Scheduled. Feedback and outcome on that visit still need clearing if approved.

| Page | Route | State | Feature flag | Notes |
|---|---|---|---|---|
| Shared grid | components/grid | Built, tested, browser-verified | none | Toolbar: search, optional Filter, Columns. Filter builder is an anchored popover with add and remove, operators per field type, Apply and Clear. Active filters show as removable chips and a count on the Filter button. Filter conditions and column layout are saved per user, organization and grid. Table holds business columns only. Header and footer use the soft surface; body uses the main surface. |
| Contacts | /contacts | Built, tested, browser-verified | VITE_DEALSFLO_SALES_CONTACTS | Filters: name, email, phone, status, created. |
| Customers | /customers | Built, tested, browser-verified | VITE_DEALSFLO_SALES_CUSTOMERS | Lists all customer profiles; status is a filter, not a default. Filters: customer, email, phone, status, notes, registered. Customer type and owner are not in the customer-profile contract, so not shown. |
| Leads | /leads | Built, tested, browser-verified | VITE_DEALSFLO_SALES_LEADS | Record dialog is shared with Pipeline (LeadDetailDialog). Stage rules, next-action prompt, interest, activation, timeline and follow-up actions keep their endpoints. Filters: lead, email, phone, stage, interest, owner (when the team list resolves names), next follow-up, created. Source is not in the lead contract. |
| Pipeline | /pipeline | Built, tested, browser-verified | VITE_DEALSFLO_SALES_PIPELINE | Kanban only; no list or board toggle. One column per stage (`pipeline/pipeline-stages.ts`), cards open the lead record. Stage select on each card and drag-and-drop both use the existing transition table; a move that needs a next action opens the record at that step. Filters: lead, email, phone, interest, owner, next follow-up, created, lead activity. Expected value and closing date are not in the lead contract. Board scrolls horizontally on narrow screens. |
| Site Visits | /site-visits | Built, tested, browser-verified | VITE_DEALSFLO_SALES_SITE_VISITS | Columns: visit date and time, property, lead or customer, assigned agent, status, outcome, follow-up, notes, last updated. Schedule, attendance (status, outcome, feedback), follow-up from a visit, and history use the existing endpoints. The visit contract has no reference number and no reschedule endpoint, so neither is shown or offered. |
| Space header | layouts/workspace/spaces | Built, browser-verified | none | Jira-style continuous header: icon and title, tabs below, white, no card or border, one divider under the tabs. Active tab uses the blue underline. |

Gaps:
- Selection and bulk actions in the grid are not built. Bulk follow-up actions live in the follow-up dialog.
- Column reordering uses Up and Down buttons, not drag-and-drop. Hover column menus are not built.
- Paging: all records load and are filtered in the browser. Server paging is not used.
- Visit rescheduling is not available: no reschedule endpoint exists. Changing a visit's time needs a backend change.
- Filter preferences are saved in browser localStorage (per device); they are not synced.
- Dark theme was checked by applying the dark token set on the page for Pipeline; Light and dark were not checked on every page.
- Zoom (80 to 200 percent) was not checked.
- Pipeline's legacy board stays behind the flag-off path until the flag is enabled everywhere.

## Shared record dialog (DFR-UI-DIALOG-001)

Status: one dialog primitive (`components/ui/Overlays.tsx`, `Dialog`) and one record layout (`components/record/RecordDialog.tsx`, `RecordDialog`, which replaced `RecordDetailDialog`). Used by Contacts, Customers, Leads (and Pipeline cards, through the lead record), and Site Visits. Create dialogs for Contacts, Customers, Site Visits (schedule, attendance, follow-up) use the same primitive. Properties, Requirements, Deals, Commissions, Referrals and Follow-ups still use their own pages and dialogs; they are not migrated.

Behaviour in `Dialog`:
- Header (type, title, status, actions, close) and footer stay fixed; only the body scrolls.
- Backdrop click closes only when the press also started on the backdrop. Clicks inside the dialog or in its nested popovers never close it.
- Escape is handled on keydown. Browsers only send Escape to the cancel handler while the page has user activation, so relying on cancel alone let the dialog close without the unsaved-change check. Found and fixed in the live check.
- Unsaved changes: any dismissal asks "Discard unsaved changes?" with Keep editing and Discard changes. The prompt closes natively before it unmounts.
- Busy: close, Escape and backdrop are ignored while a request runs; the close control is disabled.
- Focus returns to the element that opened the dialog.
- Phones (< 768px): full-screen, with safe-area padding and 44px footer buttons.
- Save and create actions sit in the footer and submit their form by id; read-only records have no Save.

Verification (2026-11-07, dev database):
- Contact detail: backdrop closes (no edit), Escape with an edit asks first, Keep editing keeps the record and the edit, Discard closes, nothing saved, focus returns to the row.
- Lead detail: Manage follow-ups opens a nested dialog; its backdrop closes only the nested one.
- Widths measured with no page overflow at 360, 390, 430, 768, 1024, 1280, 1366, 1440, 1920.
- Light and dark themes checked on the lead dialog (desktop).
- Screenshots: desktop lead and contact dialogs, phone contact and site-visit dialogs.

Accidental data change during this check (undone): a stray click set the dev lead for Charan Appala to inactive. It was reactivated the same session; the grid shows it active again.

Limitations:
- Browser zoom (80%, 100%, 125%, 150%, 200%) was not tested. The browser tool cannot change zoom; viewport widths were tested instead.
- Sticky Sales header was added (`position: sticky`) but not checked with a scrolling page; the current pages are short.
- Busy-state blocking and the double-submit guard are covered by unit tests only.
- Other business modules listed in the brief still use their own dialogs.

## Space header integration (DFR-UI-SHELL-FIX-001)

The space chrome (title row and tab bar) is part of the shell content. It cancels the shell's page padding, so it sits directly under the global header, runs edge to edge, and has no card, border, radius or shadow. One divider runs full width beneath the tabs. Page content starts 20px below the divider. The chrome is sticky at the top of the scrolling main area, with its threshold set to the page padding so it does not drift below the global header. The shell's mobile override of the page padding was removed, so the shell and the space header use the same tokens. Checked in the running app for Sales (all five tabs), Properties, Deals, Partners and Operations, in light and dark themes at desktop, tablet and phone widths. Tabs scroll horizontally on phones and fit on tablets; no page overflow was seen.

## Enterprise grids: Properties, Requirements, Deals, Referrals (DFR-UI-GRID-STANDARDIZE-001)

| Module | Route | State | Flag | Notes |
|---|---|---|---|---|
| Properties | /properties | Built, tested, grid browser-verified | VITE_DEALSFLO_PROPERTIES | Columns: property (title and address), transaction, type (hidden by default), location, price or rent, availability badge, listed, last updated (hidden). Filters: transaction, availability, type, city, locality, listed. Record dialog: details, availability change, visit history. Add property uses the existing create sequence and its partial-failure message; the form validates before any request. Owner is not in the property record, so no owner column. |
| Referrals | /referrals | Built, tested, grid browser-verified (created one QA record and edited its phone) | VITE_DEALSFLO_REFERRALS | Columns: referral (name and contact), referrer, customer, related deal stage, status badge, referral date, last updated (hidden). Filters: status, referral, referrer, customer, referral date. One record dialog creates and edits the same fields; deactivation stays behind a confirmation. Commission and referral value are not in the referral record, so no value column. |
| Requirements | /requirements | Built, tested, grid browser-verified (created one QA requirement: budget, customer assignment, preferred location) | VITE_DEALSFLO_REQUIREMENTS | Grid: customer requirement (customer name and contact), transaction, budget range, status badge, created, last updated (hidden). Filters: status, transaction, customer, email, created. Record dialog: budget, lead or customer assignment, preferred locations, property preferences, possession and parking, shortlist, and the shared matching panel. Each section saves on its own, as before. Locations, preferences and matches are sub-records and appear in the record, not the grid. |
| Deals | /deals | Built, tested, grid browser-verified (opened the existing deal record; writes not run live) | VITE_DEALSFLO_DEALS | Grid: deal (customer and property), stage badge, expected value, assigned agent, created (last updated hidden). Filters: stage, customer, property, agent, created. Record dialog: deal details (lead, expected value, currency, notes), stage advance, closing as won or lost with a reason, negotiation (start, state change with note and reason rules, history), and the existing payment milestones and commissions panels. No deal name, reference or expected closing date in the API, so none are shown. |

Gaps and limits:
- Requirements and Deals are not migrated yet; their legacy pages remain the default.
- Owner (properties) and commission or referral value (referrals) are not in the API records, so they are not shown.
- Browser zoom (80–200%) was not tested for these pages.
- Column layout and filters are personal per user and organization, as on the other grids.

## Requirements grid (DFR-UI-GRID-REQUIREMENTS-001)

Requirements now uses the shared grid and a single record dialog. The dialog's sections keep the legacy page's separate saves and validation rules (budget range, BHK, parking spaces). Matching uses the existing RequirementMatchPanel. Not yet checked: light theme, zoom levels, and the possession/parking and property-preference sections in the browser (the QA check covered budget, customer assignment and preferred location). Requirement reference numbers are not in the API, so the grid shows the customer name instead.

## Deals grid (DFR-UI-GRID-DEALS-001)

Deals uses the shared grid and one record dialog. The legacy stage, closing, negotiation and field rules are kept, and the existing payment milestones and commissions panels open from the record. Not yet checked: a live create (needs an available property), a live stage or negotiation change, light theme, and zoom levels.

## Overlay system audit and shared primitives (DFR-UI-OVERLAYS-001)

Audit: one native dialog primitive (`Dialog`, components/ui/Overlays.tsx) with focus, Escape, backdrop and unsaved-change rules; `RecordDialog` on top of it for records; `AnchoredPopover` for portal popovers; `Menu` and `Popover` in Overlays for contextual menus. About 14 portal-based components remain outside this system (legacy pages and panels).

Added: `ConfirmationDialog` (small, danger or default confirm, Cancel/Escape/backdrop leave the action undone) and `AppDrawer` (end-placed `Dialog` for configuration panels). Added `size="sm"` to `Dialog`; small dialogs stay compact on phones.

Migrated to ConfirmationDialog: customer deactivation and reactivation (Customers), referral deactivation (Referrals record). Verified in the running app on a QA customer: Escape cancels only the confirmation; deactivate and reactivate both worked and the record was restored to Active.

Outstanding:
- Native `window.confirm` still used in legacy-shared panels and pages: DealCommissionsPanel, PaymentMilestonesPanel, OrganizationRolesPanel, TeamAccessPage, AutomationRulesPage, ImportsPage, legacy ReferralsPage, legacy CustomersPage. These need the same ConfirmationDialog.
- Record dialogs are not yet split into separate RecordDialogHeader/Content/Sidebar/Footer components; RecordDialog renders them together.
- Per-entity record layouts beyond the current sections (Contacts, Customers, Leads, Site Visits) are not redesigned.
- Settings and configuration: not standardized in this pass (SettingsMenu, SidebarCustomizer, ProfileMenu, notification preferences).
- Browser zoom (80–200%) and the full width matrix were not re-run for this pass.

## Application-wide audit (DFR-UI-AUDIT-001, Phase 1)

The route audit matrix is in `route-audit-matrix.md`. It lists every route in the router with its implementation, flag, grid and overlay use, inconsistencies, status and migration work. It is based on code inspection and counts; the Operations and Overview screens were not audited in depth, and responsive and zoom checks are listed as gaps per screen.

Phases: 1 audit (done). 2 shared system: nested-section components, the 8 native confirms, motion tokens, settings drawers. 3 business modules: commissions, property and customer related sections, lead history, site-visit feedback. 4 Operations: documents first, then automation, imports, agents, lead intake, workflows, approvals. 5 full QA across routes, widths, zoom, themes and accessibility.


## Native confirm replacement (DFR-UI-CONFIRM-001)

All eight native `window.confirm` calls now use `useConfirmation` (components/ui/useConfirmation.tsx), which shows the shared `ConfirmationDialog` and resolves a promise, so each handler keeps its existing flow. Sites: DealCommissionsPanel (agree, mark paid, cancel), PaymentMilestonesPanel (cancel), OrganizationRolesPanel (deactivate role), TeamAccessPage (revoke invitation), AutomationRulesPage (activate or disable rule), ImportsPage (process import), legacy ReferralsPage (deactivate), legacy CustomersPage (deactivate or reactivate). Destructive actions use the danger tone; the import confirmation names the number of rows.

Escape handling in DealCommissionsPanel and PaymentMilestonesPanel now ignores a keydown that a nested confirmation already handled (`defaultPrevented`), so Escape cancels only the confirmation.

Verification: typecheck, lint and the full unit suite (366 tests) pass. Browser checks were not run for these eight sites: the legacy CustomersPage and ReferralsPage only render with their flags off, and the commissions and milestones panels need a deal with records. The Customers workspace (flag on) was checked in an earlier pass.

## Nested dialogs and deal payment/commission workflows (DFR-UI-NESTED-001)

**Root cause.** The payment milestones and commissions panels were portalled to `document.body`. The deal record is a native `<dialog>` shown with showModal, which sits in the top layer, so the panels rendered beneath it: covered and inert. The same defect affected `LeadTimeline` (opened from the lead record).

**Fix (shared primitive).** `Dialog` now (a) reference-counts a document scroll lock, so page scrolling stays locked until the last open dialog closes; and (b) when an open dialog unmounts, closes itself, releases the lock and returns focus to the control that opened it. Nested dialogs use the native top layer, so a child always stacks above its parent. Escape is handled on keydown and skipped when a child has already handled it, so Escape closes only the topmost dialog. Backdrop clicks are scoped to the dialog that owns the backdrop.

**Payment milestones.** Lists milestones with amount, due date, paid date, reference and status (Pending, Overdue from the API's `is_overdue` flag, Paid, Cancelled). The API has no partially-paid state, so none is shown. Create and edit use a nested form dialog, with the dirty prompt on close. Record payment is its own nested step with an optional reference. Cancel asks for confirmation. Every change reloads the list and tells the parent deal.

**Commissions.** Lists commissions by type (percentage or fixed), rate or basis, currency, status, agreed and paid dates, and reference. Amounts come from the API's `calculated_amount`. The client-side "estimated commission" figure was removed, and the form now says the server calculates the amount. Totals are grouped by currency, and a commission with no calculated amount is reported, not counted as zero. Agree and cancel confirm first. Record payment is a nested step. Every change refreshes the deal.

**Not supported by the backend, so not built.** Assigned beneficiary or recipient on a commission (the model has no such field); partially-paid milestone states; any commission or milestone field outside the schemas in `backend/app/*/schemas.py`.

**Duplicate submissions.** Each mutating handler is guarded by a ref, so a second click in the same frame cannot start a second request. Buttons are disabled and show progress while a request runs, and the dialog cannot be dismissed mid-request.

**Nested overlay audit.**

| Surface | Overlay | Result |
|---|---|---|
| Deal record | Payment milestones, commissions (and their forms, record-payment and confirm steps) | Fixed: nested `Dialog` |
| Lead record | Lead activity timeline | Fixed: nested `Dialog`; own Escape and scroll handling removed |
| Lead record | Follow-ups | Already a nested `Dialog` |
| Site visits, referrals, customers, properties, requirements | Record dialogs and forms | Already `Dialog` / `RecordDialog`; no portal |
| Grids (all pages) | Column and filter popovers (`AnchoredPopover`) | Not nested in dialogs; a grid is never placed inside a dialog |
| Header | Notifications (`NotificationBell`) | Top-level; not nested |
| Legacy pages behind flags (Deals, Leads, Contacts, Customers, Properties, Requirements, Referrals, Site visits, Automation rules) | Hand-built portal overlays | Not changed. They render only with their flags off and never inside a dialog. Migrate with their pages |
| Documents (legacy) | Not audited in this pass | Phase 4 |

**Verification.** Typecheck, lint (exit 0) and production build pass. 396 unit tests pass, including new tests for nested dismissal, focus return, the scroll lock, validation, currency totals and both panels' workflows against a mocked API.

Browser check (dev database, 746px pane and 1440px desktop, 360px phone emulation). A QA-named deal was used. Created a QA milestone and a QA commission, and edited the milestone name. Verified: nested form stacks above the milestones dialog; the unsaved-change prompt appears on top of the form; Escape closes only the innermost step with focus returned; backdrop click closes only the commissions dialog and the deal stays open; the cancel confirmation dismisses without cancelling; the server-calculated commission (2% of ₹25,00,000 = ₹50,000.00) displays. Phone layout at 360px is full-screen with two-column summary tiles.

Not done in the browser: recording a payment or agreeing a commission on the dev data. Both change financial status, and a paid or agreed record cannot be reverted through the API. They are covered by the unit tests. The QA milestone and commission remain on the dev deal as Pending and Proposed.

Not yet verified: widths 320, 390–430, 768, 1024, 1920; browser zoom; light theme; keyboard-only pass on each nested step.

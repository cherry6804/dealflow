# Route and component audit matrix (Phase 1)

Status key: **Migrated** = on the shared system behind a flag, legacy kept as fallback. **Legacy** = not yet migrated. **Placeholder** = route shows a not-yet-available state. "Static" = checked in code only, not in the browser at every width.

Counts come from the code: `grid` = EnterpriseDataGrid or DataGrid usages, `confirm` = native `window.confirm` calls, `portal` = `createPortal` usages (hand-built overlays).

## Workspace and navigation

| Route / screen | Implementation | Flag | Shared pieces used | Inconsistencies found | Status |
|---|---|---|---|---|---|
| Global header (`AppShell`, `HeaderMenus`, `NotificationsMenu`) | `components/shell/AppShell.tsx` | VITE_DEALSFLO_NEW_SHELL | Menu, Popover (Overlays), Dialog for account panel | Account panel is a dialog; org switcher is a listbox. Both verified earlier. | Migrated (shell), Static for zoom/themes |
| Space chrome (title, tabs) for all spaces | `layouts/workspace/spaces/SpaceLayout.tsx`, `spaces.css` | none | — | Earlier fix made it flush and sticky. Tabs scroll on phones. Not checked at every zoom level. | Migrated |
| Sidebar and space navigation | `WorkspaceSidebar.tsx`, `SidebarCustomizer.tsx` (dnd-kit), `SettingsMenu.tsx` | none | Dialog (settings) | Customizer is inline in the sidebar footer, not a drawer. Settings menu opens a dialog. | Legacy-style, needs settings pass |
| Overview (Today dashboard) | `pages/TodayPage.tsx` (729 lines) | none | — | Not audited in depth; 0 grids, no shared empty/loading components confirmed. Charts not reviewed. | Legacy, Static |
| Follow-ups | `pages/FollowUpsPage.tsx` (386 lines) | none | — | 0 grids, no portal. Uses its own list layout. Bulk actions not reviewed. | Legacy |

## Sales

| Route | Implementation | Flag | Grid | Record UI | Status |
|---|---|---|---|---|---|
| /contacts | `pages/sales/ContactsWorkspacePage.tsx` (reference) | VITE_DEALSFLO_SALES_CONTACTS | EnterpriseDataGrid | RecordDialog, footer save, Dialog create | Migrated (reference) |
| /customers | `pages/sales/CustomersWorkspacePage.tsx` | VITE_DEALSFLO_SALES_CUSTOMERS | EnterpriseDataGrid | RecordDialog, ConfirmationDialog for status | Migrated. Related-properties, requirements and deals sections not yet shown |
| /leads | `pages/sales/LeadsWorkspacePage.tsx` + `leads/LeadDetailDialog.tsx`, `leads/LeadFollowUpsDialog.tsx` | VITE_DEALSFLO_SALES_LEADS | EnterpriseDataGrid | RecordDialog, nested follow-ups dialog, LeadTimeline (own modal) | Migrated. Qualification history, property matches, conversion history not shown |
| /pipeline | `pages/sales/PipelineWorkspacePage.tsx` (Kanban) | VITE_DEALSFLO_SALES_PIPELINE | Board (not a grid, by design) | Reuses LeadDetailDialog. Legacy PipelinePage kept as fallback. | Migrated (board) |
| /site-visits | `pages/sales/SiteVisitsWorkspacePage.tsx` + `site-visits/SiteVisitForms.tsx` | VITE_DEALSFLO_SALES_SITE_VISITS | EnterpriseDataGrid | RecordDialog, Dialog forms with footer actions, SiteVisitHistory | Migrated. Visit timeline / feedback history not structured yet |

## Properties space

| Route | Implementation | Flag | Grid | Record UI | Status |
|---|---|---|---|---|---|
| /properties | `pages/properties/PropertiesWorkspacePage.tsx` + `PropertyCreateDialog.tsx` | VITE_DEALSFLO_PROPERTIES | EnterpriseDataGrid | RecordDialog (read-only + availability), create via RecordDialog-style Dialog | Migrated. Specifications, ownership (not in API), related requirements/deals not shown |
| /requirements | `pages/requirements/RequirementsWorkspacePage.tsx` + `RequirementRecordDialog.tsx` | VITE_DEALSFLO_REQUIREMENTS | EnterpriseDataGrid | RecordDialog with sections (budget, assignment, locations, preferences, possession, shortlist) and RequirementMatchPanel | Migrated. Sections are inline forms, not the shared nested-section components |

## Deals and commissions

| Route | Implementation | Flag | Grid | Record UI | Status |
|---|---|---|---|---|---|
| /deals | `pages/deals/DealsWorkspacePage.tsx` + `DealRecordDialog.tsx`, `DealCreateDialog.tsx` | VITE_DEALSFLO_DEALS | EnterpriseDataGrid | RecordDialog with stage, closing, negotiation sections; PaymentMilestonesPanel and DealCommissionsPanel open as their own overlays | Migrated. Payment milestones and commissions are nested `Dialog`s (DFR-UI-NESTED-001); they no longer portal under the record |
| /commissions | `ModulePlaceholder` in `AppRouter.tsx` (title and description only, no data) | none | — | — | **Placeholder**: shows a description but no records. Commission records exist only inside deals (DealCommissionsPanel) |

## Partners

| Route | Implementation | Flag | Grid | Record UI | Status |
|---|---|---|---|---|---|
| /referrals | `pages/referrals/ReferralsWorkspacePage.tsx` + `ReferralRecordDialog.tsx` | VITE_DEALSFLO_REFERRALS | EnterpriseDataGrid | RecordDialog with ConfirmationDialog for deactivation | Migrated. Referral history and commission details not shown |

## Operations space

| Route | Implementation | Flag | Grid | Record UI | confirm | portal | Status |
|---|---|---|---|---|---|---|---|
| /spaces/operations/activities | `SpacePlaceholderRoute` | none | — | — | — | — | Placeholder (labelled "Not yet available") |
| /documents | `pages/DocumentsPage.tsx` (1223 lines) | none | 0 (own table/list) | own | 0 | 0 | **Legacy, highest priority**: not on the grid system; no shared empty or loading states confirmed |
| /automation-rules | `pages/AutomationRulesPage.tsx` (1183 lines) | none | 0 | own | 1 | 2 | Legacy; confirm migrated to ConfirmationDialog; own overlays |
| /automation-history | `pages/AutomationExecutionHistoryPage.tsx` | none | not counted | — | — | — | Legacy; not audited in depth in this pass |
| /imports | `pages/ImportsPage.tsx` (957 lines) | none | 0 | own | 1 | 0 | Legacy; confirm migrated to ConfirmationDialog |
| /agents | `pages/AgentsPage.tsx` (673 lines) | none | 0 | own | 0 | 0 | Legacy |
| /lead-intake | `pages/LeadIntakePage.tsx` (438 lines) | none | 0 | own | 0 | 0 | Legacy |
| /workflows | `pages/WorkflowsPage.tsx` (860 lines) | none | 0 | own (canvas) | 0 | 0 | Legacy; canvas editor, not audited in depth |
| /approvals | `pages/ApprovalsPage.tsx` (246 lines) | none | 0 | own | 0 | 0 | Legacy |

## Account, settings and organization

| Route | Implementation | Grid | confirm | portal | Status |
|---|---|---|---|---|---|
| /settings | `features/settings/pages/TeamAccessPage.tsx` (637 lines) | 0 | 1 | 0 | Legacy; confirm migrated to ConfirmationDialog |
| /settings/governance | `features/governance/pages/GovernancePage.tsx` (99 lines) | 0 | 0 | 0 | Legacy |
| /settings/ai-providers | `features/ai-providers/AiProvidersPage.tsx` (298 lines) | 0 | 0 | 0 | Legacy |
| /notification-preferences | `pages/NotificationPreferencesPage.tsx` (354 lines) | 0 | 0 | 0 | Legacy; personal preference, not yet on the personal-preference hook |
| /billing | `features/billing/pages/BillingAccessPage.tsx` (161 lines) | 0 | 0 | 0 | Legacy |
| /onboarding | `features/onboarding/pages/OnboardingPage.tsx` (253 lines) | 0 | 0 | 0 | Legacy |
| Account panel (header) | `HeaderMenus.tsx` ProfileMenu | — | — | — | Migrated (role=dialog panel) |
| Auth pages (sign-in redirect, sign-up, verify, reset, invitation, access required) | `features/auth/pages/*` | — | — | — | Out of scope for the workspace redesign; Static only |

## Shared components: duplicates and consolidation candidates

- **Overlays:** `Dialog` (native, the shared primitive), `RecordDialog` (records), `ConfirmationDialog`, `AppDrawer` (new), `AnchoredPopover` (portal popover), `Menu`/`Popover` (Overlays). About 14 files still build their own portal overlays. Largest: `LeadsPage` (6), `DealsPage` (7), `CustomersPage` (6), `ContactsPage` (5), `SiteVisitsPage` (5).
- **Grids:** `EnterpriseDataGrid` is the target. Legacy pages still use `DataGrid` directly (Contacts, Customers, Leads, Properties, Requirements, Deals, Referrals, SiteVisits legacy versions). These are fallbacks behind flags.
- **Confirmations (done, DFR-UI-CONFIRM-001):** all 8 former `window.confirm` sites now use ConfirmationDialog. Former list: DealCommissionsPanel (3), PaymentMilestonesPanel (1), OrganizationRolesPanel (1), TeamAccessPage (1), AutomationRulesPage (1), ImportsPage (1), legacy ReferralsPage (1), legacy CustomersPage (1). All should move to `ConfirmationDialog`.
- **Nested sections:** Requirement sections, Deal sections and Lead follow-ups are each implemented inline. The brief's shared components (`RelatedRecordSection`, `ActivityTimeline`, `HistoryTimeline`, `FollowUpSection`, `PaymentMilestoneSection`, `CommissionSection`, `VisitHistorySection`, `DocumentSection`, `NotesSection`, `RelatedItemsTable`, `RecordSummaryPanel`) do not exist yet.
- **Motion:** no shared motion tokens beyond the page-enter fade and the sidebar/search transitions. Reduced-motion is respected by the fade and the spinner only.

## Gaps by category (all screens)

- **Responsive:** verified at 360, 390, 746 (pane), and desktop widths for the migrated Sales, Properties, Requirements, Deals and Referrals pages. Not verified at 430, 768, 1024, 1366, 1440, 1920, or any zoom level for any screen.
- **Accessibility:** keyboard and dialog behaviour verified for the shared Dialog and migrated record dialogs. No axe scan has been run across the application. Contrast of status badges not measured.
- **Themes:** dark theme checked on several migrated pages. Light theme checked for Sales header and Contacts only. System theme not verified.

## Phase plan (proposed)

1. **Phase 1 (this document):** route inventory and matrix. Done.
2. **Phase 2 (shared system):** nested-section components (RelatedRecordSection, ActivityTimeline, HistoryTimeline, FollowUpSection, PaymentMilestoneSection, CommissionSection, VisitHistorySection, NotesSection, RelatedItemsTable, RecordSummaryPanel); migrate the 8 `window.confirm` calls to ConfirmationDialog; motion tokens with reduced-motion; settings drawers.
3. **Phase 3 (business modules):** Commissions, Partners detail, Property and Customer related sections, Lead qualification and conversion history, Site Visit feedback and history.
4. **Phase 4 (Operations):** Documents (highest priority), Automation rules and history, Imports, Agents, Lead intake, Workflows, Approvals. Each moves to the grid and RecordDialog system, keeping existing functionality.
5. **Phase 5 (QA):** every route at 9 widths and 5 zoom levels, light/dark/system, axe scan, keyboard pass.

Each phase is large. Phase 2 should be done before Phase 4, because Operations needs the shared sections and confirmations.

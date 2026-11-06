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

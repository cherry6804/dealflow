# Frontend audit and architecture decision

Branch: `feature/dealsflo-complete-frontend-redesign`, from `origin/develop` at `f81865a`.

## 1. Existing frontend, measured

- Source: `frontend/src`. Vite, React 19, React Router 7, TypeScript.
- Build: `npm run build` passes. Tests: 163 passing in 25 files (`vitest run`). Lint (`oxlint`): exit 0 with warnings, which are recorded as the starting point.
- Routes: 35 path entries. Public: login, signup, forgot and reset password, verify email, accept invitation, access required, SSO callback, onboarding. Application: dashboard, leads, contacts, customers, properties, requirements, deals, pipeline, follow-ups, site visits, referrals, commissions, documents, imports, lead intake, agents, workflows, automation rules and history, approvals, settings (AI providers, governance), notification preferences, billing, and a wildcard route.
- Styling: 43 CSS and SCSS files, plus `styles/` and `components/`. This is the competing visual architecture the redesign replaces.
- Existing libraries that already fit the spec: `@dnd-kit/core` and `@dnd-kit/sortable`, `lucide-react`, `react-data-grid`. Adding these again would duplicate them.
- API clients: 26 service modules under `src/services`, one per domain, on a shared `lib/api.ts` client. These are the integration boundary to keep.

## 2. Backend persistence that already exists

| Capability | Backend | Frontend today |
|---|---|---|
| Per-user notification preferences | `GET` and `PATCH /api/v1/notifications/preferences` | Used by the notification preferences page |
| Dashboard summary (metrics) | `GET /api/v1/dashboard/summary` | Used by the dashboard |
| Organization and team membership | `/api/v1/organizations`, `/api/v1/team` | Used by team and org settings |
| Governance and capability switches | `/api/v1/governance` | Used by the governance settings page |
| Grid view settings | none | Stored only in browser `localStorage` (`lib/gridViewPreferences.ts`) |

## 3. Backend persistence that does not exist

Dashboard layouts, widget configuration, saved views, grid preferences shared by a team or organization, workspace settings and configuration inheritance have no backend endpoints or tables. The frontend may keep these only as temporary local state, and it must be labelled as such. See `backend-customization-api-proposal.md`.

## 4. Architecture decisions

**Styling: one system.** Design tokens as CSS custom properties on `:root`, with a `data-theme` attribute for light, dark and system. Components use tokens only. No hard-coded colours or sizes in components. The existing 43 stylesheets are removed module by module, only after the replacement is in place and verified.

**Primitives: reuse, then add minimally.** Use the existing `react-router`, `lucide-react`, `@dnd-kit` and `react-data-grid`. Evaluate Radix UI for accessible menus, dialogs, popovers and tabs before adding it. Do not add Tailwind: it would create a second styling system beside the token system.

**Motion: CSS first.** Use CSS transitions and `prefers-reduced-motion` for interaction feedback. Add Motion only if a specific interaction needs layout animation that CSS cannot express.

**Charts: one library.** Pick one charting library in the design-system phase, and document the choice against bundle size.

**Forms: React Hook Form with Zod,** where a form has validation rules. Do not migrate forms that work and have no open defects.

**Scope rules.** The `services/` layer and the backend contracts stay as they are. Route guards, permissions and entitlement checks are reused, not re-implemented in components.

## 5. Migration plan (phases)

1. Reference analysis: full-resolution crops and verified inventory. In progress: tile boundaries need checking.
2. Integration audit: route-to-API map for all 35 routes. Partly complete at the service level.
3. Architecture and technology decisions: this document.
4. Design system: tokens, themes, typography, spacing, surfaces. Not started.
5. Application shell and navigation. Not started.
6. Shared component system. Not started.
7. Data grids, forms and interaction foundation. Not started.
8. Dashboard and customization experience. Not started.
9. Core CRM modules. Not started.
10. Operational modules. Not started.
11. AI and automation modules. Not started.
12. Administration, billing and settings. Not started.
13. Public marketing experience. Not started.
14. Responsive design and accessibility. Not started.
15. Functional and visual regression. Not started.

Each phase ends with: build, tests, lint, console check, responsive check in both themes, and a screenshot comparison against the reference. Obsolete code is removed only after its replacement is verified.

## 6. Risks

- Scope: 35 routes, about 25 reference screens and a full design system is weeks of work. Each phase must be committed and reviewable.
- Regression: rewriting pages can break business workflows. The existing 163 tests are the floor. Each migrated route needs its own tests.
- Visual fidelity: most reference tiles are not yet verified at full resolution.
- Persistence: customization features that need backend APIs must stay labelled as unavailable or temporary until those APIs are approved and built.

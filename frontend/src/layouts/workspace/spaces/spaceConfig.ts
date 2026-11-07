import {
  Handshake,
  House,
  LayoutDashboard,
  Network,
  Target,
  Workflow,
  type LucideIcon,
} from "lucide-react";

/**
 * Configuration of the primary workspace spaces and their tabs. The shell renders from this list, so spaces and tabs are
 * added here, not in the layout.
 *
 * A tab points at a route (`to`). Existing pages keep their own routes. A placeholder tab (`placeholder: true`) points at
 * a `/spaces/<space>/<tab>` route that shows "not available yet"; it never renders fake data. Existing routes that no
 * space lists stay reachable through the command palette.
 */

export interface SpaceTab {
  readonly id: string;
  readonly label: string;
  /** Route the tab opens. */
  readonly to?: string;
  /** Placeholder tabs show a not-yet-available state. */
  readonly placeholder?: boolean;
}

export interface SpaceDefinition {
  readonly id: string;
  readonly label: string;
  readonly description: string;
  readonly icon: LucideIcon;
  /** Overview cannot be hidden, so the workspace always has a home. */
  readonly hideable: boolean;
  readonly tabs: readonly SpaceTab[];
}

export const SPACE_DEFINITIONS: readonly SpaceDefinition[] = [
  {
    id: "overview",
    label: "Overview",
    description: "Your business at a glance",
    icon: LayoutDashboard,
    hideable: false,
    tabs: [
      { id: "dashboard", label: "Dashboard", to: "/" },
      { id: "follow-ups", label: "Follow-ups", to: "/follow-ups" },
      { id: "my-day", label: "My Day", to: "/spaces/overview/my-day", placeholder: true },
      { id: "trends", label: "Trends", to: "/spaces/overview/trends", placeholder: true },
    ],
  },
  {
    id: "sales",
    label: "Sales",
    description: "Contacts, customers and leads",
    icon: Target,
    hideable: true,
    tabs: [
      { id: "contacts", label: "Contacts", to: "/contacts" },
      { id: "customers", label: "Customers", to: "/customers" },
      { id: "leads", label: "Leads", to: "/leads" },
      { id: "pipeline", label: "Pipeline", to: "/pipeline" },
      { id: "site-visits", label: "Site Visits", to: "/site-visits" },
    ],
  },
  {
    id: "properties",
    label: "Properties",
    description: "Listings and client requirements",
    icon: House,
    hideable: true,
    tabs: [
      { id: "properties", label: "Properties", to: "/properties" },
      { id: "requirements", label: "Requirements", to: "/requirements" },
    ],
  },
  {
    id: "deals",
    label: "Deals",
    description: "Deals and commissions",
    icon: Handshake,
    hideable: true,
    tabs: [
      { id: "deals", label: "Deals", to: "/deals" },
      { id: "commissions", label: "Commissions", to: "/commissions" },
    ],
  },
  {
    id: "partners",
    label: "Partners",
    description: "Referral partners",
    icon: Network,
    hideable: true,
    tabs: [{ id: "referrals", label: "Referrals", to: "/referrals" }],
  },
  {
    id: "operations",
    label: "Operations",
    description: "Activities, documents, automation and imports",
    icon: Workflow,
    hideable: true,
    tabs: [
      { id: "activities", label: "Activities", to: "/spaces/operations/activities", placeholder: true },
      { id: "documents", label: "Documents", to: "/documents" },
      { id: "automation", label: "Automation", to: "/automation-rules" },
      { id: "imports", label: "Imports", to: "/imports" },
    ],
  },
];

export const DEFAULT_SPACE_ORDER: readonly string[] = SPACE_DEFINITIONS.map((space) => space.id);

export function getSpaceById(id: string): SpaceDefinition | undefined {
  return SPACE_DEFINITIONS.find((space) => space.id === id);
}

/** Matches a path to the space that owns it: the route itself or a child of it. The root route only matches exactly. */
function routeMatches(pathname: string, to: string): boolean {
  if (to === "/") return pathname === "/";
  return pathname === to || pathname.startsWith(`${to}/`);
}

/** The space and tab whose route matches the path, using the most specific match. Undefined when none does. */
export function resolveSpaceLocation(
  pathname: string,
): { space: SpaceDefinition; tab: SpaceTab } | undefined {
  let best: { space: SpaceDefinition; tab: SpaceTab; length: number } | undefined;
  for (const space of SPACE_DEFINITIONS) {
    for (const tab of space.tabs) {
      if (!tab.to || !routeMatches(pathname, tab.to)) continue;
      if (!best || tab.to.length > best.length) best = { space, tab, length: tab.to.length };
    }
  }
  return best ? { space: best.space, tab: best.tab } : undefined;
}

/** Every available (non-placeholder) route in the spaces, in order. Used for the command palette. */
export function listSpaceRoutes(): Array<{ id: string; label: string; to: string; space: string }> {
  return SPACE_DEFINITIONS.flatMap((space) =>
    space.tabs.flatMap((tab) =>
      tab.to && !tab.placeholder ? [{ id: tab.id, label: tab.label, to: tab.to, space: space.label }] : [],
    ),
  );
}

/**
 * Existing routes that no space tab lists. They stay reachable from the command palette so no screen is lost during the
 * migration. Each entry is a label and a route; the labels are shown in the palette only.
 */
export const UNLISTED_ROUTES: ReadonlyArray<{ label: string; to: string; group: string }> = [
  { label: "Billing", to: "/billing", group: "Account" },
  { label: "Settings", to: "/settings", group: "Account" },
  { label: "Governance settings", to: "/settings/governance", group: "Account" },
  { label: "AI providers", to: "/settings/ai-providers", group: "Account" },
  { label: "Notification settings", to: "/notification-preferences", group: "Account" },
  { label: "Agents", to: "/agents", group: "AI" },
  { label: "Workflows", to: "/workflows", group: "AI" },
  { label: "Automation history", to: "/automation-history", group: "AI" },
  { label: "Approvals", to: "/approvals", group: "AI" },
  { label: "Lead intake", to: "/lead-intake", group: "Sales" },
];


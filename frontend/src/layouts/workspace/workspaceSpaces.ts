import {
  Activity,
  Bot,
  BellRing,
  BriefcaseBusiness,
  Building2,
  CalendarCheck,
  CircleDollarSign,
  ClipboardList,
  ContactRound,
  CreditCard,
  FileText,
  Handshake,
  House,
  LayoutDashboard,
  Layers,
  MapPin,
  Network,
  Settings,
  Target,
  TrendingUp,
  Upload,
  UserRound,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";

/**
 * Static navigation model for the global sidebar. Module labels are stable
 * identifiers: personal layout preferences are stored by label, so renaming a
 * label would reset that user's saved layout.
 *
 * Spaces are a UI grouping of existing routes. They are not organizations or
 * tenants, and they carry no permissions. Route access is still enforced by
 * the routes and the server.
 */
export interface WorkspaceModule {
  readonly label: string;
  readonly to: string;
  readonly icon: LucideIcon;
}

export interface WorkspaceSpace {
  readonly id: string;
  readonly label: string;
  readonly icon: LucideIcon;
  readonly moduleLabels: readonly string[];
}

export const GLOBAL_MODULES: readonly WorkspaceModule[] = [
  { label: "Overview", to: "/", icon: LayoutDashboard },
  { label: "Notifications", to: "/notification-preferences", icon: BellRing },
  { label: "Billing", to: "/billing", icon: CreditCard },
  { label: "Settings", to: "/settings", icon: Settings },
];

export const WORKSPACE_SPACES: readonly WorkspaceSpace[] = [
  {
    id: "sales",
    label: "Sales",
    icon: Target,
    moduleLabels: ["Leads", "Contacts", "Customers", "Pipeline", "Follow-ups"],
  },
  {
    id: "deals-revenue",
    label: "Deals & Revenue",
    icon: TrendingUp,
    moduleLabels: ["Deals", "Commissions"],
  },
  {
    id: "property",
    label: "Property",
    icon: House,
    moduleLabels: ["Properties", "Requirements", "Site Visits"],
  },
  {
    id: "partners",
    label: "Partners",
    icon: Network,
    moduleLabels: ["Referrals"],
  },
  {
    id: "operations",
    label: "Operations",
    icon: Layers,
    moduleLabels: ["Documents", "Imports", "Automation Rules", "Activity"],
  },
];

export const SPACE_MODULES: readonly WorkspaceModule[] = [
  { label: "Leads", to: "/leads", icon: Users },
  { label: "Contacts", to: "/contacts", icon: ContactRound },
  { label: "Customers", to: "/customers", icon: UserRound },
  { label: "Requirements", to: "/requirements", icon: ClipboardList },
  { label: "Pipeline", to: "/pipeline", icon: Workflow },
  { label: "Deals", to: "/deals", icon: Handshake },
  { label: "Properties", to: "/properties", icon: Building2 },
  { label: "Referrals", to: "/referrals", icon: BriefcaseBusiness },
  { label: "Site Visits", to: "/site-visits", icon: MapPin },
  { label: "Follow-ups", to: "/follow-ups", icon: CalendarCheck },
  { label: "Commissions", to: "/commissions", icon: CircleDollarSign },
  { label: "Documents", to: "/documents", icon: FileText },
  { label: "Imports", to: "/imports", icon: Upload },
  { label: "Automation Rules", to: "/automation-rules", icon: Bot },
  { label: "Activity", to: "/automation-history", icon: Activity },
];

export const WORKSPACE_MODULES: readonly WorkspaceModule[] = [
  ...GLOBAL_MODULES,
  ...SPACE_MODULES,
];

export const WORKSPACE_MODULE_LABELS: readonly string[] = WORKSPACE_MODULES.map(
  (module) => module.label,
);

export const WORKSPACE_SPACE_IDS: readonly string[] = WORKSPACE_SPACES.map(
  (space) => space.id,
);

export function getWorkspaceModule(label: string): WorkspaceModule | undefined {
  return WORKSPACE_MODULES.find((module) => module.label === label);
}

export function getSpaceForModule(label: string): WorkspaceSpace | undefined {
  return WORKSPACE_SPACES.find((space) => space.moduleLabels.includes(label));
}

import { WORKSPACE_SPACE_IDS } from "./workspaceSpaces";
import {
  parsePersonalPreference,
  personalPreferenceKey,
  readRawPreference,
  removePersonalPreference,
  writePersonalPreference,
} from "../../lib/personalPreferences";

export type TableDensity = "comfortable" | "compact";

export const WORKSPACE_PREFERENCES_CHANGED_EVENT =
  "dealflow:workspace-preferences-changed";

/**
 * Personal display preferences. Every field here applies only to the current
 * user in the current organization, and is stored in this browser only. None
 * of these values change shared organization configuration or another user's
 * interface.
 */
export interface WorkspacePreferences {
  sidebarCollapsed: boolean;
  navigationOrder: string[];
  hiddenModules: string[];
  pinnedModules: string[];
  spaceOrder: string[];
  collapsedSpaces: string[];
  tableDensity: TableDensity;
}

export const DEFAULT_WORKSPACE_PREFERENCES: WorkspacePreferences = {
  sidebarCollapsed: false,
  navigationOrder: [
    "Overview",
    "Leads",
    "Contacts",
    "Customers",
    "Requirements",
    "Pipeline",
    "Deals",
    "Properties",
    "Referrals",
    "Site Visits",
    "Follow-ups",
    "Commissions",
    "Documents",
    "Imports",
    "Automation Rules",
    "Activity",
    "Notifications",
    "Billing",
    "Settings",
  ],
  hiddenModules: [],
  pinnedModules: ["Leads", "Follow-ups"],
  spaceOrder: [...WORKSPACE_SPACE_IDS],
  collapsedSpaces: [],
  tableDensity: "comfortable",
};

/** Workspace preferences are personal: one key per user per organization, in the personal preference store. */
function storageKey(organizationId: string, userId: string): string | null {
  return personalPreferenceKey("workspace-preferences", { userId, organizationId });
}

function uniqueStrings(value: unknown): string[] | null {
  if (!Array.isArray(value)) {
    return null;
  }

  return [
    ...new Set(
      value.filter(
        (item): item is string =>
          typeof item === "string" && item.trim().length > 0,
      ),
    ),
  ];
}

function normalizeOrder(
  savedOrder: string[] | null,
  availableModules: string[],
): string[] {
  const available = new Set(availableModules);

  const retained = (savedOrder ?? []).filter((module) =>
    available.has(module),
  );

  const retainedSet = new Set(retained);

  return [
    ...retained,
    ...availableModules.filter((module) => !retainedSet.has(module)),
  ];
}

function normalizePreferences(
  value: unknown,
  availableModules: string[],
): WorkspacePreferences {
  const defaults = DEFAULT_WORKSPACE_PREFERENCES;

  if (!value || typeof value !== "object") {
    return {
      ...defaults,
      navigationOrder: [...availableModules],
      hiddenModules: [],
      pinnedModules: defaults.pinnedModules.filter((module) =>
        availableModules.includes(module),
      ),
      spaceOrder: [...WORKSPACE_SPACE_IDS],
      collapsedSpaces: [],
    };
  }

  const saved = value as Partial<WorkspacePreferences>;
  const savedOrder = uniqueStrings(saved.navigationOrder);
  const savedHidden = uniqueStrings(saved.hiddenModules);
  const savedPinned = uniqueStrings(saved.pinnedModules);
  const savedSpaceOrder = uniqueStrings(saved.spaceOrder);
  const savedCollapsedSpaces = uniqueStrings(saved.collapsedSpaces);
  const available = new Set(availableModules);
  const availableSpaces = new Set(WORKSPACE_SPACE_IDS);

  return {
    sidebarCollapsed:
      typeof saved.sidebarCollapsed === "boolean"
        ? saved.sidebarCollapsed
        : defaults.sidebarCollapsed,

    navigationOrder: normalizeOrder(savedOrder, availableModules),

    hiddenModules: (savedHidden ?? []).filter((module) =>
      available.has(module),
    ),

    pinnedModules: (savedPinned ?? defaults.pinnedModules).filter(
      (module) => available.has(module),
    ),

    spaceOrder: normalizeOrder(savedSpaceOrder, [...WORKSPACE_SPACE_IDS]),

    collapsedSpaces: (savedCollapsedSpaces ?? []).filter((spaceId) =>
      availableSpaces.has(spaceId),
    ),

    tableDensity:
      saved.tableDensity === "compact" ||
      saved.tableDensity === "comfortable"
        ? saved.tableDensity
        : defaults.tableDensity,
  };
}

export function loadWorkspacePreferences(
  organizationId: string,
  userId: string,
  availableModules: string[] = DEFAULT_WORKSPACE_PREFERENCES.navigationOrder,
): WorkspacePreferences {
  const key = storageKey(organizationId, userId);
  const fallback = normalizePreferences(DEFAULT_WORKSPACE_PREFERENCES, availableModules);
  // Values saved before the envelope existed are accepted; normalization fills any missing fields.
  return parsePersonalPreference(
    readRawPreference(key),
    (data) => normalizePreferences(data, availableModules),
    fallback,
    { acceptLegacy: true },
  );
}

export function saveWorkspacePreferences(
  organizationId: string,
  userId: string,
  preferences: WorkspacePreferences,
): void {
  // A refused write leaves the workspace usable for this session; the next load shows the last saved state.
  writePersonalPreference(storageKey(organizationId, userId), preferences);
  window.dispatchEvent(new Event(WORKSPACE_PREFERENCES_CHANGED_EVENT));
}

export function resetWorkspacePreferences(
  organizationId: string,
  userId: string,
): void {
  // Removes only this user's key in this organization.
  removePersonalPreference(storageKey(organizationId, userId));
  window.dispatchEvent(new Event(WORKSPACE_PREFERENCES_CHANGED_EVENT));
}

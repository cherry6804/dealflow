
export type TableDensity = "comfortable" | "compact";

export interface WorkspacePreferences {
  sidebarCollapsed: boolean;
  navigationOrder: string[];
  hiddenModules: string[];
  pinnedModules: string[];
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
    "Settings",
  ],
  hiddenModules: [],
  pinnedModules: ["Leads", "Follow-ups"],
  tableDensity: "comfortable",
};

function storageKey(organizationId: string, userId: string): string {
  return `dealflow:workspace-preferences:${organizationId}:${userId}`;
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
    };
  }

  const saved = value as Partial<WorkspacePreferences>;
  const savedOrder = uniqueStrings(saved.navigationOrder);
  const savedHidden = uniqueStrings(saved.hiddenModules);
  const savedPinned = uniqueStrings(saved.pinnedModules);
  const available = new Set(availableModules);

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
  try {
    const raw = localStorage.getItem(storageKey(organizationId, userId));

    if (!raw) {
      return normalizePreferences(
        DEFAULT_WORKSPACE_PREFERENCES,
        availableModules,
      );
    }

    return normalizePreferences(JSON.parse(raw), availableModules);
  } catch {
    return normalizePreferences(
      DEFAULT_WORKSPACE_PREFERENCES,
      availableModules,
    );
  }
}

export function saveWorkspacePreferences(
  organizationId: string,
  userId: string,
  preferences: WorkspacePreferences,
): void {
  try {
    localStorage.setItem(
      storageKey(organizationId, userId),
      JSON.stringify(preferences),
    );
  } catch {
    // The workspace remains usable if browser storage is unavailable.
  }
}

export function resetWorkspacePreferences(
  organizationId: string,
  userId: string,
): void {
  try {
    localStorage.removeItem(storageKey(organizationId, userId));
  } catch {
    // Resetting local preferences must not break workspace navigation.
  }
}

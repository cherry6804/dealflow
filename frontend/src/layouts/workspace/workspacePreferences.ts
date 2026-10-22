
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
    "Requirements",
    "Pipeline",
    "Deals",
    "Follow-ups",
    "Commissions",
    "Documents",
    "Activity",
    "Settings",
  ],
  hiddenModules: [],
  pinnedModules: ["Leads", "Follow-ups"],
  tableDensity: "comfortable",
};

function storageKey(
  organizationId: string,
  userId: string,
): string {
  return `dealflow:workspace-preferences:${organizationId}:${userId}`;
}

export function loadWorkspacePreferences(
  organizationId: string,
  userId: string,
): WorkspacePreferences {
  const defaults = DEFAULT_WORKSPACE_PREFERENCES;

  try {
    const raw = localStorage.getItem(
      storageKey(organizationId, userId),
    );

    if (!raw) {
      return { ...defaults };
    }

    const parsed: unknown = JSON.parse(raw);

    if (!parsed || typeof parsed !== "object") {
      return { ...defaults };
    }

    const saved = parsed as Partial<WorkspacePreferences>;

    const validDensity =
      saved.tableDensity === "compact" ||
      saved.tableDensity === "comfortable";

    return {
      sidebarCollapsed:
        typeof saved.sidebarCollapsed === "boolean"
          ? saved.sidebarCollapsed
          : defaults.sidebarCollapsed,

      navigationOrder: Array.isArray(saved.navigationOrder)
        ? saved.navigationOrder.filter(
            (item): item is string => typeof item === "string",
          )
        : [...defaults.navigationOrder],

      hiddenModules: Array.isArray(saved.hiddenModules)
        ? saved.hiddenModules.filter(
            (item): item is string => typeof item === "string",
          )
        : [...defaults.hiddenModules],

      pinnedModules: Array.isArray(saved.pinnedModules)
        ? saved.pinnedModules.filter(
            (item): item is string => typeof item === "string",
          )
        : [...defaults.pinnedModules],

      tableDensity: validDensity
        ? saved.tableDensity!
        : defaults.tableDensity,
    };
  } catch {
    return { ...defaults };
  }
}

export function saveWorkspacePreferences(
  organizationId: string,
  userId: string,
  preferences: WorkspacePreferences,
): void {
  localStorage.setItem(
    storageKey(organizationId, userId),
    JSON.stringify(preferences),
  );
}

export function resetWorkspacePreferences(
  organizationId: string,
  userId: string,
): void {
  localStorage.removeItem(storageKey(organizationId, userId));
}

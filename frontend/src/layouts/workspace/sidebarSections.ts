import type { WorkspacePreferences } from "./workspacePreferences";
import {
  GLOBAL_MODULES,
  WORKSPACE_MODULES,
  WORKSPACE_SPACES,
  getWorkspaceModule,
  type WorkspaceModule,
  type WorkspaceSpace,
} from "./workspaceSpaces";

export interface SidebarSpaceSection {
  readonly space: WorkspaceSpace;
  readonly expanded: boolean;
  readonly modules: readonly WorkspaceModule[];
}

export interface SidebarSections {
  readonly pinned: readonly WorkspaceModule[];
  readonly global: readonly WorkspaceModule[];
  readonly spaces: readonly SidebarSpaceSection[];
}

function orderByPreference(
  modules: readonly WorkspaceModule[],
  navigationOrder: readonly string[],
): WorkspaceModule[] {
  const rank = new Map(navigationOrder.map((label, index) => [label, index]));

  return [...modules].sort(
    (a, b) =>
      (rank.get(a.label) ?? Number.MAX_SAFE_INTEGER) -
      (rank.get(b.label) ?? Number.MAX_SAFE_INTEGER),
  );
}

/**
 * Applies the current user's personal layout to the static navigation model.
 * Hidden items are removed everywhere. Pinned items appear once, in the pinned
 * group, and are left out of their space so no destination is listed twice.
 * Spaces with nothing left to show are dropped.
 */
export function buildSidebarSections(
  preferences: WorkspacePreferences,
): SidebarSections {
  const hidden = new Set(preferences.hiddenModules);
  const pinned = new Set(preferences.pinnedModules);
  const collapsed = new Set(preferences.collapsedSpaces);
  const order = preferences.navigationOrder;

  const isShown = (module: WorkspaceModule) =>
    !hidden.has(module.label) && !pinned.has(module.label);

  const spacesById = new Map(WORKSPACE_SPACES.map((space) => [space.id, space]));

  const spaces: SidebarSpaceSection[] = [];

  for (const spaceId of preferences.spaceOrder) {
    const space = spacesById.get(spaceId);

    if (!space) {
      continue;
    }

    const modules = orderByPreference(
      space.moduleLabels
        .map((label) => getWorkspaceModule(label))
        .filter((module): module is WorkspaceModule => module !== undefined)
        .filter(isShown),
      order,
    );

    if (modules.length > 0) {
      spaces.push({ space, expanded: !collapsed.has(space.id), modules });
    }
  }

  return {
    pinned: orderByPreference(
      WORKSPACE_MODULES.filter(
        (module) => pinned.has(module.label) && !hidden.has(module.label),
      ),
      order,
    ),
    global: orderByPreference(GLOBAL_MODULES.filter(isShown), order),
    spaces,
  };
}

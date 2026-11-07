import { DEFAULT_SPACE_ORDER, SPACE_DEFINITIONS, getSpaceById, type SpaceDefinition } from "./spaceConfig";

/**
 * Personal sidebar layout. Pure functions only: no storage, no React. The stored value is read and written through the
 * personal preference store (see useSpacePreferences), so it belongs to one user in one organization.
 *
 * - order: every space id, in the user's arrangement (hidden spaces keep their place).
 * - pinned: pinned spaces are listed first, in their order.
 * - hidden: spaces removed from the sidebar. Spaces that cannot be hidden (Overview) are never listed here.
 * - collapsed: the sidebar shows icons only (true) or icons with labels (false).
 * - density: row spacing inside the sidebar.
 */
export type SidebarDensity = "comfortable" | "compact";

export interface SpacePreferences {
  readonly order: readonly string[];
  readonly pinned: readonly string[];
  readonly hidden: readonly string[];
  readonly collapsed: boolean;
  readonly density: SidebarDensity;
}

export const DEFAULT_SPACE_PREFERENCES: SpacePreferences = {
  order: [...DEFAULT_SPACE_ORDER],
  pinned: [],
  hidden: [],
  collapsed: false,
  density: "comfortable",
};

const DENSITIES: readonly SidebarDensity[] = ["comfortable", "compact"];

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)];
}

/**
 * Rebuilds preferences from stored data. Unknown space ids are dropped, missing spaces take their default position, and
 * invalid fields fall back to defaults. Overview can never be hidden. Pinned and hidden never overlap.
 */
export function normalizeSpacePreferences(value: unknown): SpacePreferences {
  if (!value || typeof value !== "object") return DEFAULT_SPACE_PREFERENCES;
  const saved = value as Record<string, unknown>;
  const known = new Set(DEFAULT_SPACE_ORDER);
  const cannotHide = new Set(SPACE_DEFINITIONS.filter((space) => !space.hideable).map((space) => space.id));

  const savedOrder = unique(stringList(saved.order).filter((id) => known.has(id)));
  const order = [...savedOrder, ...DEFAULT_SPACE_ORDER.filter((id) => !savedOrder.includes(id))];

  const hidden = unique(stringList(saved.hidden).filter((id) => known.has(id) && !cannotHide.has(id)));
  const pinned = unique(stringList(saved.pinned).filter((id) => known.has(id) && !hidden.includes(id)));

  return {
    order,
    pinned,
    hidden,
    collapsed: saved.collapsed === true,
    density: DENSITIES.includes(saved.density as SidebarDensity) ? (saved.density as SidebarDensity) : "comfortable",
  };
}

/** Spaces in the order the sidebar shows them: pinned first (in order), then the rest, without hidden spaces. */
export function arrangeSpaces(preferences: SpacePreferences): SpaceDefinition[] {
  return visibleSpaceIds(preferences)
    .map((id) => getSpaceById(id))
    .filter((space): space is SpaceDefinition => space !== undefined);
}

function visibleSpaceIds(preferences: SpacePreferences): string[] {
  const hidden = new Set(preferences.hidden);
  const pinned = new Set(preferences.pinned);
  const visible = preferences.order.filter((id) => !hidden.has(id));
  return [...visible.filter((id) => pinned.has(id)), ...visible.filter((id) => !pinned.has(id))];
}

/** Every space in customizer order, including hidden ones, so they can be restored. */
export function allSpacesInOrder(preferences: SpacePreferences): Array<{ space: SpaceDefinition; pinned: boolean; hidden: boolean }> {
  const pinned = new Set(preferences.pinned);
  const hidden = new Set(preferences.hidden);
  const ordered = [
    ...preferences.order.filter((id) => pinned.has(id) && !hidden.has(id)),
    ...preferences.order.filter((id) => !pinned.has(id) && !hidden.has(id)),
    ...preferences.order.filter((id) => hidden.has(id)),
  ];
  return ordered
    .map((id) => getSpaceById(id))
    .filter((space): space is SpaceDefinition => space !== undefined)
    .map((space) => ({ space, pinned: pinned.has(space.id), hidden: hidden.has(space.id) }));
}

/** Moves a space to a new position in the full list. Used by drag and drop. */
export function reorderSpaces(preferences: SpacePreferences, fromId: string, toId: string): SpacePreferences {
  const ids = allSpacesInOrder(preferences).map((entry) => entry.space.id);
  const from = ids.indexOf(fromId);
  const to = ids.indexOf(toId);
  if (from < 0 || to < 0 || from === to) return preferences;
  const next = [...ids];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return { ...preferences, order: next };
}

/** Moves a space one place up or down. The keyboard and button alternative to dragging. */
export function moveSpace(preferences: SpacePreferences, id: string, direction: -1 | 1): SpacePreferences {
  const ids = allSpacesInOrder(preferences).map((entry) => entry.space.id);
  const index = ids.indexOf(id);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= ids.length) return preferences;
  return reorderSpaces(preferences, id, ids[target]);
}

/** Pins or unpins a space. Pinning a hidden space shows it. */
export function togglePinned(preferences: SpacePreferences, id: string): SpacePreferences {
  if (!getSpaceById(id)) return preferences;
  if (preferences.pinned.includes(id)) {
    return { ...preferences, pinned: preferences.pinned.filter((pinned) => pinned !== id) };
  }
  return {
    ...preferences,
    pinned: [...preferences.pinned, id],
    hidden: preferences.hidden.filter((hidden) => hidden !== id),
  };
}

/**
 * Shows or hides a space. Overview cannot be hidden. Hiding a pinned space unpins it.
 * Permission filtering is not applied here: no per-user permission list exists yet, so every space is permitted.
 */
export function toggleHidden(preferences: SpacePreferences, id: string): SpacePreferences {
  const space = getSpaceById(id);
  if (!space || !space.hideable) return preferences;
  if (preferences.hidden.includes(id)) {
    return { ...preferences, hidden: preferences.hidden.filter((hidden) => hidden !== id) };
  }
  return {
    ...preferences,
    hidden: [...preferences.hidden, id],
    pinned: preferences.pinned.filter((pinned) => pinned !== id),
  };
}

export function setCollapsed(preferences: SpacePreferences, collapsed: boolean): SpacePreferences {
  return { ...preferences, collapsed };
}

export function setDensity(preferences: SpacePreferences, density: SidebarDensity): SpacePreferences {
  return { ...preferences, density };
}

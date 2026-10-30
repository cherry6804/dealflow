export interface GridColumnOption {
  key: string;
  label: string;
  defaultVisible: boolean;
}

export interface GridColumnPreferences {
  order: string[];
  hidden: string[];
}

export function createDefaultGridColumnPreferences(
  columnOptions: readonly GridColumnOption[],
): GridColumnPreferences {
  return {
    order: columnOptions.map((option) => option.key),
    hidden: columnOptions
      .filter((option) => !option.defaultVisible)
      .map((option) => option.key),
  };
}

export function gridColumnStorageKey(
  organizationId: string,
  userId: string,
  gridId: string,
): string {
  return `dealflow:grid-view:${organizationId}:${userId}:${gridId}`;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

/**
 * Rebuilds saved preferences against the grid's current columns. Unknown keys
 * are dropped, and columns added since the preference was saved take their
 * default position and visibility.
 */
export function normalizeGridColumnPreferences(
  value: unknown,
  columnOptions: readonly GridColumnOption[],
): GridColumnPreferences {
  const defaults = createDefaultGridColumnPreferences(columnOptions);

  if (!value || typeof value !== "object") {
    return defaults;
  }

  const known = new Set(columnOptions.map((option) => option.key));
  const saved = value as { order?: unknown; hidden?: unknown };

  const savedOrder = Array.isArray(saved.order)
    ? saved.order.filter(isString).filter((key) => known.has(key))
    : [];
  const savedOrderSet = new Set(savedOrder);

  const savedHidden = Array.isArray(saved.hidden)
    ? saved.hidden.filter(isString)
    : defaults.hidden;
  const addedHidden = defaults.hidden.filter(
    (key) => !savedOrderSet.has(key),
  );

  return {
    order: [...new Set([...savedOrder, ...defaults.order])],
    hidden: [...new Set([...savedHidden, ...addedHidden])].filter((key) =>
      known.has(key),
    ),
  };
}

export function visibleGridColumnKeys(
  preferences: GridColumnPreferences,
): string[] {
  const hidden = new Set(preferences.hidden);

  return preferences.order.filter((key) => !hidden.has(key));
}

/**
 * Shows or hides one configurable column. The last visible column cannot be
 * hidden, so a grid never renders with no data columns.
 */
export function setGridColumnVisibility(
  preferences: GridColumnPreferences,
  key: string,
  visible: boolean,
): GridColumnPreferences {
  const withoutKey = preferences.hidden.filter((hiddenKey) => hiddenKey !== key);

  if (visible) {
    return { ...preferences, hidden: withoutKey };
  }

  const remaining = visibleGridColumnKeys(preferences).filter(
    (visibleKey) => visibleKey !== key,
  );

  if (remaining.length === 0) {
    return preferences;
  }

  return { ...preferences, hidden: [...withoutKey, key] };
}

export function moveGridColumn(
  preferences: GridColumnPreferences,
  key: string,
  direction: -1 | 1,
): GridColumnPreferences {
  const index = preferences.order.indexOf(key);
  const targetIndex = index + direction;

  if (index < 0 || targetIndex < 0 || targetIndex >= preferences.order.length) {
    return preferences;
  }

  const order = [...preferences.order];
  [order[index], order[targetIndex]] = [order[targetIndex], order[index]];

  return { ...preferences, order };
}

/**
 * Returns the grid's columns in the user's order, showing only visible ones.
 * Columns that are not configurable (such as actions) keep their position at
 * the end of the grid.
 */
export function arrangeGridColumns<T extends { key: string }>(
  columns: readonly T[],
  columnOptions: readonly GridColumnOption[],
  preferences: GridColumnPreferences,
): T[] {
  const configurable = new Set(columnOptions.map((option) => option.key));
  const columnByKey = new Map(columns.map((column) => [column.key, column]));
  const visible = new Set(visibleGridColumnKeys(preferences));

  const arranged = preferences.order
    .filter((key) => visible.has(key))
    .map((key) => columnByKey.get(key))
    .filter((column): column is T => column !== undefined);

  const fixed = columns.filter((column) => !configurable.has(column.key));

  return [...arranged, ...fixed];
}

export function loadGridColumnPreferences(
  storageKey: string,
  columnOptions: readonly GridColumnOption[],
): GridColumnPreferences {
  try {
    const raw = localStorage.getItem(storageKey);

    return normalizeGridColumnPreferences(
      raw ? JSON.parse(raw) : null,
      columnOptions,
    );
  } catch {
    return normalizeGridColumnPreferences(null, columnOptions);
  }
}

export function saveGridColumnPreferences(
  storageKey: string,
  preferences: GridColumnPreferences,
): void {
  try {
    localStorage.setItem(storageKey, JSON.stringify(preferences));
  } catch {
    // The grid remains usable when browser storage is unavailable.
  }
}

export function clearGridColumnPreferences(storageKey: string): void {
  try {
    localStorage.removeItem(storageKey);
  } catch {
    // Resetting local preferences must not break the grid.
  }
}

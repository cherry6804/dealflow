import type { SortColumn } from "react-data-grid";

/**
 * Pure column-layout model for the EnterpriseDataGrid. No React, no storage. The stored value is read and written through the
 * personal preference store (see useGridLayout), so it belongs to one user in one organization.
 *
 * - order: every column key in the user's order.
 * - hidden: keys the user has hidden. At least one column always stays visible.
 * - widths: user-set column widths in pixels, clamped to GRID_WIDTH_BOUNDS.
 * - pinned: keys pinned to the left edge, shown first in their order.
 * - density: row height preset.
 */

export type GridDensity = "comfortable" | "compact";

export interface GridColumnDef {
  readonly key: string;
  readonly label: string;
  readonly defaultWidth: number;
  readonly defaultVisible?: boolean;
  /** Columns that cannot be hidden, reordered or pinned (for example the row actions column). */
  readonly fixed?: boolean;
}

export interface GridLayout {
  readonly order: readonly string[];
  readonly hidden: readonly string[];
  readonly widths: Readonly<Record<string, number>>;
  readonly pinned: readonly string[];
  readonly density: GridDensity;
}

export const GRID_WIDTH_BOUNDS = { min: 96, max: 720 } as const;
export const GRID_ROW_HEIGHT: Readonly<Record<GridDensity, number>> = { comfortable: 52, compact: 40 };

export function clampGridWidth(value: number): number {
  if (!Number.isFinite(value)) return GRID_WIDTH_BOUNDS.min;
  return Math.min(GRID_WIDTH_BOUNDS.max, Math.max(GRID_WIDTH_BOUNDS.min, Math.round(value)));
}

export function createDefaultGridLayout(columns: readonly GridColumnDef[]): GridLayout {
  return {
    order: columns.map((column) => column.key),
    hidden: columns.filter((column) => column.defaultVisible === false).map((column) => column.key),
    widths: {},
    pinned: [],
    density: "comfortable",
  };
}

const DENSITIES: readonly GridDensity[] = ["comfortable", "compact"];

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/**
 * Rebuilds a stored layout against the grid's current columns. Unknown keys are dropped, new columns take their defaults,
 * invalid widths are discarded, and at least one column stays visible.
 */
export function normalizeGridLayout(value: unknown, columns: readonly GridColumnDef[]): GridLayout {
  const defaults = createDefaultGridLayout(columns);
  if (!value || typeof value !== "object") return defaults;
  const saved = value as Record<string, unknown>;
  const known = new Set(columns.map((column) => column.key));
  const fixed = new Set(columns.filter((column) => column.fixed).map((column) => column.key));

  const savedOrder = [...new Set(stringList(saved.order).filter((key) => known.has(key)))];
  const order = [...savedOrder, ...defaults.order.filter((key) => !savedOrder.includes(key))];

  let hidden = [...new Set(stringList(saved.hidden).filter((key) => known.has(key) && !fixed.has(key)))];
  // A grid with no data column visible is not useful, so a layout that hides every data column is discarded.
  const dataColumns = columns.filter((column) => !column.fixed).map((column) => column.key);
  if (dataColumns.every((key) => hidden.includes(key))) hidden = [];

  const pinned = [...new Set(stringList(saved.pinned).filter((key) => known.has(key) && !fixed.has(key)))];

  const widths: Record<string, number> = {};
  if (saved.widths && typeof saved.widths === "object") {
    for (const [key, width] of Object.entries(saved.widths as Record<string, unknown>)) {
      if (known.has(key) && typeof width === "number" && Number.isFinite(width)) widths[key] = clampGridWidth(width);
    }
  }

  return {
    order,
    hidden,
    widths,
    pinned,
    density: DENSITIES.includes(saved.density as GridDensity) ? (saved.density as GridDensity) : "comfortable",
  };
}

/** Columns in display order: pinned first, then the rest, hidden columns removed. */
export function arrangeGridColumns(columns: readonly GridColumnDef[], layout: GridLayout): GridColumnDef[] {
  const byKey = new Map(columns.map((column) => [column.key, column]));
  const hidden = new Set(layout.hidden);
  const pinned = new Set(layout.pinned);
  const ordered = layout.order
    .map((key) => byKey.get(key))
    .filter((column): column is GridColumnDef => column !== undefined && !hidden.has(column.key));
  return [...ordered.filter((column) => pinned.has(column.key)), ...ordered.filter((column) => !pinned.has(column.key))];
}

/** Shows or hides a column. The last visible column cannot be hidden, so the grid always has data. */
export function toggleColumnHidden(layout: GridLayout, columns: readonly GridColumnDef[], key: string): GridLayout {
  const column = columns.find((candidate) => candidate.key === key);
  if (!column || column.fixed) return layout;
  if (layout.hidden.includes(key)) {
    return { ...layout, hidden: layout.hidden.filter((hidden) => hidden !== key) };
  }
  // Count visible data columns only: fixed columns (such as actions) are not data.
  const visibleDataCount = columns.filter((candidate) => !candidate.fixed && !layout.hidden.includes(candidate.key)).length;
  if (visibleDataCount <= 1) return layout;
  return { ...layout, hidden: [...layout.hidden, key], pinned: layout.pinned.filter((pinned) => pinned !== key) };
}

/** Moves a column one place within the full order. Fixed columns do not move. */
export function moveColumn(layout: GridLayout, columns: readonly GridColumnDef[], key: string, direction: -1 | 1): GridLayout {
  const fixed = new Set(columns.filter((column) => column.fixed).map((column) => column.key));
  if (fixed.has(key)) return layout;
  const index = layout.order.indexOf(key);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= layout.order.length || fixed.has(layout.order[target])) return layout;
  const order = [...layout.order];
  [order[index], order[target]] = [order[target], order[index]];
  return { ...layout, order };
}

export function togglePinnedColumn(layout: GridLayout, columns: readonly GridColumnDef[], key: string): GridLayout {
  const column = columns.find((candidate) => candidate.key === key);
  if (!column || column.fixed) return layout;
  if (layout.pinned.includes(key)) return { ...layout, pinned: layout.pinned.filter((pinned) => pinned !== key) };
  return { ...layout, pinned: [...layout.pinned, key], hidden: layout.hidden.filter((hidden) => hidden !== key) };
}

export function setColumnWidth(layout: GridLayout, key: string, width: number): GridLayout {
  return { ...layout, widths: { ...layout.widths, [key]: clampGridWidth(width) } };
}

export function setGridDensity(layout: GridLayout, density: GridDensity): GridLayout {
  return { ...layout, density };
}

/**
 * Sorts rows by the grid's sort columns. Empty values sort last in both directions, so incomplete records do not jump to
 * the top. Text compares case-insensitively; numbers and dates compare numerically.
 */
export function sortGridRows<T>(
  rows: readonly T[],
  sortColumns: readonly SortColumn[],
  valueOf: (row: T, columnKey: string) => string | number | null,
): T[] {
  if (sortColumns.length === 0) return [...rows];
  const [primary] = sortColumns;
  const direction = primary.direction === "DESC" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const left = valueOf(a, primary.columnKey);
    const right = valueOf(b, primary.columnKey);
    if (left === null && right === null) return 0;
    if (left === null) return 1;
    if (right === null) return -1;
    if (typeof left === "number" && typeof right === "number") return (left - right) * direction;
    return String(left).localeCompare(String(right), undefined, { sensitivity: "base", numeric: true }) * direction;
  });
}

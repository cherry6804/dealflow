import { describe, expect, it } from "vitest";

import {
  arrangeGridColumns,
  clampGridWidth,
  createDefaultGridLayout,
  moveColumn,
  normalizeGridLayout,
  setColumnWidth,
  sortGridRows,
  toggleColumnHidden,
  togglePinnedColumn,
  type GridColumnDef,
} from "./gridLayout";

const COLUMNS: GridColumnDef[] = [
  { key: "name", label: "Contact", defaultWidth: 240 },
  { key: "email", label: "Email", defaultWidth: 200 },
  { key: "phone", label: "Phone", defaultWidth: 160, defaultVisible: false },
  { key: "actions", label: "Actions", defaultWidth: 80, fixed: true },
];

describe("grid layout model", () => {
  it("defaults to every column in order, with default-hidden columns hidden", () => {
    const layout = createDefaultGridLayout(COLUMNS);
    expect(layout.order).toEqual(["name", "email", "phone", "actions"]);
    expect(layout.hidden).toEqual(["phone"]);
    expect(arrangeGridColumns(COLUMNS, layout).map((column) => column.key)).toEqual(["name", "email", "actions"]);
  });

  it("drops unknown keys, adds new columns, and keeps at least one column visible", () => {
    const layout = normalizeGridLayout(
      { order: ["email", "ghost", "name"], hidden: ["name", "email", "actions", "ghost"], widths: { email: 9999, ghost: 5 } },
      COLUMNS,
    );
    expect(layout.order).toEqual(["email", "name", "phone", "actions"]);
    expect(layout.hidden).toEqual(["name", "email"]);
    expect(normalizeGridLayout({ hidden: ["name", "email", "phone"] }, COLUMNS).hidden).toEqual([]);
    expect(layout.widths).toEqual({ email: 720 });
  });

  it("never hides the last visible column or any fixed column", () => {
    let layout = createDefaultGridLayout(COLUMNS);
    layout = toggleColumnHidden(layout, COLUMNS, "name");
    layout = toggleColumnHidden(layout, COLUMNS, "email");
    expect(layout.hidden).toEqual(["phone", "name"]);
    expect(toggleColumnHidden(layout, COLUMNS, "actions")).toBe(layout);
  });

  it("moves a column one place and never moves a fixed column", () => {
    const layout = createDefaultGridLayout(COLUMNS);
    expect(moveColumn(layout, COLUMNS, "email", -1).order).toEqual(["email", "name", "phone", "actions"]);
    expect(moveColumn(layout, COLUMNS, "actions", -1)).toBe(layout);
  });

  it("shows pinned columns first and clamps widths to the allowed range", () => {
    let layout = togglePinnedColumn(createDefaultGridLayout(COLUMNS), COLUMNS, "email");
    expect(arrangeGridColumns(COLUMNS, layout).map((column) => column.key)).toEqual(["email", "name", "actions"]);
    layout = setColumnWidth(layout, "name", 10);
    expect(layout.widths.name).toBe(96);
    expect(clampGridWidth(Number.NaN)).toBe(96);
  });
});

describe("grid sorting", () => {
  const rows = [
    { id: "1", name: "bravo", score: 2 as number | null },
    { id: "2", name: "Alpha", score: null as number | null },
    { id: "3", name: "charlie", score: 10 as number | null },
  ];
  const value = (row: (typeof rows)[number], key: string) => (key === "score" ? row.score : row.name);

  it("sorts text case-insensitively and numbers numerically", () => {
    expect(sortGridRows(rows, [{ columnKey: "name", direction: "ASC" }], value).map((row) => row.id)).toEqual(["2", "1", "3"]);
    expect(sortGridRows(rows, [{ columnKey: "score", direction: "DESC" }], value).map((row) => row.id)).toEqual(["3", "1", "2"]);
  });

  it("keeps empty values last in both directions", () => {
    expect(sortGridRows(rows, [{ columnKey: "score", direction: "ASC" }], value).at(-1)?.id).toBe("2");
    expect(sortGridRows(rows, [{ columnKey: "score", direction: "DESC" }], value).at(-1)?.id).toBe("2");
  });
});

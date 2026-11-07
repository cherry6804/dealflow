import { describe, expect, it } from "vitest";

import {
  applyGridFilters,
  describeFilterCondition,
  isConditionComplete,
  normalizeFilterConditions,
  type GridFilterCondition,
  type GridFilterField,
} from "./gridFilters";

const FIELDS: GridFilterField[] = [
  { key: "name", label: "Name", type: "text" },
  { key: "stage", label: "Stage", type: "select", options: [{ value: "NEW", label: "New" }, { value: "WON", label: "Won" }] },
  { key: "created", label: "Created", type: "date" },
];

interface Row {
  id: string;
  name: string;
  stage: string | null;
  created: string | null;
}

const ROWS: Row[] = [
  { id: "1", name: "Asha Rao", stage: "NEW", created: "2026-01-05T10:00:00" },
  { id: "2", name: "Ben Ortiz", stage: "WON", created: "2026-02-10T10:00:00" },
  { id: "3", name: "Chen Li", stage: null, created: null },
];

const value = (row: Row, key: string): string | null => {
  if (key === "name") return row.name;
  if (key === "stage") return row.stage;
  if (key === "created") return row.created;
  return null;
};

function condition(id: string, field: string, operator: GridFilterCondition["operator"], text = ""): GridFilterCondition {
  return { id, field, operator, value: text };
}

describe("grid filter conditions", () => {
  it("applies text, select and date conditions together", () => {
    const result = applyGridFilters(ROWS, [condition("a", "name", "contains", "ORTIZ"), condition("b", "created", "after", "2026-01-31")], FIELDS, value);
    expect(result.map((row) => row.id)).toEqual(["2"]);
  });

  it("matches empty values only with is_empty, and treats them as not equal for is_not", () => {
    expect(applyGridFilters(ROWS, [condition("a", "stage", "is_empty")], FIELDS, value).map((row) => row.id)).toEqual(["3"]);
    expect(applyGridFilters(ROWS, [condition("a", "stage", "is_not", "NEW")], FIELDS, value).map((row) => row.id)).toEqual(["2", "3"]);
  });

  it("ignores incomplete conditions instead of hiding every row", () => {
    expect(applyGridFilters(ROWS, [condition("a", "stage", "is", "")], FIELDS, value)).toHaveLength(3);
    expect(applyGridFilters(ROWS, [condition("a", "missing", "is", "x")], FIELDS, value)).toHaveLength(3);
  });

  it("rejects an operator that does not fit the field type", () => {
    expect(isConditionComplete(condition("a", "stage", "before", "2026-01-01"), FIELDS)).toBe(false);
    expect(isConditionComplete(condition("a", "created", "is_empty"), FIELDS)).toBe(true);
  });

  it("drops stored conditions that are unknown or incomplete when they are read back", () => {
    const stored = [
      { id: "a", field: "stage", operator: "is", value: "WON" },
      { id: "b", field: "removed", operator: "is", value: "x" },
      { id: "c", field: "name", operator: "contains", value: "" },
      "garbage",
    ];
    expect(normalizeFilterConditions(stored, FIELDS)).toEqual([{ id: "a", field: "stage", operator: "is", value: "WON" }]);
    expect(normalizeFilterConditions("not a list", FIELDS)).toEqual([]);
  });

  it("describes a condition with its option label", () => {
    expect(describeFilterCondition(condition("a", "stage", "is", "WON"), FIELDS)).toBe("Stage is Won");
    expect(describeFilterCondition(condition("a", "created", "is_empty"), FIELDS)).toBe("Created is empty");
  });
});

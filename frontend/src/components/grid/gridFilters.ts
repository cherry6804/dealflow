/**
 * Pure filter model for the Sales grids and boards. A page declares the fields it can really filter on, with the operators each
 * field type supports. Conditions combine with AND. Nothing here reads storage or the network: the stored value is handled by
 * useGridFilters, so it belongs to one user in one organization.
 */

export type GridFilterFieldType = "text" | "select" | "date";

export type GridFilterOperator = "contains" | "is" | "is_not" | "is_empty" | "before" | "after";

export interface GridFilterOption {
  readonly value: string;
  readonly label: string;
}

export interface GridFilterField {
  readonly key: string;
  readonly label: string;
  readonly type: GridFilterFieldType;
  /** Choices for select fields. */
  readonly options?: readonly GridFilterOption[];
}

export interface GridFilterCondition {
  readonly id: string;
  readonly field: string;
  readonly operator: GridFilterOperator;
  /** Text, option value, or a yyyy-mm-dd day. Empty for is_empty. */
  readonly value: string;
}

export const GRID_FILTER_OPERATORS: Readonly<Record<GridFilterFieldType, readonly GridFilterOperator[]>> = {
  text: ["contains", "is_empty"],
  select: ["is", "is_not", "is_empty"],
  date: ["before", "after", "is_empty"],
};

export const GRID_FILTER_OPERATOR_LABELS: Readonly<Record<GridFilterOperator, string>> = {
  contains: "contains",
  is: "is",
  is_not: "is not",
  is_empty: "is empty",
  before: "is before",
  after: "is after",
};

export function operatorNeedsValue(operator: GridFilterOperator): boolean {
  return operator !== "is_empty";
}

/** Whether a condition can be applied: its field exists, its operator fits the field, and it has a value when one is needed. */
export function isConditionComplete(condition: GridFilterCondition, fields: readonly GridFilterField[]): boolean {
  const field = fields.find((item) => item.key === condition.field);
  if (!field || !GRID_FILTER_OPERATORS[field.type].includes(condition.operator)) return false;
  if (!operatorNeedsValue(condition.operator)) return true;
  return condition.value.trim().length > 0;
}

/** Keeps only complete conditions that refer to known fields. Stored values are untrusted, so this runs on every read. */
export function normalizeFilterConditions(value: unknown, fields: readonly GridFilterField[]): GridFilterCondition[] {
  if (!Array.isArray(value)) return [];
  const result: GridFilterCondition[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const raw = item as Record<string, unknown>;
    if (typeof raw.id !== "string" || typeof raw.field !== "string" || typeof raw.operator !== "string" || typeof raw.value !== "string") continue;
    const candidate: GridFilterCondition = {
      id: raw.id,
      field: raw.field,
      operator: raw.operator as GridFilterOperator,
      value: raw.value,
    };
    if (isConditionComplete(candidate, fields)) result.push(candidate);
  }
  return result;
}

/** Local yyyy-mm-dd day for an ISO timestamp, or null when it cannot be read. */
function dayKey(value: string): string | null {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** Whether one row's value satisfies one condition. Missing values match only is_empty, or is_not. */
export function matchesFilterCondition(raw: string | null, condition: GridFilterCondition, field: GridFilterField): boolean {
  const present = raw !== null && raw.trim().length > 0;
  switch (condition.operator) {
    case "is_empty":
      return !present;
    case "contains":
      return present && raw.toLowerCase().includes(condition.value.trim().toLowerCase());
    case "is":
      return present && raw === condition.value;
    case "is_not":
      return !present || raw !== condition.value;
    case "before":
    case "after": {
      if (!present || field.type !== "date") return false;
      const day = dayKey(raw);
      if (!day) return false;
      return condition.operator === "before" ? day < condition.value : day > condition.value;
    }
  }
}

/**
 * Applies all conditions to rows. valueOf returns the raw value for a row and field key: text and select fields return the
 * displayed or stored value, and date fields return an ISO timestamp.
 */
export function applyGridFilters<T>(
  rows: readonly T[],
  conditions: readonly GridFilterCondition[],
  fields: readonly GridFilterField[],
  valueOf: (row: T, fieldKey: string) => string | null,
): T[] {
  const usable = conditions.filter((condition) => isConditionComplete(condition, fields));
  if (usable.length === 0) return [...rows];
  return rows.filter((row) =>
    usable.every((condition) => {
      const field = fields.find((item) => item.key === condition.field);
      return field ? matchesFilterCondition(valueOf(row, condition.field), condition, field) : true;
    }),
  );
}

/** Human-readable text for a condition, used in active-filter chips. */
export function describeFilterCondition(condition: GridFilterCondition, fields: readonly GridFilterField[]): string {
  const field = fields.find((item) => item.key === condition.field);
  if (!field) return "";
  const operator = GRID_FILTER_OPERATOR_LABELS[condition.operator];
  if (!operatorNeedsValue(condition.operator)) return `${field.label} ${operator}`;
  const shown = field.type === "select" ? (field.options?.find((option) => option.value === condition.value)?.label ?? condition.value) : condition.value;
  return `${field.label} ${operator} ${shown}`;
}

let conditionSequence = 0;

/** A new, unique condition id. Ids only need to be unique within one filter list. */
export function newFilterConditionId(): string {
  conditionSequence += 1;
  return `c${Date.now().toString(36)}${conditionSequence.toString(36)}`;
}

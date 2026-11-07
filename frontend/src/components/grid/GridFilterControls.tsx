import { useRef, useState } from "react";
import { Filter, Plus, X } from "lucide-react";

import { AnchoredPopover } from "../ui/AnchoredPopover";
import { Button } from "../ui";
import {
  GRID_FILTER_OPERATOR_LABELS,
  GRID_FILTER_OPERATORS,
  describeFilterCondition,
  isConditionComplete,
  newFilterConditionId,
  operatorNeedsValue,
  type GridFilterCondition,
  type GridFilterField,
  type GridFilterOperator,
} from "./gridFilters";
import "./grid-layout.css";
import "./grid-filters.css";

interface GridFilterControlsProps {
  fields: readonly GridFilterField[];
  conditions: readonly GridFilterCondition[];
  /** Commits the conditions. Each call is one personal, saved change. */
  onApply: (next: GridFilterCondition[]) => void;
}

function blankCondition(field: GridFilterField): GridFilterCondition {
  return { id: newFilterConditionId(), field: field.key, operator: GRID_FILTER_OPERATORS[field.type][0], value: "" };
}

/**
 * The optional Filter control for a grid or board. It is a button in the toolbar that shows a count of active conditions. The
 * builder is a popover with one row per condition: field, operator and value, each limited to what the page's data supports.
 * Apply saves the conditions; Clear removes them all.
 */
export function GridFilterButton({ fields, conditions, onApply }: GridFilterControlsProps) {
  const anchorRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<GridFilterCondition[]>([]);
  const [error, setError] = useState("");

  if (fields.length === 0) return null;

  function openBuilder() {
    setDraft(conditions.length > 0 ? [...conditions] : []);
    setError("");
    setOpen(true);
  }

  function close() {
    setOpen(false);
    anchorRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }

  function updateRow(id: string, patch: Partial<GridFilterCondition>) {
    setDraft((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
    setError("");
  }

  function changeField(id: string, fieldKey: string) {
    const field = fields.find((item) => item.key === fieldKey);
    if (!field) return;
    updateRow(id, { field: fieldKey, operator: GRID_FILTER_OPERATORS[field.type][0], value: "" });
  }

  function apply() {
    const incomplete = draft.some((condition) => !isConditionComplete(condition, fields));
    if (incomplete) {
      setError("Choose a value for every filter, or remove it.");
      return;
    }
    onApply(draft);
    setOpen(false);
    anchorRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }

  function clearAll() {
    setDraft([]);
    onApply([]);
    setOpen(false);
  }

  const activeCount = conditions.length;

  return (
    <div ref={anchorRef} className="df-grid-filter-anchor">
      <Button
        variant="secondary"
        size="sm"
        icon={<Filter size={16} aria-hidden="true" />}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => (open ? close() : openBuilder())}
      >
        Filter
        {activeCount > 0 ? <span className="df-visually-hidden">, {activeCount} active</span> : null}
        {activeCount > 0 ? (
          <span className="df-grid-filter-count" aria-hidden="true">
            {activeCount}
          </span>
        ) : null}
      </Button>

      <AnchoredPopover open={open} anchorRef={anchorRef} label="Filter records" width={440} onClose={close}>
        <div className="df-grid-filter-builder">
          <header className="df-grid-picker-header">
            <div>
              <h2 className="df-grid-picker-title">Filter records</h2>
              <p className="df-grid-picker-description">Only fields this page can filter on are listed. Filters are saved to your account.</p>
            </div>
            <Button variant="tertiary" size="sm" iconOnly aria-label="Close filters" icon={<X size={16} aria-hidden="true" />} onClick={close}>
              Close
            </Button>
          </header>

          {draft.length === 0 ? <p className="df-grid-config-empty">No filters. Add one to narrow the records.</p> : null}

          <ul className="df-grid-filter-rows" aria-label="Filter conditions">
            {draft.map((condition, index) => {
              const field = fields.find((item) => item.key === condition.field) ?? fields[0];
              const operators = GRID_FILTER_OPERATORS[field.type];
              const number = index + 1;
              return (
                <li key={condition.id} className="df-grid-filter-row">
                  <select
                    className="df-input"
                    aria-label={`Field for filter ${number}`}
                    value={field.key}
                    onChange={(event) => changeField(condition.id, event.target.value)}
                  >
                    {fields.map((item) => (
                      <option key={item.key} value={item.key}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                  <select
                    className="df-input"
                    aria-label={`Operator for filter ${number}`}
                    value={condition.operator}
                    onChange={(event) => updateRow(condition.id, { operator: event.target.value as GridFilterOperator, value: "" })}
                  >
                    {operators.map((operator) => (
                      <option key={operator} value={operator}>
                        {GRID_FILTER_OPERATOR_LABELS[operator]}
                      </option>
                    ))}
                  </select>
                  {operatorNeedsValue(condition.operator) ? (
                    field.type === "select" ? (
                      <select
                        className="df-input"
                        aria-label={`Value for filter ${number}`}
                        value={condition.value}
                        onChange={(event) => updateRow(condition.id, { value: event.target.value })}
                      >
                        <option value="">Choose…</option>
                        {(field.options ?? []).map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        className="df-input"
                        type={field.type === "date" ? "date" : "text"}
                        aria-label={`Value for filter ${number}`}
                        placeholder={field.type === "text" ? "Type to match" : undefined}
                        value={condition.value}
                        onChange={(event) => updateRow(condition.id, { value: event.target.value })}
                      />
                    )
                  ) : (
                    <span className="df-grid-filter-novalue" aria-hidden="true">
                      —
                    </span>
                  )}
                  <Button
                    variant="tertiary"
                    size="sm"
                    iconOnly
                    aria-label={`Remove filter ${number}`}
                    icon={<X size={14} aria-hidden="true" />}
                    onClick={() => setDraft((current) => current.filter((item) => item.id !== condition.id))}
                  >
                    Remove
                  </Button>
                </li>
              );
            })}
          </ul>

          {error ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              {error}
            </p>
          ) : null}

          <div className="df-grid-filter-footer">
            <Button variant="secondary" size="sm" icon={<Plus size={14} aria-hidden="true" />} onClick={() => setDraft((current) => [...current, blankCondition(fields[0])])}>
              Add filter
            </Button>
            <div className="df-grid-filter-footer-end">
              <Button variant="tertiary" size="sm" onClick={clearAll} disabled={conditions.length === 0 && draft.length === 0}>
                Clear
              </Button>
              <Button variant="primary" size="sm" onClick={apply}>
                Apply
              </Button>
            </div>
          </div>
        </div>
      </AnchoredPopover>
    </div>
  );
}

/** Active-filter indicators: one removable chip per condition, and a clear-all action. Renders nothing when no filter is set. */
export function GridFilterChips({ fields, conditions, onApply }: GridFilterControlsProps) {
  if (conditions.length === 0) return null;
  return (
    <div className="df-grid-filter-chips" aria-label="Active filters">
      <ul className="df-grid-filter-chip-list">
        {conditions.map((condition) => {
          const label = describeFilterCondition(condition, fields);
          return (
            <li key={condition.id}>
              <span className="df-grid-filter-chip">
                <span>{label}</span>
                <button
                  type="button"
                  className="df-grid-filter-chip-remove"
                  aria-label={`Remove filter ${label}`}
                  onClick={() => onApply(conditions.filter((item) => item.id !== condition.id))}
                >
                  <X size={12} aria-hidden="true" />
                </button>
              </span>
            </li>
          );
        })}
      </ul>
      <Button variant="tertiary" size="sm" onClick={() => onApply([])}>
        Clear all filters
      </Button>
    </div>
  );
}

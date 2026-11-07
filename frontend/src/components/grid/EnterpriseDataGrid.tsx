import { useMemo, useRef, useState, type ReactNode } from "react";
import { DataGrid, type Column, type SortColumn } from "react-data-grid";
import "react-data-grid/lib/styles.css";
import { ChevronDown, ChevronUp, Pin, PinOff, SlidersHorizontal } from "lucide-react";

import { Button, Checkbox, RadioGroup } from "../ui";
import { useDismissOnOutside } from "../ui/useDismissOnOutside";
import { ErrorState, LoadingState, EmptyState } from "../shell/RouteStates";
import {
  GRID_ROW_HEIGHT,
  arrangeGridColumns,
  moveColumn,
  setColumnWidth,
  setGridDensity,
  sortGridRows,
  toggleColumnHidden,
  togglePinnedColumn,
  type GridColumnDef,
  type GridDensity,
  type GridLayout,
} from "./gridLayout";
import { useGridLayout } from "./useGridLayout";
import "./grid.css";

export type GridStatus = "loading" | "ready" | "error";

export interface EnterpriseDataGridProps<T> {
  /** Stable id for personal layout storage. One id per grid. */
  gridId: string;
  ariaLabel: string;
  columns: readonly GridColumnDef[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  /** Value used for sorting a column. Null sorts last. */
  sortValue: (row: T, columnKey: string) => string | number | null;
  /** Cell content for a column. */
  renderCell: (row: T, columnKey: string) => ReactNode;
  status: GridStatus;
  errorMessage?: string;
  onRetry?: () => void;
  searchValue: string;
  onSearchChange: (value: string) => void;
  searchLabel: string;
  searchPlaceholder: string;
  emptyTitle: string;
  emptyMessage: string;
  noMatchTitle: string;
  noMatchMessage: string;
  /** Primary create action, shown at the bottom of the grid. */
  createLabel?: string;
  onCreate?: () => void;
  onOpenRow?: (row: T) => void;
  /** Total records available for this view (for example, after server-side paging). */
  totalCount: number;
  /** Text describing the page of records shown, such as "Showing all 12 records". */
  rangeLabel: string;
}

/**
 * The shared Dealsflo data grid. It wraps react-data-grid and adds the shared toolbar (one search field, column
 * configuration), loading, empty, no-match and error states, and the footer with counts and the create action. Layout
 * (column order, visibility, widths, pinning and density) is personal and stored per user and organization.
 */
export function EnterpriseDataGrid<T>({
  gridId,
  ariaLabel,
  columns,
  rows,
  rowKey,
  sortValue,
  renderCell,
  status,
  errorMessage,
  onRetry,
  searchValue,
  onSearchChange,
  searchLabel,
  searchPlaceholder,
  emptyTitle,
  emptyMessage,
  noMatchTitle,
  noMatchMessage,
  createLabel,
  onCreate,
  onOpenRow,
  totalCount,
  rangeLabel,
}: EnterpriseDataGridProps<T>) {
  const { layout, update, resetLayout, available } = useGridLayout(gridId, columns);
  const [sortColumns, setSortColumns] = useState<SortColumn[]>([]);
  const [configOpen, setConfigOpen] = useState(false);
  const configRef = useRef<HTMLDivElement | null>(null);
  const configButtonRef = useRef<HTMLButtonElement | null>(null);
  useDismissOnOutside(configRef, configOpen, () => setConfigOpen(false));

  const visibleColumns = useMemo(() => arrangeGridColumns(columns, layout), [columns, layout]);
  const sortedRows = useMemo(() => sortGridRows(rows, sortColumns, sortValue), [rows, sortColumns, sortValue]);

  const gridColumns = useMemo<Column<T>[]>(
    () =>
      visibleColumns.map((column) => ({
        key: column.key,
        name: column.label,
        width: layout.widths[column.key] ?? column.defaultWidth,
        minWidth: 96,
        resizable: true,
        sortable: true,
        frozen: layout.pinned.includes(column.key),
        renderCell: ({ row }) => renderCell(row, column.key),
      })),
    [visibleColumns, layout.widths, layout.pinned, renderCell],
  );

  const rowHeight = GRID_ROW_HEIGHT[layout.density];
  const hasSearch = searchValue.trim().length > 0;
  // Rows arrive already filtered by the search, so an empty list with a search means "no match".
  const isEmpty = status === "ready" && rows.length === 0 && !hasSearch;
  const isNoMatch = status === "ready" && rows.length === 0 && hasSearch;

  function onColumnResize(column: { key: string }, width: number) {
    update(setColumnWidth(layout, column.key, width));
  }

  function onColumnsReorder(sourceKey: string, targetKey: string) {
    const from = layout.order.indexOf(sourceKey);
    const to = layout.order.indexOf(targetKey);
    if (from < 0 || to < 0 || from === to) return;
    const order = [...layout.order];
    const [moved] = order.splice(from, 1);
    order.splice(to, 0, moved);
    update({ ...layout, order });
  }

  return (
    <section className="df-grid" aria-label={ariaLabel}>
      <div className="df-grid-toolbar">
        <label className="df-grid-search">
          <span className="df-visually-hidden">{searchLabel}</span>
          <input
            type="search"
            className="df-input"
            value={searchValue}
            placeholder={searchPlaceholder}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>

        <div className="df-grid-config" ref={configRef}>
          <button
            ref={configButtonRef}
            type="button"
            className="df-btn df-btn--secondary df-btn--md"
            aria-haspopup="dialog"
            aria-expanded={configOpen}
            onClick={() => setConfigOpen((value) => !value)}
          >
            <SlidersHorizontal size={16} aria-hidden="true" />
            <span className="df-btn-label">Columns</span>
          </button>
          {configOpen ? (
            <ColumnConfigPanel
              columns={columns}
              layout={layout}
              onClose={() => {
                setConfigOpen(false);
                configButtonRef.current?.focus();
              }}
              onChange={update}
              onRestore={resetLayout}
            />
          ) : null}
        </div>
      </div>

      {status === "loading" ? <LoadingState title="Loading records" message="Fetching the latest records." /> : null}

      {status === "error" ? (
        <ErrorState
          title="Records could not be loaded"
          message={errorMessage ?? "Check your connection and try again."}
          retryLabel="Try again"
          onRetry={onRetry ?? (() => undefined)}
        />
      ) : null}

      {isEmpty && !hasSearch ? (
        <EmptyState
          title={emptyTitle}
          message={emptyMessage}
          action={
            onCreate && createLabel ? (
              <Button variant="primary" onClick={onCreate}>
                {createLabel}
              </Button>
            ) : null
          }
        />
      ) : null}

      {isNoMatch ? (
        <EmptyState
          title={noMatchTitle}
          message={noMatchMessage}
          action={
            <Button variant="secondary" onClick={() => onSearchChange("")}>
              Clear search
            </Button>
          }
        />
      ) : null}

      {status === "ready" && rows.length > 0 ? (
        <div className="df-grid-body">
          <DataGrid
            aria-label={ariaLabel}
            className="df-grid-table"
            columns={gridColumns}
            rows={sortedRows}
            rowKeyGetter={rowKey}
            rowHeight={rowHeight}
            headerRowHeight={rowHeight}
            sortColumns={sortColumns}
            onSortColumnsChange={setSortColumns}
            onColumnResize={onColumnResize}
            onColumnsReorder={onColumnsReorder}
            onCellClick={(args, event) => {
              if (!onOpenRow || args.column.key === "__actions") return;
              event.preventDefault();
              onOpenRow(args.row);
            }}
            defaultColumnOptions={{ resizable: true, sortable: true }}
            style={{ height: Math.min(rows.length * rowHeight + rowHeight, 640) }}
          />
        </div>
      ) : null}

      <footer className="df-grid-footer">
        <div className="df-grid-footer-start">
          {onCreate && createLabel ? (
            <Button variant="tertiary" icon={<span aria-hidden="true">+</span>} onClick={onCreate}>
              {createLabel}
            </Button>
          ) : null}
        </div>
        <p className="df-grid-footer-count" aria-live="polite">
          <strong>{totalCount}</strong> total
          {hasSearch ? <span> · {rows.length} match your search</span> : null}
          <span> · {rangeLabel}</span>
          {available ? null : <span className="df-grid-footer-note"> · Layout is not saved</span>}
        </p>
      </footer>
    </section>
  );
}

interface ColumnConfigPanelProps {
  columns: readonly GridColumnDef[];
  layout: GridLayout;
  onClose: () => void;
  onChange: (next: GridLayout) => void;
  onRestore: () => void;
}

const DENSITY_OPTIONS = [
  { value: "comfortable", label: "Comfortable" },
  { value: "compact", label: "Compact" },
];

function ColumnConfigPanel({ columns, layout, onClose, onChange, onRestore }: ColumnConfigPanelProps) {
  const byKey = new Map(columns.map((column) => [column.key, column]));
  const orderedKeys = layout.order.filter((key) => byKey.has(key));
  const panelRef = useRef<HTMLDivElement | null>(null);

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="Configure columns"
      className="df-grid-config-panel"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
        }
      }}
    >
      <p className="df-grid-config-heading">Columns</p>
      <ul className="df-grid-config-list">
        {orderedKeys.map((key, index) => {
          const column = byKey.get(key);
          if (!column) return null;
          const hidden = layout.hidden.includes(key);
          const pinned = layout.pinned.includes(key);
          return (
            <li key={key} className="df-grid-config-row">
              <Checkbox
                label={`Show ${column.label}`}
                labelHidden
                checked={!hidden}
                disabled={column.fixed}
                onChange={() => onChange(toggleColumnHidden(layout, columns, key))}
              />
              <span className="df-grid-config-name">{column.label}</span>
              <Button
                variant="tertiary"
                size="sm"
                iconOnly
                aria-label={pinned ? `Unpin ${column.label}` : `Pin ${column.label}`}
                aria-pressed={pinned}
                disabled={column.fixed || hidden}
                icon={pinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />}
                onClick={() => onChange(togglePinnedColumn(layout, columns, key))}
              >
                {pinned ? "Unpin" : "Pin"}
              </Button>
              <Button
                variant="tertiary"
                size="sm"
                iconOnly
                aria-label={`Move ${column.label} up`}
                disabled={index === 0 || column.fixed}
                icon={<ChevronUp size={14} aria-hidden="true" />}
                onClick={() => onChange(moveColumn(layout, columns, key, -1))}
              >
                Up
              </Button>
              <Button
                variant="tertiary"
                size="sm"
                iconOnly
                aria-label={`Move ${column.label} down`}
                disabled={index === orderedKeys.length - 1 || column.fixed}
                icon={<ChevronDown size={14} aria-hidden="true" />}
                onClick={() => onChange(moveColumn(layout, columns, key, 1))}
              >
                Down
              </Button>
            </li>
          );
        })}
      </ul>

      <div className="df-grid-config-density">
        <RadioGroup
          name="grid-density"
          label="Row density"
          value={layout.density}
          options={DENSITY_OPTIONS}
          onChange={(value) => onChange(setGridDensity(layout, value as GridDensity))}
        />
      </div>

      <div className="df-grid-config-footer">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            onRestore();
          }}
        >
          Restore default columns
        </Button>
      </div>
    </div>
  );
}


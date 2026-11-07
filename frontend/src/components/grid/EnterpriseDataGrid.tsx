import { useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { DataGrid, type Column, type SortColumn } from "react-data-grid";
import "react-data-grid/lib/styles.css";
import { ChevronDown, ChevronUp, Pin, PinOff, RotateCcw, Search, SlidersHorizontal, X } from "lucide-react";

import { AnchoredPopover } from "../ui/AnchoredPopover";
import { Button, Checkbox, RadioGroup } from "../ui";
import { ErrorState, LoadingState, EmptyState } from "../shell/RouteStates";
import {
  GRID_ROW_HEIGHT,
  arrangeGridColumns,
  fitColumnWidths,
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
import { useMeasuredWidth } from "./useMeasuredWidth";
import "./grid.css";
import "./grid-layout.css";

export type GridStatus = "loading" | "ready" | "error";

/** Width of the utility gutter at the far right of the header, holding the column configuration control. */
const UTILITY_WIDTH = 40;

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
  /** Entity-specific create action, shown at the left of the footer inside the grid. */
  createLabel?: string;
  onCreate?: () => void;
  onOpenRow?: (row: T) => void;
  /** Reloads the records from the existing API. */
  onRefresh?: () => void;
  /** Total records available for this view. */
  totalCount: number;
  /** Describes the records shown, for example "All records" or "Filtered". */
  rangeLabel: string;
}

/**
 * The shared Dealsflo data grid. One bordered container holds three sections that share the same column layout: the header
 * (sortable labels; the column configuration control sits at its far-right end in a narrow utility gutter, not as a data
 * column), the scrollable body, and the footer (Create at the left; counts and refresh at the right). Columns stretch to the
 * available width, and horizontal scrolling stays inside the grid. The column picker is an anchored popover rendered in a
 * portal, so the grid's overflow never clips it. Layout is personal, per user and organization.
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
  onRefresh,
  totalCount,
  rangeLabel,
}: EnterpriseDataGridProps<T>) {
  const { layout, update, resetLayout, available } = useGridLayout(gridId, columns);
  const [sortColumns, setSortColumns] = useState<SortColumn[]>([]);
  const [configOpen, setConfigOpen] = useState(false);
  const configButtonRef = useRef<HTMLButtonElement | null>(null);
  const [measureRef, measuredWidth] = useMeasuredWidth(1200);

  const visibleColumns = useMemo(() => arrangeGridColumns(columns, layout), [columns, layout]);
  const sortedRows = useMemo(() => sortGridRows(rows, sortColumns, sortValue), [rows, sortColumns, sortValue]);

  // Columns stretch to the available width (the utility gutter is excluded), so the grid uses the space it has.
  const gridColumns = useMemo<Column<T>[]>(() => {
    const widths = fitColumnWidths(
      visibleColumns.map((column) => layout.widths[column.key] ?? column.defaultWidth),
      Math.max(0, measuredWidth - UTILITY_WIDTH),
    );
    return visibleColumns.map((column, index) => ({
      key: column.key,
      name: column.label,
      width: widths[index],
      minWidth: 96,
      resizable: true,
      sortable: true,
      frozen: layout.pinned.includes(column.key),
      renderCell: ({ row }) => renderCell(row, column.key),
    }));
  }, [visibleColumns, layout.widths, layout.pinned, renderCell, measuredWidth]);

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

  function closeConfig() {
    setConfigOpen(false);
    configButtonRef.current?.focus();
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

      {isEmpty ? (
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
        <div
          ref={measureRef}
          className="df-grid-frame"
          style={{ "--df-grid-header-height": `${rowHeight}px` } as CSSProperties}
        >
          <div className="df-grid-main">
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
                  if (!onOpenRow) return;
                  event.preventDefault();
                  onOpenRow(args.row);
                }}
                defaultColumnOptions={{ resizable: true, sortable: true }}
                style={{ height: Math.min(rows.length * rowHeight + rowHeight, 640) }}
              />
            </div>
            <div className="df-grid-utility">
              <button
                ref={configButtonRef}
                type="button"
                className="df-grid-config-trigger"
                aria-label="Configure columns"
                title="Configure columns"
                aria-haspopup="dialog"
                aria-expanded={configOpen}
                onClick={() => setConfigOpen((value) => !value)}
              >
                <SlidersHorizontal size={16} aria-hidden="true" />
              </button>
            </div>
          </div>

          <AnchoredPopover open={configOpen} anchorRef={configButtonRef} label="Configure columns" width={360} onClose={closeConfig}>
            <ColumnConfigPanel
              columns={columns}
              layout={layout}
              onClose={closeConfig}
              onChange={update}
              onRestore={() => resetLayout()}
            />
          </AnchoredPopover>

          <footer className="df-grid-footer">
            <div className="df-grid-footer-start">
              {onCreate && createLabel ? (
                <Button variant="tertiary" size="sm" icon={<span aria-hidden="true">+</span>} onClick={onCreate}>
                  {createLabel}
                </Button>
              ) : null}
            </div>
            <div className="df-grid-footer-end">
              <p className="df-grid-footer-count" aria-live="polite">
                <strong>{totalCount}</strong> total
                {hasSearch ? <span> · {rows.length} match</span> : null}
                <span> · {rangeLabel}</span>
                {available ? null : <span className="df-grid-footer-note"> · Layout not saved</span>}
              </p>
              {onRefresh ? (
                <Button variant="tertiary" size="sm" iconOnly aria-label="Refresh records" onClick={onRefresh} icon={<RotateCcw size={14} aria-hidden="true" />}>
                  Refresh
                </Button>
              ) : null}
            </div>
          </footer>
        </div>
      ) : null}
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

/**
 * Column configuration picker, shown in an AnchoredPopover. It has a title, a close control, a search field for column names,
 * one row per configurable column (checked means visible), move and pin controls for keyboard and touch users, row density,
 * and reset and done actions. Changes apply to the grid immediately.
 */
function ColumnConfigPanel({ columns, layout, onClose, onChange, onRestore }: ColumnConfigPanelProps) {
  const [query, setQuery] = useState("");
  const byKey = new Map(columns.map((column) => [column.key, column]));
  const orderedKeys = layout.order.filter((key) => byKey.has(key));
  const needle = query.trim().toLowerCase();
  const matchingKeys = orderedKeys.filter((key) => (byKey.get(key)?.label ?? "").toLowerCase().includes(needle));
  const configurable = columns.filter((column) => !column.fixed);
  const visibleCount = configurable.filter((column) => !layout.hidden.includes(column.key)).length;

  return (
    <div className="df-grid-picker">
      <header className="df-grid-picker-header">
        <div>
          <h2 className="df-grid-picker-title">Configure columns</h2>
          <p className="df-grid-picker-description">Show, hide and reorder columns. Saved to your account on this browser.</p>
        </div>
        <Button variant="tertiary" size="sm" iconOnly aria-label="Close column settings" icon={<X size={16} aria-hidden="true" />} onClick={onClose}>
          Close
        </Button>
      </header>

      <div className="df-grid-config-search">
        <Search size={14} aria-hidden="true" />
        <input
          type="search"
          className="df-grid-config-input"
          aria-label="Search columns"
          placeholder="Search columns"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <p className="df-grid-config-heading">
        {visibleCount} of {configurable.length} columns visible
      </p>

      <ul className="df-grid-config-list" aria-label="Available columns">
        {matchingKeys.length === 0 ? <li className="df-grid-config-empty">No column matches the search.</li> : null}
        {matchingKeys.map((key) => {
          const column = byKey.get(key);
          if (!column) return null;
          const index = layout.order.indexOf(key);
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
                disabled={index <= 0 || column.fixed}
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

      <footer className="df-grid-config-footer">
        <Button variant="secondary" size="sm" onClick={onRestore}>
          Reset to defaults
        </Button>
        <Button variant="primary" size="sm" onClick={onClose}>
          Done
        </Button>
      </footer>
    </div>
  );
}

import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext, type AppContextValue } from "../../contexts/appContextDefinition";
import { EnterpriseDataGrid, type EnterpriseDataGridProps } from "./EnterpriseDataGrid";
import type { GridColumnDef } from "./gridLayout";

interface Row {
  id: string;
  name: string;
  email: string;
}

const COLUMNS: GridColumnDef[] = [
  { key: "name", label: "Contact", defaultWidth: 220 },
  { key: "email", label: "Email", defaultWidth: 240 },
];

const ROWS: Row[] = [
  { id: "1", name: "Asha Rao", email: "asha@example.com" },
  { id: "2", name: "Ben Ortiz", email: "ben@example.com" },
];

function session(userId: string | null): AppContextValue {
  return {
    user: userId ? { id: userId, email: `${userId}@example.com`, display_name: userId } : null,
    organizations: [{ id: "org-1", name: "Acme" }],
    selectedOrganization: { id: "org-1", name: "Acme" },
    status: "authenticated",
    error: null,
    selectOrganization: vi.fn(),
    refreshOrganizations: vi.fn(async () => undefined),
    refreshSession: vi.fn(async () => undefined),
    signOut: vi.fn(async () => undefined),
  };
}

function gridProps(overrides: Partial<EnterpriseDataGridProps<Row>> = {}): EnterpriseDataGridProps<Row> {
  return {
    gridId: "test",
    ariaLabel: "Test records",
    columns: COLUMNS,
    rows: ROWS,
    rowKey: (row) => row.id,
    sortValue: (row, key) => (key === "email" ? row.email : row.name),
    renderCell: (row, key) => (key === "email" ? row.email : row.name),
    status: "ready",
    searchValue: "",
    onSearchChange: vi.fn(),
    searchLabel: "Search records",
    searchPlaceholder: "Search records",
    emptyTitle: "No records yet",
    emptyMessage: "Add the first record.",
    noMatchTitle: "No records match",
    noMatchMessage: "Try another search.",
    createLabel: "Add record",
    onCreate: vi.fn(),
    onOpenRow: vi.fn(),
    totalCount: ROWS.length,
    rangeLabel: "Showing all records",
    ...overrides,
  };
}

function renderGrid(props: EnterpriseDataGridProps<Row>, user: string | null = "alice") {
  return render(
    <AppContext.Provider value={session(user)}>
      <EnterpriseDataGrid<Row> {...props} />
    </AppContext.Provider>,
  );
}

describe("EnterpriseDataGrid", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // jsdom has no layout. Give the grid a viewport so the header renders every column, including the configuration cell.
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1200 });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 600 });
  });

  it("shows the loading state while records load", () => {
    renderGrid(gridProps({ status: "loading", rows: [] }));
    expect(screen.getByText("Loading records")).toBeTruthy();
  });

  it("shows an error with retry", () => {
    const onRetry = vi.fn();
    renderGrid(gridProps({ status: "error", rows: [], onRetry }));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("shows an empty state with the create action when there are no records", () => {
    const onCreate = vi.fn();
    renderGrid(gridProps({ rows: [], totalCount: 0, onCreate }));
    expect(screen.getByRole("heading", { name: "No records yet" })).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Add record" })[0]);
    expect(onCreate).toHaveBeenCalled();
  });

  it("shows a no-match state with a clear-search action when a search finds nothing", () => {
    const onSearchChange = vi.fn();
    renderGrid(gridProps({ rows: [], searchValue: "zzz", onSearchChange }));
    expect(screen.getByRole("heading", { name: "No records match" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(onSearchChange).toHaveBeenCalledWith("");
  });

  it("has one search field and reports the total and range", () => {
    renderGrid(gridProps());
    expect(screen.getAllByRole("searchbox")).toHaveLength(1);
    expect(screen.getByText(/Showing all records/)).toBeTruthy();
  });

  it("hides a column from the column panel, and the change stays with that user", () => {
    const { unmount } = renderGrid(gridProps(), "alice");
    fireEvent.click(screen.getByRole("button", { name: "Configure columns" }));
    const panel = screen.getByRole("dialog", { name: "Configure columns" });
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Show Email" }));
    expect((within(panel).getByRole("checkbox", { name: "Show Email" }) as HTMLInputElement).checked).toBe(false);
    unmount();

    renderGrid(gridProps(), "bob");
    fireEvent.click(screen.getByRole("button", { name: "Configure columns" }));
    expect((screen.getByRole("checkbox", { name: "Show Email" }) as HTMLInputElement).checked).toBe(true);
  });

  it("filters the column list by name in the picker and keeps the search field focused", () => {
    renderGrid(gridProps());
    fireEvent.click(screen.getByRole("button", { name: "Configure columns" }));
    const panel = screen.getByRole("dialog", { name: "Configure columns" });
    const search = within(panel).getByRole("searchbox", { name: "Search columns" });
    search.focus();
    fireEvent.change(search, { target: { value: "email" } });
    expect(within(panel).getByText("Email", { selector: "span.df-grid-config-name" })).toBeTruthy();
    expect(within(panel).queryByText("Contact", { selector: "span.df-grid-config-name" })).toBeNull();
    expect(document.activeElement).toBe(search);
  });

  it("opens a row on click and offers the create action at the bottom", () => {
    const onOpenRow = vi.fn();
    renderGrid(gridProps({ onOpenRow }));
    fireEvent.click(screen.getByText("Asha Rao"));
    expect(onOpenRow).toHaveBeenCalledWith(ROWS[0]);
    expect(screen.getAllByRole("button", { name: "Add record" }).length).toBeGreaterThan(0);
  });
});

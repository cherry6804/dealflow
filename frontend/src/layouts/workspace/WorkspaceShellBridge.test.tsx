import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext, type AppContextValue } from "../../contexts/appContextDefinition";
import { ThemeProvider } from "../../theme/ThemeProvider";
import { notificationApi } from "../../services/notificationApi";
import WorkspaceShellBridge from "./WorkspaceShellBridge";

vi.mock("../../services/notificationApi", () => ({
  notificationApi: {
    list: vi.fn(async () => ({ items: [], total: 0, unread_count: 2, limit: 10, offset: 0 })),
    unreadCount: vi.fn(async () => ({ unread_count: 2 })),
    markRead: vi.fn(async () => ({})),
    markAllRead: vi.fn(async () => ({ updated_count: 0 })),
  },
}));

function contextValue(overrides: Partial<AppContextValue> = {}): AppContextValue {
  return {
    user: { id: "user-1", email: "elena@example.com", display_name: "Elena Ruiz" },
    organizations: [
      { id: "org-1", name: "Acme Realty" },
      { id: "org-2", name: "Northwind Capital" },
    ],
    selectedOrganization: { id: "org-1", name: "Acme Realty" },
    status: "authenticated",
    error: null,
    selectOrganization: vi.fn(),
    refreshOrganizations: vi.fn(async () => undefined),
    refreshSession: vi.fn(async () => undefined),
    signOut: vi.fn(async () => undefined),
    ...overrides,
  };
}

function renderBridge(value: AppContextValue, path = "/deals") {
  return render(
    <ThemeProvider>
      <AppContext.Provider value={value}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route element={<WorkspaceShellBridge />}>
              <Route path="/deals" element={<h1>Deals page</h1>} />
              <Route path="/leads" element={<h1>Leads page</h1>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AppContext.Provider>
    </ThemeProvider>,
  );
}

describe("WorkspaceShellBridge", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("renders the routed page inside the shell and marks the active module", () => {
    renderBridge(contextValue());
    expect(screen.getByRole("heading", { name: "Deals page" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Deals" }).getAttribute("aria-current")).toBe("page");
  });

  it("switches organizations through the existing context", () => {
    const value = contextValue();
    renderBridge(value);
    fireEvent.click(screen.getByRole("button", { name: /Organization:/ }));
    fireEvent.click(screen.getByRole("option", { name: "Northwind Capital" }));
    expect(value.selectOrganization).toHaveBeenCalledWith("org-2");
  });

  it("signs out through the existing context", async () => {
    const value = contextValue();
    renderBridge(value);
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(value.signOut).toHaveBeenCalledTimes(1));
  });

  it("shows the unread count from the notifications API before the panel is opened", async () => {
    renderBridge(contextValue());
    expect(await screen.findByRole("button", { name: "Notifications, 2 unread" })).toBeTruthy();
    expect(notificationApi.unreadCount).toHaveBeenCalled();
  });

  it("persists the sidebar collapse for the current organization and user", () => {
    renderBridge(contextValue());
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    const stored = Object.keys(window.localStorage).filter((key) => key.includes("org-1"));
    expect(stored.length).toBeGreaterThan(0);
  });
});

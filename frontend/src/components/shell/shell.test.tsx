import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { Home, Target } from "lucide-react";

import type { SidebarSections } from "../../layouts/workspace/sidebarSections";
import type { WorkspaceModule } from "../../layouts/workspace/workspaceSpaces";
import { ThemeProvider } from "../../theme/ThemeProvider";
import { AppShell, type AppShellLabels } from "./AppShell";
import { CommandPalette } from "./CommandPalette";
import { NotificationsMenu, type NotificationEntry, type NotificationsMenuLabels } from "./NotificationsMenu";
import { OrganizationSwitcher, type OrganizationSwitcherLabels } from "./HeaderMenus";
import {
  buildBreadcrumbs,
  filterCommands,
  filterVisibleModules,
  isRouteActive,
  withBasePath,
  type ShellCommand,
} from "./shellModel";

const deals: WorkspaceModule = { label: "Deals", to: "/deals", icon: Target };
const overview: WorkspaceModule = { label: "Overview", to: "/", icon: Home };
const leads: WorkspaceModule = { label: "Leads", to: "/leads", icon: Target };

const sections: SidebarSections = {
  pinned: [],
  global: [overview],
  spaces: [{ space: { id: "sales", label: "Sales", icon: Target, moduleLabels: [] }, expanded: true, modules: [deals, leads] }],
};

const labels: AppShellLabels = {
  productName: "Dealsflo",
  skipToContent: "Skip to content",
  mainNavigation: "Main navigation",
  navigationTitle: "Navigation",
  openNavigation: "Open navigation",
  closeNavigation: "Close navigation",
  collapseSidebar: "Collapse navigation",
  expandSidebar: "Expand navigation",
  showSidebar: "Show navigation",
  search: "Search",
  searchShortcut: "Ctrl K",
  homeBreadcrumb: "Home",
  breadcrumbs: "Breadcrumbs",
  pinnedGroup: "Pinned",
  globalGroup: "Workspace",
  closeLabel: "Close",
  palette: {
    title: "Search and commands",
    description: "Find a module or run a command.",
    closeLabel: "Close search",
    placeholder: "Search modules and commands",
    listLabel: "Results",
    empty: "No matches",
  },
  organization: {
    trigger: "Organization",
    listLabel: "Organizations",
    current: "Current",
    loading: "Loading organizations",
    error: "Organizations could not be loaded",
    retry: "Try again",
    empty: "No organizations",
  },
  notifications: {
    trigger: "Notifications",
    panelTitle: "Notifications",
    unreadLabel: "Unread",
    unreadCountLabel: (count) => `${count} unread`,
    markRead: "Mark as read",
    markAllRead: "Mark all as read",
    loading: "Loading notifications",
    loadingMessage: "Fetching your latest updates.",
    emptyTitle: "You are all caught up",
    emptyMessage: "New notifications appear here.",
    errorTitle: "Notifications could not be loaded",
    errorMessage: "Check your connection and try again.",
    retry: "Try again",
  },
  profile: { trigger: "Account", settings: "Settings", signOut: "Sign out", signingOut: "Signing out" },
};

function shellProps(overrides: Partial<Parameters<typeof AppShell>[0]> = {}) {
  return {
    labels,
    pathname: "/deals",
    modules: [overview, deals, leads],
    sections,
    canAccess: () => true,
    commands: [] as ShellCommand[],
    user: { name: "Elena Ruiz", email: "elena@example.com", initials: "ER" },
    signingOut: false,
    onSignOut: vi.fn(),
    onOpenSettings: vi.fn(),
    organizations: [{ id: "a", name: "Acme" }, { id: "b", name: "Northwind" }],
    selectedOrganizationId: "a",
    organizationStatus: "ready" as const,
    onSelectOrganization: vi.fn(),
    onRetryOrganizations: vi.fn(),
    notifications: {
      load: vi.fn(async () => []),
      unreadCount: vi.fn(async () => 0),
      markRead: vi.fn(async () => undefined),
      markAllRead: vi.fn(async () => undefined),
    },
    sidebarCollapsed: false,
    onSidebarCollapsedChange: vi.fn(),
    onToggleSpace: vi.fn(),
    children: <p>Page body</p>,
    ...overrides,
  };
}

function renderShell(overrides: Partial<Parameters<typeof AppShell>[0]> = {}) {
  const props = shellProps(overrides);
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[props.pathname]}>
        <AppShell {...props} />
      </MemoryRouter>
    </ThemeProvider>,
  );
  return props;
}

describe("shell model", () => {
  it("matches routes exactly for the root and by prefix for others", () => {
    expect(isRouteActive("/", "/")).toBe(true);
    expect(isRouteActive("/deals/123", "/")).toBe(false);
    expect(isRouteActive("/deals/123", "/deals")).toBe(true);
    expect(isRouteActive("/dealsx", "/deals")).toBe(false);
  });

  it("prefixes preview routes without changing production routes", () => {
    expect(withBasePath("/deals", "/design-system/shell")).toBe("/design-system/shell/deals");
    expect(withBasePath("/", "/design-system/shell")).toBe("/design-system/shell");
    expect(withBasePath("/deals")).toBe("/deals");
  });

  it("builds breadcrumbs with the current page unlinked", () => {
    const crumbs = buildBreadcrumbs("/deals/9", [overview, deals], "Home");
    expect(crumbs).toEqual([{ label: "Home", to: "/" }, { label: "Deals" }]);
  });

  it("hides modules whose permission is not granted and keeps ungated modules", () => {
    expect(filterVisibleModules([overview, deals], () => false)).toEqual([overview, deals]);
  });

  it("filters commands, ranking prefix matches first", () => {
    const commands: ShellCommand[] = [
      { id: "1", label: "Open leads", group: "Navigate", run: () => undefined },
      { id: "2", label: "Leads report", group: "Navigate", run: () => undefined },
      { id: "3", label: "Settings", group: "Navigate", keywords: "preferences leads", run: () => undefined },
    ];
    expect(filterCommands(commands, "leads").map((command) => command.id)).toEqual(["2", "1", "3"]);
    expect(filterCommands(commands, "  ")).toHaveLength(3);
    expect(filterCommands(commands, "zzz")).toHaveLength(0);
  });
});

describe("AppShell", () => {
  it("marks the active route with aria-current", () => {
    renderShell();
    const active = screen.getByRole("link", { name: "Deals" });
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(screen.queryByRole("navigation", { name: "Breadcrumbs" })).toBeNull();
  });

  it("hides the sidebar with the header toggle in one click", () => {
    const onSidebarHiddenChange = vi.fn();
    renderShell({ onSidebarHiddenChange });
    fireEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    expect(onSidebarHiddenChange).toHaveBeenCalledWith(true);
  });

  it("toggles a space disclosure and exposes its expanded state", () => {
    const props = renderShell();
    const toggle = screen.getByRole("button", { name: "Sales" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(props.onToggleSpace).toHaveBeenCalledWith("sales");
  });

  it("opens the palette with Ctrl+K and hides commands the user cannot run", () => {
    const commands: ShellCommand[] = [
      { id: "open-deals", label: "Open deals", group: "Navigate", run: () => undefined },
      { id: "admin", label: "Open admin console", group: "Navigate", permission: "admin:view", run: () => undefined },
    ];
    renderShell({ commands, canAccess: (permission) => permission !== "admin:view" });
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    const list = screen.getByRole("listbox", { name: "Results" });
    expect(list.textContent).toContain("Open deals");
    expect(list.textContent).not.toContain("Open admin console");
  });

  it("opens the palette on '/' outside text fields but not inside them", () => {
    renderShell({ children: <input aria-label="Field" /> });
    const dialog = document.querySelector("dialog");
    const field = screen.getByRole("textbox", { name: "Field" });
    field.focus();
    fireEvent.keyDown(field, { key: "/" });
    expect(dialog?.open).toBe(false);
    fireEvent.keyDown(document.body, { key: "/" });
    expect(dialog?.open).toBe(true);
  });
});

describe("CommandPalette", () => {
  const commands: ShellCommand[] = [
    { id: "a", label: "Open deals", group: "Navigate", run: vi.fn() },
    { id: "b", label: "Open leads", group: "Navigate", run: vi.fn() },
  ];

  it("moves the active option with arrow keys and runs it on Enter", () => {
    const onClose = vi.fn();
    render(<CommandPalette open onClose={onClose} commands={commands} labels={labels.palette} />);
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toContain("b");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(commands[1].run).toHaveBeenCalledTimes(1);
  });

  it("shows the empty message when nothing matches", () => {
    render(<CommandPalette open onClose={() => undefined} commands={commands} labels={labels.palette} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzz" } });
    expect(screen.getByRole("status").textContent).toBe("No matches");
  });
});

describe("NotificationsMenu", () => {
  const notificationLabels: NotificationsMenuLabels = labels.notifications;
  const entries: NotificationEntry[] = [
    { id: "1", title: "Deal won", message: "Meridian closed", createdAt: "2026-11-07T09:00:00Z", read: false },
    { id: "2", title: "Visit booked", message: "Tomorrow 10:00", createdAt: "2026-11-07T08:00:00Z", read: true },
  ];

  it("loads when opened, shows the unread count and marks one item read", async () => {
    const markRead = vi.fn(async () => undefined);
    render(
      <NotificationsMenu labels={notificationLabels} load={async () => entries} markRead={markRead} unreadCount={async () => 1} markAllRead={async () => undefined} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("Deal won")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Notifications, 1 unread" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mark as read" }));
    await waitFor(() => expect(markRead).toHaveBeenCalledWith("1"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Mark as read" })).toBeNull());
  });

  it("shows an error with a retry that reloads the list", async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(entries);
    render(<NotificationsMenu labels={notificationLabels} load={load} markRead={async () => undefined} unreadCount={async () => 0} markAllRead={async () => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Deal won")).toBeTruthy();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("shows the empty state when there are no notifications", async () => {
    render(<NotificationsMenu labels={notificationLabels} load={async () => []} markRead={async () => undefined} unreadCount={async () => 0} markAllRead={async () => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("You are all caught up")).toBeTruthy();
  });
});

describe("OrganizationSwitcher", () => {
  const orgLabels: OrganizationSwitcherLabels = labels.organization;

  it("selects another organization and does not call onSelect for the current one", () => {
    const onSelect = vi.fn();
    render(
      <OrganizationSwitcher
        labels={orgLabels}
        organizations={[{ id: "a", name: "Acme" }, { id: "b", name: "Northwind" }]}
        selectedId="a"
        status="ready"
        onSelect={onSelect}
        onRetry={() => undefined}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Organization/ }));
    act(() => {
      fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowDown" });
    });
    fireEvent.keyDown(screen.getByRole("listbox"), { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("b");
  });

  it("shows a retry when organizations fail to load", () => {
    const onRetry = vi.fn();
    render(
      <OrganizationSwitcher labels={orgLabels} organizations={[]} selectedId={null} status="error" onSelect={() => undefined} onRetry={onRetry} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Organization/ }));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("outside-click dismissal and permission-gated navigation", () => {
  it("closes the notifications panel on a press outside it", async () => {
    render(
      <NotificationsMenu
        labels={labels.notifications}
        load={async () => []}
        markRead={async () => undefined}
        unreadCount={async () => 0} markAllRead={async () => undefined}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("You are all caught up")).toBeTruthy();
    fireEvent.pointerDown(document.body);
    await waitFor(() => expect(screen.queryByText("You are all caught up")).toBeNull());
  });

  it("hides a module the user cannot access from the sidebar", () => {
    renderShell({
      canAccess: (permission) => permission !== "deals:view",
      permissionByModule: { Deals: "deals:view" },
    });
    expect(screen.queryByRole("link", { name: "Deals" })).toBeNull();
    expect(screen.getByRole("link", { name: "Leads" })).toBeTruthy();
  });
});

describe("sidebar hidden and resize", () => {
  it("removes the sidebar when hidden and restores it from the header", () => {
    const onSidebarHiddenChange = vi.fn();
    renderShell({ sidebarHidden: true, onSidebarHiddenChange });
    expect(document.querySelector(".df-shell-sidebar")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show navigation" }));
    expect(onSidebarHiddenChange).toHaveBeenCalledWith(false);
  });

  it("keeps the header's space content available while the sidebar is hidden", () => {
    renderShell({ sidebarHidden: true });
    expect(screen.getByText("Page body")).toBeTruthy();
  });

  it("resizes with the keyboard in 8px steps and resets with Home", () => {
    const onSidebarWidthChange = vi.fn();
    const onSidebarWidthReset = vi.fn();
    renderShell({ sidebarWidth: 208, onSidebarWidthChange, onSidebarWidthReset });
    const handle = screen.getByRole("separator", { name: /Resize sidebar/ });
    expect(handle.getAttribute("aria-valuenow")).toBe("208");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(onSidebarWidthChange).toHaveBeenLastCalledWith(216);
    fireEvent.keyDown(handle, { key: "ArrowLeft", shiftKey: true });
    expect(onSidebarWidthChange).toHaveBeenLastCalledWith(176);
    fireEvent.keyDown(handle, { key: "Home" });
    expect(onSidebarWidthReset).toHaveBeenCalledTimes(1);
  });

  it("does not offer a resize handle while the sidebar is collapsed to icons", () => {
    renderShell({ sidebarCollapsed: true });
    expect(screen.queryByRole("separator", { name: /Resize sidebar/ })).toBeNull();
  });
});

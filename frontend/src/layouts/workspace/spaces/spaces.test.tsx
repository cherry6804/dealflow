import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider } from "../../../theme/ThemeProvider";
import { THEME_STORAGE_KEY } from "../../../theme/theme";
import { SPACE_DEFINITIONS } from "./spaceConfig";
import { SettingsMenu } from "./SettingsMenu";
import { SidebarCustomizer } from "./SidebarCustomizer";
import { SpaceFrame } from "./SpaceFrame";
import SpacePlaceholderRoute from "./SpacePlaceholderRoute";
import { DEFAULT_SPACE_PREFERENCES, arrangeSpaces, type SpacePreferences } from "./spacePreferences";
import { useSpacePreferences } from "./useSpacePreferences";
import { WorkspaceSidebar } from "./WorkspaceSidebar";

/* ---------- harnesses ---------- */

function BackButton() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(-1)}>
      Go back
    </button>
  );
}

function Page({ name }: { name: string }) {
  return <p>{name} page</p>;
}

function Shell({ path, rail = false }: { path: string; rail?: boolean }) {
  return (
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <div className="layout">
          <WorkspaceSidebar
            spaces={arrangeSpaces(DEFAULT_SPACE_PREFERENCES)}
            pathname={path}
            rail={rail}
            density="comfortable"
            label="Workspace spaces"
            heading="Spaces"
          />
          <BackButton />
          <Routes>
            <Route
              element={
                <SpaceFrame navigationSuffix="sections">
                  <Outlet />
                </SpaceFrame>
              }
            >
              <Route path="/" element={<Page name="Dashboard" />} />
              <Route path="/leads" element={<Page name="Leads" />} />
              <Route path="/contacts" element={<Page name="Contacts" />} />
              <Route path="/spaces/:spaceId/:tabId" element={<SpacePlaceholderRoute />} />
            </Route>
          </Routes>
        </div>
      </ThemeProvider>
    </MemoryRouter>
  );
}

function LocationProbe() {
  return <output data-testid="path">{useLocation().pathname}</output>;
}

/* ---------- navigation ---------- */

describe("space navigation", () => {
  it("opens a direct route with its space and tab highlighted", () => {
    render(<Shell path="/leads" />);
    const sections = screen.getByRole("navigation", { name: "Sales sections" });
    expect(within(sections).getByRole("link", { name: "Leads" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: /Sales/ }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByText("Leads page")).toBeTruthy();
  });

  it("switches tabs within a space and keeps the space active", () => {
    render(<Shell path="/leads" />);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Sales sections" })).getByRole("link", { name: "Contacts" }));
    expect(screen.getByText("Contacts page")).toBeTruthy();
    expect(within(screen.getByRole("navigation", { name: "Sales sections" })).getByRole("link", { name: "Contacts" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: /Sales/ }).getAttribute("aria-current")).toBe("page");
  });

  it("supports browser back navigation to the previous tab", () => {
    render(<Shell path="/leads" />);
    fireEvent.click(within(screen.getByRole("navigation", { name: "Sales sections" })).getByRole("link", { name: "Contacts" }));
    fireEvent.click(screen.getByRole("button", { name: "Go back" }));
    expect(screen.getByText("Leads page")).toBeTruthy();
  });

  it("shows a clearly marked placeholder for a tab with no feature yet", () => {
    render(<Shell path="/spaces/operations/activities" />);
    expect(screen.getByRole("heading", { name: "Activities is not available yet" })).toBeTruthy();
    expect(screen.getByText(/No data is shown here/)).toBeTruthy();
    const tab = within(screen.getByRole("navigation", { name: "Operations sections" })).getByRole("link", { name: /Activities/ });
    expect(tab.textContent).toContain("Not yet available");
  });

  it("renders the Overview dashboard on the root route with Overview active", () => {
    render(<Shell path="/" />);
    expect(screen.getByText("Dashboard page")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Overview/ }).getAttribute("aria-current")).toBe("page");
  });

  it("leaves routes outside the spaces without a space header", () => {
    render(
      <MemoryRouter initialEntries={["/billing"]}>
        <Routes>
          <Route
            element={
              <SpaceFrame navigationSuffix="sections">
                <Outlet />
              </SpaceFrame>
            }
          >
            <Route path="/billing" element={<Page name="Billing" />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("Billing page")).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: /sections/ })).toBeNull();
  });
});

/* ---------- sidebar ---------- */

describe("workspace sidebar", () => {
  it("shows all six spaces with labels in expanded mode", () => {
    render(<Shell path="/" />);
    for (const space of SPACE_DEFINITIONS) {
      expect(screen.getByRole("link", { name: new RegExp(space.label) })).toBeTruthy();
    }
  });

  it("keeps an accessible name for every space in icons-only mode", () => {
    render(<Shell path="/" rail />);
    expect(screen.getByRole("link", { name: "Sales" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Operations" })).toBeTruthy();
    expect(screen.queryByText("Sales", { selector: "span" })).toBeNull();
  });
});

/* ---------- customizer ---------- */

function renderCustomizer(preferences: SpacePreferences = DEFAULT_SPACE_PREFERENCES) {
  const onChange = vi.fn();
  const onRestoreDefaults = vi.fn();
  const onTableDensityChange = vi.fn();
  render(
    <ThemeProvider>
      <SidebarCustomizer
        open
        onClose={() => undefined}
        preferences={preferences}
        onChange={onChange}
        onRestoreDefaults={onRestoreDefaults}
        tableDensity="comfortable"
        onTableDensityChange={onTableDensityChange}
      />
    </ThemeProvider>,
  );
  return { onChange, onRestoreDefaults, onTableDensityChange };
}

describe("sidebar customizer", () => {
  it("pins a space through its pin control", () => {
    const { onChange } = renderCustomizer();
    fireEvent.click(screen.getByRole("button", { name: "Pin Sales" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ pinned: ["sales"] }));
  });

  it("hides a space through its visibility checkbox, but Overview cannot be hidden", () => {
    const { onChange } = renderCustomizer();
    expect((screen.getByRole("checkbox", { name: "Show Overview" }) as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox", { name: "Show Sales" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ hidden: ["sales"] }));
  });

  it("moves a space with the move buttons, the keyboard alternative to dragging", () => {
    const { onChange } = renderCustomizer();
    fireEvent.click(screen.getByRole("button", { name: "Move Sales down" }));
    const next = onChange.mock.calls[0][0] as SpacePreferences;
    expect(next.order.indexOf("sales")).toBe(2);
  });

  it("disables the move up control for the first space and the move down control for the last", () => {
    renderCustomizer();
    expect((screen.getByRole("button", { name: "Move Overview up" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Move Operations down" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("switches between expanded and icons-only mode", () => {
    const { onChange } = renderCustomizer();
    fireEvent.click(screen.getByRole("radio", { name: "Icons only" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ collapsed: true }));
  });

  it("restores the default arrangement", () => {
    const { onRestoreDefaults } = renderCustomizer();
    fireEvent.click(screen.getByRole("button", { name: "Restore default arrangement" }));
    expect(onRestoreDefaults).toHaveBeenCalledTimes(1);
  });

  it("changes table density, which the grids read", () => {
    const { onTableDensityChange } = renderCustomizer();
    const table = screen.getByRole("radiogroup", { name: "Table density" });
    fireEvent.click(within(table).getByRole("radio", { name: "Compact" }));
    expect(onTableDensityChange).toHaveBeenCalledWith("compact");
  });
});

/* ---------- settings menu ---------- */

describe("settings menu", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });
  afterEach(() => window.localStorage.clear());

  it("opens notification settings through the existing page route", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <ThemeProvider>
          <SettingsMenu />
          <LocationProbe />
        </ThemeProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("link", { name: /Email and in-app preferences/ }));
    expect(screen.getByTestId("path").textContent).toBe("/notification-preferences");
  });

  it("changes the theme through the existing theme control", () => {
    render(
      <MemoryRouter>
        <ThemeProvider>
          <SettingsMenu />
        </ThemeProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("radio", { name: "Dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("closes on Escape and returns focus to the trigger", () => {
    render(
      <MemoryRouter>
        <ThemeProvider>
          <SettingsMenu />
        </ThemeProvider>
      </MemoryRouter>,
    );
    const trigger = screen.getByRole("button", { name: "Settings" });
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Settings" }), { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Settings" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

/* ---------- personal isolation ---------- */

function Probe({ userId, organizationId, onReady }: { userId: string | null; organizationId: string | null; onReady: (api: ReturnType<typeof useSpacePreferences>) => void }) {
  const api = useSpacePreferences(userId, organizationId);
  onReady(api);
  return <output data-testid="order">{arrangeSpaces(api.preferences).map((space) => space.id).join(",")}</output>;
}

describe("sidebar preferences are personal", () => {
  beforeEach(() => window.localStorage.clear());

  it("user A's sidebar changes do not change user B's sidebar", () => {
    let alice: ReturnType<typeof useSpacePreferences> | undefined;
    const { unmount } = render(<Probe userId="alice" organizationId="org-1" onReady={(api) => (alice = api)} />);
    act(() => alice?.update({ ...DEFAULT_SPACE_PREFERENCES, pinned: ["deals"], hidden: ["partners"] }));
    unmount();

    let bob: ReturnType<typeof useSpacePreferences> | undefined;
    render(<Probe userId="bob" organizationId="org-1" onReady={(api) => (bob = api)} />);
    expect(bob?.preferences.pinned).toEqual([]);
    expect(screen.getByTestId("order").textContent).toContain("sales");
  });

  it("the same user in another organization sees that organization's layout only", () => {
    let first: ReturnType<typeof useSpacePreferences> | undefined;
    const { unmount } = render(<Probe userId="alice" organizationId="org-1" onReady={(api) => (first = api)} />);
    first?.update({ ...DEFAULT_SPACE_PREFERENCES, hidden: ["sales"] });
    unmount();

    render(<Probe userId="alice" organizationId="org-2" onReady={() => undefined} />);
    expect(screen.getByTestId("order").textContent).toContain("sales");
  });

  it("without a signed-in user, the defaults apply and nothing is stored", () => {
    let api: ReturnType<typeof useSpacePreferences> | undefined;
    render(<Probe userId={null} organizationId="org-1" onReady={(value) => (api = value)} />);
    expect(api?.available).toBe(false);
    expect(Object.keys(window.localStorage).filter((key) => key.startsWith("dealflow:workspace-spaces"))).toEqual([]);
  });

  it("restoring defaults for user A leaves user B's layout unchanged", () => {
    let alice: ReturnType<typeof useSpacePreferences> | undefined;
    let bob: ReturnType<typeof useSpacePreferences> | undefined;
    const first = render(<Probe userId="alice" organizationId="org-1" onReady={(api) => (alice = api)} />);
    act(() => alice?.update({ ...DEFAULT_SPACE_PREFERENCES, collapsed: true }));
    first.unmount();
    const second = render(<Probe userId="bob" organizationId="org-1" onReady={(api) => (bob = api)} />);
    act(() => bob?.update({ ...DEFAULT_SPACE_PREFERENCES, collapsed: true }));
    second.unmount();

    render(<Probe userId="alice" organizationId="org-1" onReady={(api) => (alice = api)} />);
    act(() => alice?.restoreDefaults());
    expect(alice?.preferences.collapsed).toBe(false);
    render(<Probe userId="bob" organizationId="org-1" onReady={(api) => (bob = api)} />);
    expect(bob?.preferences.collapsed).toBe(true);
  });

  it("a refused write still applies for the session and says nothing is stored", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    let api: ReturnType<typeof useSpacePreferences> | undefined;
    render(<Probe userId="alice" organizationId="org-1" onReady={(value) => (api = value)} />);
    act(() => api?.update({ ...DEFAULT_SPACE_PREFERENCES, pinned: ["partners"] }));
    expect(api?.preferences.pinned).toEqual(["partners"]);
    vi.restoreAllMocks();
  });
});

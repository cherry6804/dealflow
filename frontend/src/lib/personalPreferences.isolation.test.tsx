import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppContext, type AppContextValue } from "../contexts/appContextDefinition";
import { useGridViewPreferences } from "../hooks/useGridViewPreferences";
import { ThemeProvider } from "../theme/ThemeProvider";
import { ThemeToggle } from "../theme/ThemeToggle";
import { THEME_STORAGE_KEY } from "../theme/theme";
import {
  loadWorkspacePreferences,
  resetWorkspacePreferences,
  saveWorkspacePreferences,
  DEFAULT_WORKSPACE_PREFERENCES,
} from "../layouts/workspace/workspacePreferences";
import { LEADS_GRID_VIEW } from "./gridViewConfigs";
import {
  PERSONAL_PREFERENCE_SCHEMA_VERSION,
  parsePersonalPreference,
  personalPreferenceKey,
  readRawPreference,
  writePersonalPreference,
} from "./personalPreferences";

/* ---------- helpers ---------- */

const ORG_1 = { id: "org-1", name: "Acme" };
const ORG_2 = { id: "org-2", name: "Northwind" };
const ALICE = { id: "alice", email: "alice@example.com", display_name: "Alice" };
const BOB = { id: "bob", email: "bob@example.com", display_name: "Bob" };

function session(user: typeof ALICE | null, org = ORG_1): AppContextValue {
  return {
    user,
    organizations: [ORG_1, ORG_2],
    selectedOrganization: org,
    status: user ? "authenticated" : "unauthenticated",
    error: null,
    selectOrganization: vi.fn(),
    refreshOrganizations: vi.fn(async () => undefined),
    refreshSession: vi.fn(async () => undefined),
    signOut: vi.fn(async () => undefined),
  };
}

function Providers({ value, children }: { value: AppContextValue; children: ReactNode }) {
  return (
    <AppContext.Provider value={value}>
      <ThemeProvider>{children}</ThemeProvider>
    </AppContext.Provider>
  );
}

function GridProbe() {
  const grid = useGridViewPreferences(LEADS_GRID_VIEW);
  return (
    <div>
      <p data-testid="hidden">{grid.preferences.hidden.join(",")}</p>
      <button type="button" onClick={() => grid.setColumnVisible("status", false)}>
        hide status
      </button>
    </div>
  );
}

function resetStorage() {
  window.localStorage.clear();
}

/* ---------- store ---------- */

describe("personal preference store", () => {
  beforeEach(resetStorage);
  afterEach(() => vi.restoreAllMocks());

  it("keys every preference by organization and user, and never without a user", () => {
    expect(personalPreferenceKey("theme", null)).toBeNull();
    expect(personalPreferenceKey("theme", { userId: "", organizationId: null })).toBeNull();
    expect(personalPreferenceKey("theme", { userId: "alice", organizationId: null })).toBe("dealflow:theme:-:alice");
    expect(personalPreferenceKey("grid-view", { userId: "alice", organizationId: "org-1" }, "leads")).toBe(
      "dealflow:grid-view:org-1:alice:leads",
    );
  });

  it("returns the fallback for missing, invalid, outdated or wrong-shape values", () => {
    const parse = (data: unknown) => (typeof data === "string" ? data : null);
    expect(parsePersonalPreference(null, parse, "fallback")).toBe("fallback");
    expect(parsePersonalPreference("{not json", parse, "fallback")).toBe("fallback");
    expect(parsePersonalPreference(JSON.stringify({ v: 999, data: "x" }), parse, "fallback")).toBe("fallback");
    expect(parsePersonalPreference(JSON.stringify({ v: PERSONAL_PREFERENCE_SCHEMA_VERSION, data: 5 }), parse, "fallback")).toBe("fallback");
    expect(parsePersonalPreference(JSON.stringify("text"), parse, "fallback")).toBe("fallback");
  });

  it("replaces only the key it writes", () => {
    const aliceKey = personalPreferenceKey("theme", { userId: "alice", organizationId: null });
    const bobKey = personalPreferenceKey("theme", { userId: "bob", organizationId: null });
    writePersonalPreference(aliceKey, "dark");
    writePersonalPreference(bobKey, "light");
    writePersonalPreference(aliceKey, "system");
    expect(readRawPreference(bobKey)).toContain('"light"');
  });

  it("reports a refused write instead of throwing", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    expect(writePersonalPreference("dealflow:theme:-:alice", "dark")).toBe(false);
  });
});

/* ---------- 1. grid isolation ---------- */

describe("grid configuration is personal", () => {
  beforeEach(resetStorage);

  it("user A hides a column; user B's grid is unaffected", () => {
    const alice = render(
      <Providers value={session(ALICE)}>
        <GridProbe />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("button", { name: "hide status" }));
    expect(screen.getByTestId("hidden").textContent).toContain("status");
    alice.unmount();

    render(
      <Providers value={session(BOB)}>
        <GridProbe />
      </Providers>,
    );
    expect(screen.getByTestId("hidden").textContent).toBe("");
  });

  // 8 (reset): resetting one user's grid does not touch another's.
  it("resetting user A's workspace preferences leaves user B's unchanged", () => {
    saveWorkspacePreferences("org-1", "alice", { ...DEFAULT_WORKSPACE_PREFERENCES, sidebarCollapsed: true, navigationOrder: [...DEFAULT_WORKSPACE_PREFERENCES.navigationOrder] });
    saveWorkspacePreferences("org-1", "bob", { ...DEFAULT_WORKSPACE_PREFERENCES, sidebarCollapsed: true, navigationOrder: [...DEFAULT_WORKSPACE_PREFERENCES.navigationOrder] });
    resetWorkspacePreferences("org-1", "alice");
    expect(loadWorkspacePreferences("org-1", "alice").sidebarCollapsed).toBe(false);
    expect(loadWorkspacePreferences("org-1", "bob").sidebarCollapsed).toBe(true);
  });
});

/* ---------- 3. spaces and navigation ---------- */

describe("spaces and navigation are personal", () => {
  beforeEach(resetStorage);

  it("user A collapses a space and reorders spaces; user B keeps the defaults", () => {
    const base = loadWorkspacePreferences("org-1", "alice");
    saveWorkspacePreferences("org-1", "alice", {
      ...base,
      collapsedSpaces: ["sales"],
      spaceOrder: [...base.spaceOrder].reverse(),
    });
    const bob = loadWorkspacePreferences("org-1", "bob");
    expect(bob.collapsedSpaces).toEqual([]);
    expect(bob.spaceOrder).toEqual(DEFAULT_WORKSPACE_PREFERENCES.spaceOrder);
  });
});

/* ---------- 4. theme ---------- */

describe("theme is personal", () => {
  beforeEach(resetStorage);

  it("user A's theme does not change user B's theme", () => {
    const { rerender } = render(
      <Providers value={session(ALICE)}>
        <ThemeToggle />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");

    rerender(
      <Providers value={session(BOB)}>
        <ThemeToggle />
      </Providers>,
    );
    expect(screen.getByRole("radio", { name: "System theme" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: "Dark theme" }).getAttribute("aria-checked")).toBe("false");
  });

  // 6: signing out must not leave the previous user's theme on screen.
  it("signing out falls back to the device theme, not the previous user's choice", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    const { rerender } = render(
      <Providers value={session(ALICE)}>
        <ThemeToggle />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Dark theme" }));
    rerender(
      <Providers value={session(null)}>
        <ThemeToggle />
      </Providers>,
    );
    expect(screen.getByRole("radio", { name: "Light theme" }).getAttribute("aria-checked")).toBe("true");
  });

  // 9: the theme still works when storage is unavailable.
  it("applies the chosen theme for the session when storage is refused", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(
      <Providers value={session(ALICE)}>
        <ThemeToggle />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("status").textContent).toContain("would not remember");
    vi.restoreAllMocks();
  });
});

/* ---------- 5, 7: organization isolation and switching ---------- */

describe("organizations are isolated", () => {
  beforeEach(resetStorage);

  it("a user's preferences in one organization are not visible in another", () => {
    const base = loadWorkspacePreferences("org-1", "alice");
    saveWorkspacePreferences("org-1", "alice", { ...base, collapsedSpaces: ["sales"] });
    expect(loadWorkspacePreferences("org-2", "alice").collapsedSpaces).toEqual([]);
  });

  // 7: switching organization must show the new organization's preferences, not the previous one's.
  it("switching organization re-reads the grid for the new organization", () => {
    const { rerender } = render(
      <Providers value={session(ALICE, ORG_1)}>
        <GridProbe />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("button", { name: "hide status" }));
    expect(screen.getByTestId("hidden").textContent).toContain("status");

    rerender(
      <Providers value={session(ALICE, ORG_2)}>
        <GridProbe />
      </Providers>,
    );
    expect(screen.getByTestId("hidden").textContent).toBe("");
  });

  it("another organization's stored preferences are not read by this organization", () => {
    writePersonalPreference(personalPreferenceKey("grid-view", { userId: "alice", organizationId: "org-2" }, "leads"), {
      order: ["lead", "status", "interest", "nextAction", "createdAt"],
      hidden: ["status"],
    });
    render(
      <Providers value={session(ALICE, ORG_1)}>
        <GridProbe />
      </Providers>,
    );
    expect(screen.getByTestId("hidden").textContent).toBe("");
  });
});

/* ---------- 2. dashboard (store-level; no dashboard UI exists yet) ---------- */

describe("dashboard layouts are personal", () => {
  beforeEach(resetStorage);

  it("a layout saved by user A is not read for user B", () => {
    const aliceKey = personalPreferenceKey("dashboard", { userId: "alice", organizationId: "org-1" }, "main");
    const bobKey = personalPreferenceKey("dashboard", { userId: "bob", organizationId: "org-1" }, "main");
    writePersonalPreference(aliceKey, { widgets: ["kpis"] });
    const bobRaw = readRawPreference(bobKey);
    expect(bobRaw).toBeNull();
  });
});

/* ---------- 6. logout and login ---------- */

describe("sign-in and sign-out do not leak preferences", () => {
  beforeEach(resetStorage);

  it("user B signing in after user A sees only B's stored values", () => {
    saveWorkspacePreferences("org-1", "alice", { ...DEFAULT_WORKSPACE_PREFERENCES, sidebarCollapsed: true, navigationOrder: [...DEFAULT_WORKSPACE_PREFERENCES.navigationOrder] });
    expect(loadWorkspacePreferences("org-1", "bob").sidebarCollapsed).toBe(false);
  });

  it("without a user, personal keys are never read or written", () => {
    const { container } = render(
      <Providers value={session(null)}>
        <GridProbe />
      </Providers>,
    );
    fireEvent.click(screen.getByRole("button", { name: "hide status" }));
    expect(container.textContent).toContain("hide status");
    expect(Object.keys(window.localStorage).filter((key) => key.startsWith("dealflow:grid-view"))).toEqual([]);
  });
});

/* ---------- 9. unavailable storage ---------- */

describe("unavailable persistence falls back safely", () => {
  beforeEach(resetStorage);

  it("workspace preferences load defaults and save without throwing when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => saveWorkspacePreferences("org-1", "alice", DEFAULT_WORKSPACE_PREFERENCES)).not.toThrow();
    expect(loadWorkspacePreferences("org-1", "alice").sidebarCollapsed).toBe(false);
    vi.restoreAllMocks();
  });

  it("legacy unversioned workspace values still load, and migrate on the next save", () => {
    const key = personalPreferenceKey("workspace-preferences", { userId: "alice", organizationId: "org-1" });
    window.localStorage.setItem(key as string, JSON.stringify({ sidebarCollapsed: true }));
    expect(loadWorkspacePreferences("org-1", "alice").sidebarCollapsed).toBe(true);
    saveWorkspacePreferences("org-1", "alice", loadWorkspacePreferences("org-1", "alice"));
    expect(JSON.parse(window.localStorage.getItem(key as string) as string).v).toBe(PERSONAL_PREFERENCE_SCHEMA_VERSION);
  });

  it("a corrupted stored value falls back to defaults", () => {
    const key = personalPreferenceKey("workspace-preferences", { userId: "alice", organizationId: "org-1" });
    window.localStorage.setItem(key as string, "{broken");
    expect(loadWorkspacePreferences("org-1", "alice").sidebarCollapsed).toBe(false);
  });
});

/* ---------- 10. existing behaviour ---------- */

describe("existing behaviour is unchanged", () => {
  beforeEach(resetStorage);

  it("theme storage key for signed-out visitors is the device key used before", () => {
    expect(THEME_STORAGE_KEY).toBe("dealsflo.theme.preference");
  });
});

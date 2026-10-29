import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import GlobalSidebarNav from "./GlobalSidebarNav";
import { buildSidebarSections } from "./sidebarSections";
import {
  DEFAULT_WORKSPACE_PREFERENCES,
  type WorkspacePreferences,
} from "./workspacePreferences";

function preferences(
  overrides: Partial<WorkspacePreferences> = {},
): WorkspacePreferences {
  return { ...DEFAULT_WORKSPACE_PREFERENCES, ...overrides };
}

function renderNav(
  overrides: Partial<WorkspacePreferences> = {},
  onToggleSpace = vi.fn(),
) {
  const result = render(
    <MemoryRouter initialEntries={["/leads"]}>
      <nav aria-label="Main navigation">
        <GlobalSidebarNav
          preferences={preferences(overrides)}
          onToggleSpace={onToggleSpace}
        />
      </nav>
    </MemoryRouter>,
  );

  return { ...result, onToggleSpace };
}

describe("buildSidebarSections", () => {
  it("lists spaces in the user's order with the global items separate", () => {
    const sections = buildSidebarSections(
      preferences({
        spaceOrder: ["partners", "sales", "deals-revenue", "property", "operations"],
        pinnedModules: [],
      }),
    );

    expect(sections.spaces.map((section) => section.space.id)).toEqual([
      "partners",
      "sales",
      "deals-revenue",
      "property",
      "operations",
    ]);
    expect(sections.global.map((module) => module.label)).toEqual([
      "Overview",
      "Notifications",
      "Billing",
      "Settings",
    ]);
  });

  it("removes hidden modules everywhere", () => {
    const sections = buildSidebarSections(
      preferences({ hiddenModules: ["Leads", "Billing", "Commissions"], pinnedModules: [] }),
    );

    const labels = [
      ...sections.global.map((module) => module.label),
      ...sections.spaces.flatMap((section) =>
        section.modules.map((module) => module.label),
      ),
    ];

    expect(labels).not.toContain("Leads");
    expect(labels).not.toContain("Billing");
    expect(labels).not.toContain("Commissions");
  });

  it("shows pinned modules once, in the pinned group only", () => {
    const sections = buildSidebarSections(
      preferences({ pinnedModules: ["Leads", "Follow-ups"] }),
    );

    expect(sections.pinned.map((module) => module.label)).toEqual([
      "Leads",
      "Follow-ups",
    ]);

    const spaceLabels = sections.spaces.flatMap((section) =>
      section.modules.map((module) => module.label),
    );

    expect(spaceLabels).not.toContain("Leads");
    expect(spaceLabels).not.toContain("Follow-ups");
  });

  it("drops a space when every module in it is hidden or pinned", () => {
    const sections = buildSidebarSections(
      preferences({
        pinnedModules: ["Referrals"],
        hiddenModules: [],
      }),
    );

    expect(sections.spaces.map((section) => section.space.id)).not.toContain(
      "partners",
    );
  });

  it("marks spaces the user has collapsed", () => {
    const sections = buildSidebarSections(
      preferences({ collapsedSpaces: ["property"] }),
    );

    const property = sections.spaces.find(
      (section) => section.space.id === "property",
    );

    expect(property?.expanded).toBe(false);
    expect(
      sections.spaces.find((section) => section.space.id === "sales")?.expanded,
    ).toBe(true);
  });
});

describe("GlobalSidebarNav", () => {
  it("renders one toggle per space, expanded by default", () => {
    renderNav();

    for (const label of ["Sales", "Deals & Revenue", "Property", "Partners", "Operations"]) {
      const toggle = screen.getByRole("button", { name: label });
      expect(toggle.getAttribute("aria-expanded")).toBe("true");
    }
  });

  it("links each destination to its existing route", () => {
    renderNav();

    expect(screen.getByRole("link", { name: "Contacts" }).getAttribute("href")).toBe(
      "/contacts",
    );
    expect(screen.getByRole("link", { name: "Site Visits" }).getAttribute("href")).toBe(
      "/site-visits",
    );
    expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe(
      "/settings",
    );
  });

  it("marks the active route", () => {
    renderNav();

    expect(screen.getByRole("link", { name: "Leads" }).className).toContain(
      "is-active",
    );
  });

  it("toggles a space when its header is activated with the keyboard", async () => {
    const user = userEvent.setup();
    const { onToggleSpace } = renderNav();

    screen.getByRole("button", { name: "Sales" }).focus();
    await user.keyboard("{Enter}");

    expect(onToggleSpace).toHaveBeenCalledWith("sales");
  });

  it("hides a collapsed space's items and reports it as collapsed", () => {
    renderNav({ collapsedSpaces: ["property"] });

    const toggle = screen.getByRole("button", { name: "Property" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(panel?.hidden).toBe(true);
    expect(
      within(panel as HTMLElement).getByRole("link", {
        name: "Properties",
        hidden: true,
      }),
    ).toBeTruthy();
  });

  it("shows every destination as an icon when the sidebar is collapsed", () => {
    renderNav({ sidebarCollapsed: true });

    expect(screen.queryByRole("button", { name: "Sales" })).toBeNull();
    expect(screen.getByRole("link", { name: "Leads" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Referrals" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Settings" })).toBeTruthy();
  });
});

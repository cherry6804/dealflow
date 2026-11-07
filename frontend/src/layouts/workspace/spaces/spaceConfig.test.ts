import { describe, expect, it } from "vitest";

import { SPACE_DEFINITIONS, listSpaceRoutes, resolveSpaceLocation } from "./spaceConfig";
import { firstRoutableTab, spaceBreadcrumbs } from "./spaceNavigation";

describe("space configuration and routing", () => {
  it("defines the six primary spaces with the tabs in the story", () => {
    const tabs = Object.fromEntries(SPACE_DEFINITIONS.map((space) => [space.label, space.tabs.map((tab) => tab.label)]));
    expect(tabs).toEqual({
      Overview: ["Dashboard", "Follow-ups", "My Day", "Trends"],
      Sales: ["Contacts", "Customers", "Leads", "Pipeline", "Site Visits"],
      Properties: ["Properties", "Requirements"],
      Deals: ["Deals", "Commissions"],
      Partners: ["Referrals"],
      Operations: ["Activities", "Documents", "Automation", "Imports"],
    });
  });

  it("resolves a route to its space and tab, including child routes", () => {
    expect(resolveSpaceLocation("/")?.tab.id).toBe("dashboard");
    expect(resolveSpaceLocation("/leads")?.space.id).toBe("sales");
    expect(resolveSpaceLocation("/deals/123")?.tab.id).toBe("deals");
    expect(resolveSpaceLocation("/automation-rules/9")?.space.id).toBe("operations");
  });

  it("resolves placeholder tabs and returns undefined for routes outside the spaces", () => {
    expect(resolveSpaceLocation("/spaces/operations/activities")?.tab.id).toBe("activities");
    expect(resolveSpaceLocation("/agents")).toBeUndefined();
    expect(resolveSpaceLocation("/billing")).toBeUndefined();
  });

  it("does not match a route by prefix of another word", () => {
    expect(resolveSpaceLocation("/dealsx")).toBeUndefined();
  });

  it("opens a space on its first tab that has a real page, not a placeholder", () => {
    const operations = SPACE_DEFINITIONS.find((space) => space.id === "operations");
    expect(operations && firstRoutableTab(operations)?.id).toBe("documents");
  });

  it("lists only available routes for the command palette, with no duplicates", () => {
    const routes = listSpaceRoutes().map((route) => route.to);
    expect(routes).not.toContain("/spaces/overview/my-day");
    expect(new Set(routes).size).toBe(routes.length);
  });

  it("builds breadcrumbs for space routes and leaves other routes to the default trail", () => {
    expect(spaceBreadcrumbs("/leads", "Overview", "/")).toEqual([
      { label: "Overview", to: "/" },
      { label: "Sales", to: "/contacts" },
      { label: "Leads" },
    ]);
    expect(spaceBreadcrumbs("/billing", "Overview", "/")).toBeUndefined();
  });
});

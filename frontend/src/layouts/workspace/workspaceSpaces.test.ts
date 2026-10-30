import { describe, expect, it } from "vitest";

import {
  GLOBAL_MODULES,
  WORKSPACE_MODULES,
  WORKSPACE_SPACES,
  getSpaceForModule,
} from "./workspaceSpaces";

describe("workspace space configuration", () => {
  it("defines the five approved spaces in order", () => {
    expect(WORKSPACE_SPACES.map((space) => space.label)).toEqual([
      "Sales",
      "Deals & Revenue",
      "Property",
      "Partners",
      "Operations",
    ]);
  });

  it("assigns the approved modules to each space", () => {
    const modulesBySpace = Object.fromEntries(
      WORKSPACE_SPACES.map((space) => [space.id, [...space.moduleLabels]]),
    );

    expect(modulesBySpace).toEqual({
      sales: ["Leads", "Contacts", "Customers", "Pipeline", "Follow-ups"],
      "deals-revenue": ["Deals", "Commissions"],
      property: ["Properties", "Requirements", "Site Visits"],
      partners: ["Referrals"],
      operations: ["Documents", "Imports", "Automation Rules", "Activity"],
    });
  });

  it("places every module in exactly one location", () => {
    const placements = [
      ...GLOBAL_MODULES.map((module) => module.label),
      ...WORKSPACE_SPACES.flatMap((space) => [...space.moduleLabels]),
    ];

    expect(new Set(placements).size).toBe(placements.length);
    expect(placements.sort()).toEqual(
      WORKSPACE_MODULES.map((module) => module.label).sort(),
    );
  });

  it("keeps every existing sidebar destination reachable", () => {
    const labels = WORKSPACE_MODULES.map((module) => module.label);

    for (const label of [
      "Overview",
      "Leads",
      "Contacts",
      "Customers",
      "Requirements",
      "Pipeline",
      "Deals",
      "Properties",
      "Referrals",
      "Site Visits",
      "Follow-ups",
      "Commissions",
      "Documents",
      "Imports",
      "Automation Rules",
      "Activity",
      "Notifications",
      "Settings",
    ]) {
      expect(labels).toContain(label);
    }
  });

  it("uses unique routes and absolute paths", () => {
    const routes = WORKSPACE_MODULES.map((module) => module.to);

    expect(new Set(routes).size).toBe(routes.length);
    for (const route of routes) {
      expect(route.startsWith("/")).toBe(true);
    }
  });

  it("finds the space that owns a module", () => {
    expect(getSpaceForModule("Leads")?.id).toBe("sales");
    expect(getSpaceForModule("Site Visits")?.id).toBe("property");
    expect(getSpaceForModule("Overview")).toBeUndefined();
  });
});

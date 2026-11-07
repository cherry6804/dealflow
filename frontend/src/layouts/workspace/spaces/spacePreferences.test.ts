import { describe, expect, it } from "vitest";

import { SPACE_DEFINITIONS } from "./spaceConfig";
import {
  DEFAULT_SPACE_PREFERENCES,
  allSpacesInOrder,
  arrangeSpaces,
  moveSpace,
  normalizeSpacePreferences,
  reorderSpaces,
  resetSidebarWidth,
  setSidebarHidden,
  setSidebarWidth,
  setCollapsed,
  setDensity,
  toggleHidden,
  togglePinned,
} from "./spacePreferences";

const ids = (list: { id: string }[]) => list.map((item) => item.id);

describe("space preferences", () => {
  it("starts with the six spaces in the default order, none pinned or hidden", () => {
    expect(ids(arrangeSpaces(DEFAULT_SPACE_PREFERENCES))).toEqual([
      "overview",
      "sales",
      "properties",
      "deals",
      "partners",
      "operations",
    ]);
  });

  it("ignores unknown ids, fills in missing spaces, and falls back for invalid fields", () => {
    const normalized = normalizeSpacePreferences({
      order: ["operations", "nope", "sales"],
      pinned: ["deals", "deals", "nope"],
      hidden: ["partners"],
      collapsed: "yes",
      density: "huge",
    });
    expect(normalized.order.slice(0, 2)).toEqual(["operations", "sales"]);
    expect(normalized.order).toHaveLength(6);
    expect(normalized.pinned).toEqual(["deals"]);
    expect(normalized.hidden).toEqual(["partners"]);
    expect(normalized.collapsed).toBe(false);
    expect(normalized.density).toBe("comfortable");
  });

  it("never hides Overview, and never leaves a space both pinned and hidden", () => {
    const normalized = normalizeSpacePreferences({ hidden: ["overview", "sales"], pinned: ["sales"] });
    expect(normalized.hidden).toEqual(["sales"]);
    expect(normalized.pinned).toEqual([]);
    expect(toggleHidden(DEFAULT_SPACE_PREFERENCES, "overview")).toEqual(DEFAULT_SPACE_PREFERENCES);
  });

  it("lists pinned spaces first and leaves hidden spaces out of the sidebar", () => {
    let prefs = togglePinned(DEFAULT_SPACE_PREFERENCES, "deals");
    prefs = toggleHidden(prefs, "sales");
    expect(ids(arrangeSpaces(prefs))).toEqual(["deals", "overview", "properties", "partners", "operations"]);
  });

  it("pinning a hidden space shows it; hiding a pinned space unpins it", () => {
    const hidden = toggleHidden(DEFAULT_SPACE_PREFERENCES, "sales");
    expect(togglePinned(hidden, "sales").hidden).toEqual([]);
    const pinned = togglePinned(DEFAULT_SPACE_PREFERENCES, "sales");
    expect(toggleHidden(pinned, "sales").pinned).toEqual([]);
  });

  it("reorders by drag (target position) and by one step with the move buttons", () => {
    const dragged = reorderSpaces(DEFAULT_SPACE_PREFERENCES, "operations", "sales");
    expect(ids(allSpacesInOrder(dragged).map((entry) => entry.space))).toEqual([
      "overview",
      "operations",
      "sales",
      "properties",
      "deals",
      "partners",
    ]);
    const stepped = moveSpace(DEFAULT_SPACE_PREFERENCES, "deals", -1);
    expect(stepped.order.indexOf("deals")).toBe(2);
    expect(moveSpace(DEFAULT_SPACE_PREFERENCES, "overview", -1)).toEqual(DEFAULT_SPACE_PREFERENCES);
  });

  it("keeps sidebar mode and row spacing separate and validated", () => {
    expect(setCollapsed(DEFAULT_SPACE_PREFERENCES, true).collapsed).toBe(true);
    expect(setDensity(DEFAULT_SPACE_PREFERENCES, "compact").density).toBe("compact");
  });

  it("every configured space has a unique id", () => {
    const all = SPACE_DEFINITIONS.map((space) => space.id);
    expect(new Set(all).size).toBe(all.length);
  });
});

describe("sidebar width and visibility", () => {
  it("keeps the width within bounds and defaults invalid values", () => {
    expect(normalizeSpacePreferences({ sidebarWidth: 10 }).sidebarWidth).toBe(176);
    expect(normalizeSpacePreferences({ sidebarWidth: 9000 }).sidebarWidth).toBe(320);
    expect(normalizeSpacePreferences({ sidebarWidth: "wide" }).sidebarWidth).toBe(208);
    expect(normalizeSpacePreferences({ sidebarWidth: 240.6 }).sidebarWidth).toBe(241);
  });

  it("hides and restores the sidebar without changing its width or mode", () => {
    const sized = setSidebarWidth(DEFAULT_SPACE_PREFERENCES, 260);
    const hidden = setSidebarHidden(sized, true);
    expect(hidden.sidebarHidden).toBe(true);
    expect(hidden.sidebarWidth).toBe(260);
    expect(setSidebarHidden(hidden, false).sidebarHidden).toBe(false);
  });

  it("resets the width to its default", () => {
    expect(resetSidebarWidth(setSidebarWidth(DEFAULT_SPACE_PREFERENCES, 300)).sidebarWidth).toBe(208);
  });
});

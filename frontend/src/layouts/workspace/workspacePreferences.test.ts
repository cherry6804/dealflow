import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_WORKSPACE_PREFERENCES,
  WORKSPACE_PREFERENCES_CHANGED_EVENT,
  loadWorkspacePreferences,
  saveWorkspacePreferences,
  type WorkspacePreferences,
} from "./workspacePreferences";
import { WORKSPACE_MODULE_LABELS, WORKSPACE_SPACE_IDS } from "./workspaceSpaces";

function storageKey(organizationId: string, userId: string) {
  return `dealflow:workspace-preferences:${organizationId}:${userId}`;
}

describe("personal workspace preferences", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("starts with the approved space order and no collapsed spaces", () => {
    expect(DEFAULT_WORKSPACE_PREFERENCES.spaceOrder).toEqual([
      "sales",
      "deals-revenue",
      "property",
      "partners",
      "operations",
    ]);
    expect(DEFAULT_WORKSPACE_PREFERENCES.collapsedSpaces).toEqual([]);
  });

  it("returns defaults when nothing is saved", () => {
    const preferences = loadWorkspacePreferences(
      "org-1",
      "user-1",
      [...WORKSPACE_MODULE_LABELS],
    );

    expect(preferences.spaceOrder).toEqual([...WORKSPACE_SPACE_IDS]);
    expect(preferences.collapsedSpaces).toEqual([]);
  });

  it("falls back to defaults when stored data is corrupt", () => {
    localStorage.setItem(storageKey("org-1", "user-1"), "{not json");

    expect(() =>
      loadWorkspacePreferences("org-1", "user-1", [...WORKSPACE_MODULE_LABELS]),
    ).not.toThrow();
    expect(
      loadWorkspacePreferences("org-1", "user-1", [...WORKSPACE_MODULE_LABELS])
        .spaceOrder,
    ).toEqual([...WORKSPACE_SPACE_IDS]);
  });

  it("falls back to defaults when browser storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });

    const preferences = loadWorkspacePreferences(
      "org-1",
      "user-1",
      [...WORKSPACE_MODULE_LABELS],
    );

    expect(preferences.spaceOrder).toEqual([...WORKSPACE_SPACE_IDS]);
  });

  it("drops unknown space ids and appends missing ones", () => {
    localStorage.setItem(
      storageKey("org-1", "user-1"),
      JSON.stringify({
        spaceOrder: ["partners", "not-a-space", "sales"],
        collapsedSpaces: ["property", "ghost"],
      }),
    );

    const preferences = loadWorkspacePreferences(
      "org-1",
      "user-1",
      [...WORKSPACE_MODULE_LABELS],
    );

    expect(preferences.spaceOrder).toEqual([
      "partners",
      "sales",
      "deals-revenue",
      "property",
      "operations",
    ]);
    expect(preferences.collapsedSpaces).toEqual(["property"]);
  });

  it("keeps each user's layout separate within the same organization", () => {
    const modules = [...WORKSPACE_MODULE_LABELS];
    const alice: WorkspacePreferences = {
      ...DEFAULT_WORKSPACE_PREFERENCES,
      spaceOrder: ["partners", "sales", "deals-revenue", "property", "operations"],
      collapsedSpaces: ["sales"],
    };

    saveWorkspacePreferences("org-1", "alice", alice);

    const bob = loadWorkspacePreferences("org-1", "bob", modules);

    expect(bob.spaceOrder).toEqual([...WORKSPACE_SPACE_IDS]);
    expect(bob.collapsedSpaces).toEqual([]);
    expect(
      loadWorkspacePreferences("org-1", "alice", modules).spaceOrder[0],
    ).toBe("partners");
  });

  it("keeps the same user's layout separate across organizations", () => {
    const modules = [...WORKSPACE_MODULE_LABELS];

    saveWorkspacePreferences("org-1", "alice", {
      ...DEFAULT_WORKSPACE_PREFERENCES,
      collapsedSpaces: ["property"],
    });

    expect(
      loadWorkspacePreferences("org-2", "alice", modules).collapsedSpaces,
    ).toEqual([]);
  });

  it("announces saved changes so open navigation can update", () => {
    const listener = vi.fn();
    window.addEventListener(WORKSPACE_PREFERENCES_CHANGED_EVENT, listener);

    saveWorkspacePreferences("org-1", "alice", DEFAULT_WORKSPACE_PREFERENCES);

    window.removeEventListener(WORKSPACE_PREFERENCES_CHANGED_EVENT, listener);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

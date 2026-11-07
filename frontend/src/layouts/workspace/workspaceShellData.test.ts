import { describe, expect, it, vi } from "vitest";

import type { NotificationItem } from "../../services/notificationApi";
import {
  formatNotificationTime,
  getPreferenceKey,
  initialsFor,
  isNewShellEnabled,
  toNotificationEntry,
} from "./workspaceShellData";

const item: NotificationItem = {
  id: "n1",
  organization_id: "org-1",
  recipient_user_id: "user-1",
  event_type: "deal.won",
  title: "Deal won",
  message: "Meridian Tower HQ lease closed",
  resource_type: "deals",
  resource_id: "d-1",
  created_at: "2026-11-07T09:00:00Z",
  read_at: null,
};

describe("workspace shell data", () => {
  it("keys stored preferences by organization and user", () => {
    expect(getPreferenceKey("org-1", "user-9")).toBe("org-1::user-9");
    expect(getPreferenceKey("org-2", "user-9")).not.toBe(getPreferenceKey("org-1", "user-9"));
  });

  it("uses the display name, then the email, then a fallback for the avatar initial", () => {
    expect(initialsFor("elena ruiz", "elena@example.com")).toBe("E");
    expect(initialsFor(null, "sam@example.com")).toBe("S");
    expect(initialsFor(null, null)).toBe("U");
  });

  it("maps an unread notification and keeps its resource type for routing", () => {
    const entry = toNotificationEntry(item);
    expect(entry).toMatchObject({ id: "n1", title: "Deal won", read: false, resourceType: "deals" });
    expect(toNotificationEntry({ ...item, read_at: "2026-11-07T10:00:00Z" }).read).toBe(true);
  });

  it("shows an unparseable timestamp as received instead of 'Invalid Date'", () => {
    expect(formatNotificationTime("not a date")).toBe("not a date");
  });

  it("uses the redesigned shell only when the build flag is exactly 'true'", () => {
    vi.stubEnv("VITE_DEALSFLO_NEW_SHELL", "false");
    expect(isNewShellEnabled()).toBe(false);
    vi.stubEnv("VITE_DEALSFLO_NEW_SHELL", "TRUE");
    expect(isNewShellEnabled()).toBe(false);
    vi.stubEnv("VITE_DEALSFLO_NEW_SHELL", "true");
    expect(isNewShellEnabled()).toBe(true);
    vi.unstubAllEnvs();
  });
});

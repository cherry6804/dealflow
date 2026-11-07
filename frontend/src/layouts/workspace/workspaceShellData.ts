import type { NotificationEntry } from "../../components/shell/NotificationsMenu";
import type { NotificationItem } from "../../services/notificationApi";

/**
 * Pure mapping between the production data model and the shell's presentational props.
 * Nothing here calls the network or touches storage.
 */

/** Preferences are stored per organization and user, so switching organizations switches layouts too. */
export function getPreferenceKey(organizationId: string, userId: string): string {
  return `${organizationId}::${userId}`;
}

/** Initial for the avatar: the display name, else the email, else "U". */
export function initialsFor(name?: string | null, email?: string | null): string {
  const value = name?.trim() || email?.trim() || "U";
  return value.charAt(0).toUpperCase();
}

/** Formats a timestamp for display. Unparseable values are shown as received rather than as "Invalid Date". */
export function formatNotificationTime(value: string): string {
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  return timestamp.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function toNotificationEntry(item: NotificationItem): NotificationEntry {
  return {
    id: item.id,
    title: item.title,
    message: item.message,
    createdAt: formatNotificationTime(item.created_at),
    read: item.read_at !== null,
    resourceType: item.resource_type,
  };
}

/**
 * Whether the redesigned shell is used. Off unless the build sets VITE_DEALSFLO_NEW_SHELL to "true", so the existing
 * layout stays the default until the new shell has been verified against the real session.
 */
export function isNewShellEnabled(): boolean {
  return import.meta.env.VITE_DEALSFLO_NEW_SHELL === "true";
}

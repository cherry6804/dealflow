import { api } from "../lib/api";

export interface NotificationItem {
  id: string;
  organization_id: string;
  recipient_user_id: string;
  event_type: string;
  title: string;
  message: string;
  resource_type: string | null;
  resource_id: string | null;
  created_at: string;
  read_at: string | null;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  total: number;
  unread_count: number;
  limit: number;
  offset: number;
}

export interface NotificationUnreadCountResponse {
  unread_count: number;
}

export interface NotificationMarkAllReadResponse {
  updated_count: number;
}

/**
 * Notification preference settings for the current user
 * in the selected organization.
 */
export interface NotificationPreferences {
  id: string;
  organization_id: string;
  user_id: string;
  enabled: boolean;
  follow_ups_enabled: boolean;
  deals_enabled: boolean;
  site_visits_enabled: boolean;
  leads_enabled: boolean;
  automation_enabled: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Preference keys that can be updated individually.
 */
export type NotificationPreferenceKey =
  | "enabled"
  | "follow_ups_enabled"
  | "deals_enabled"
  | "site_visits_enabled"
  | "leads_enabled"
  | "automation_enabled";

/**
 * Partial updates allow the client to change only
 * the preference that the user modifies.
 */
export type NotificationPreferencesUpdate = Partial<
  Record<NotificationPreferenceKey, boolean>
>;

const BASE_PATH = "/notifications";
const PREFERENCES_PATH = `${BASE_PATH}/preferences`;

export const notificationApi = {
  list(
    limit = 10,
    offset = 0,
  ): Promise<NotificationListResponse> {
    const query = new URLSearchParams({
      limit: String(
        Math.min(100, Math.max(1, Math.floor(limit))),
      ),
      offset: String(Math.max(0, Math.floor(offset))),
    });

    return api.get<NotificationListResponse>(
      `${BASE_PATH}?${query.toString()}`,
    );
  },

  unreadCount(): Promise<NotificationUnreadCountResponse> {
    return api.get<NotificationUnreadCountResponse>(
      `${BASE_PATH}/unread-count`,
    );
  },

  markRead(
    notificationId: string,
  ): Promise<NotificationItem> {
    return api.patch<NotificationItem>(
      `${BASE_PATH}/${encodeURIComponent(notificationId)}/read`,
      {},
    );
  },

  markAllRead(): Promise<NotificationMarkAllReadResponse> {
    return api.post<NotificationMarkAllReadResponse>(
      `${BASE_PATH}/mark-all-read`,
      {},
    );
  },

  /**
   * Fetches the current user's notification preferences.
   * The backend creates default preferences if none exist.
   */
  getPreferences(): Promise<NotificationPreferences> {
    return api.get<NotificationPreferences>(
      PREFERENCES_PATH,
    );
  },

  /**
   * Updates only the supplied notification preferences.
   */
  updatePreferences(
    changes: NotificationPreferencesUpdate,
  ): Promise<NotificationPreferences> {
    return api.patch<NotificationPreferences>(
      PREFERENCES_PATH,
      changes,
    );
  },
};

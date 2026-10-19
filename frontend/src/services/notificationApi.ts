
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

const BASE_PATH = "/notifications";

export const notificationApi = {
  list(limit = 10, offset = 0): Promise<NotificationListResponse> {
    const query = new URLSearchParams({
      limit: String(Math.min(100, Math.max(1, Math.floor(limit)))),
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

  markRead(notificationId: string): Promise<NotificationItem> {
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
};

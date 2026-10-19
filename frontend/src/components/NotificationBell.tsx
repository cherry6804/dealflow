import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";

import {
  notificationApi,
  type NotificationItem,
} from "../services/notificationApi";
import "./NotificationBell.css";

const PAGE_SIZE = 10;
const PANEL_WIDTH = 400;
const VIEWPORT_GAP = 12;
const PANEL_GAP = 10;

const RESOURCE_ROUTES: Record<string, string> = {
  contact: "/contacts",
  contacts: "/contacts",
  customer: "/customers",
  customers: "/customers",
  lead: "/leads",
  leads: "/leads",
  deal: "/deals",
  deals: "/deals",
  referral: "/referrals",
  referrals: "/referrals",
  property: "/properties",
  properties: "/properties",
  site_visit: "/site-visits",
  site_visits: "/site-visits",
  requirement: "/requirements",
  requirements: "/requirements",
  import: "/imports",
  imports: "/imports",
  document: "/documents",
  documents: "/documents",
  follow_up: "/",
  followup: "/",
  automation_rule: "/automation-rules",
};

function getResourceRoute(
  resourceType: string | null,
): string | null {
  if (!resourceType) {
    return null;
  }

  return RESOURCE_ROUTES[resourceType.toLowerCase()] ?? null;
}

function formatRelativeTime(value: string): string {
  const timestamp = new Date(value).getTime();

  if (!Number.isFinite(timestamp)) {
    return "";
  }

  const elapsedSeconds = Math.max(
    0,
    Math.floor((Date.now() - timestamp) / 1000),
  );

  if (elapsedSeconds < 60) {
    return "Just now";
  }

  const minutes = Math.floor(elapsedSeconds / 60);

  if (minutes < 60) {
    return `${minutes}m ago`;
  }

  const hours = Math.floor(minutes / 60);

  if (hours < 24) {
    return `${hours}h ago`;
  }

  const days = Math.floor(hours / 24);

  if (days < 7) {
    return `${days}d ago`;
  }

  return new Date(timestamp).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function BellIcon({ small = false }: { small?: boolean }) {
  return (
    <svg
      className={small ? "notification-icon-small" : "notification-icon"}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M10 21h4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      className="notification-action-icon"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="m5 12 4 4L19 6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function EmptyInboxIcon() {
  return (
    <svg
      className="notification-empty-icon"
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <rect
        x="5"
        y="9"
        width="38"
        height="30"
        rx="7"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="M5 27h10l3 4h12l3-4h10"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="m19 19 5 5 5-5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function NotificationBell() {
  const navigate = useNavigate();

  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const [isOpen, setIsOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [panelStyle, setPanelStyle] = useState<{
    top: number;
    left: number;
    width: number;
    maxHeight: number;
  } | null>(null);

  const hasMore = items.length < total;

  const refreshUnreadCount = useCallback(async () => {
    try {
      const response = await notificationApi.unreadCount();
      setUnreadCount(response.unread_count);
    } catch {
      // Keep the last known count if a refresh temporarily fails.
    }
  }, []);

  const loadNotifications = useCallback(
    async (append = false) => {
      if (append) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }

      setError(null);

      try {
        const offset = append ? items.length : 0;
        const response = await notificationApi.list(
          PAGE_SIZE,
          offset,
        );

        setItems((current) =>
          append ? [...current, ...response.items] : response.items,
        );
        setTotal(response.total);
        setUnreadCount(response.unread_count);
      } catch {
        setError("We couldn't load your notifications. Please try again.");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [items.length],
  );

  const updatePanelPosition = useCallback(() => {
    const trigger = triggerRef.current;

    if (!trigger) {
      return;
    }

    const rect = trigger.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const isMobile = viewportWidth <= 600;

    const width = Math.min(
      isMobile ? viewportWidth - VIEWPORT_GAP * 2 : PANEL_WIDTH,
      viewportWidth - VIEWPORT_GAP * 2,
    );

    const left = isMobile
      ? VIEWPORT_GAP
      : Math.max(
          VIEWPORT_GAP,
          Math.min(
            rect.right - width,
            viewportWidth - width - VIEWPORT_GAP,
          ),
        );

    const top = isMobile
      ? Math.min(
          Math.max(84, rect.bottom + PANEL_GAP),
          viewportHeight - 180,
        )
      : rect.bottom + PANEL_GAP;

    setPanelStyle({
      top,
      left,
      width,
      maxHeight: Math.max(160, viewportHeight - top - VIEWPORT_GAP),
    });
  }, []);

  const openPanel = useCallback(() => {
    setIsOpen(true);
    updatePanelPosition();
    void loadNotifications(false);
    void refreshUnreadCount();
  }, [loadNotifications, refreshUnreadCount, updatePanelPosition]);

  const closePanel = useCallback(() => {
    setIsOpen(false);
  }, []);

  const togglePanel = useCallback(() => {
    if (isOpen) {
      closePanel();
    } else {
      openPanel();
    }
  }, [closePanel, isOpen, openPanel]);

  useEffect(() => {
    void refreshUnreadCount();
  }, [refreshUnreadCount]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    updatePanelPosition();

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;

      if (!(target instanceof Node)) {
        return;
      }

      if (
        triggerRef.current?.contains(target) ||
        panelRef.current?.contains(target)
      ) {
        return;
      }

      closePanel();
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closePanel();
        triggerRef.current?.focus();
      }
    };

    const handleViewportChange = () => {
      updatePanelPosition();
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("resize", handleViewportChange);
    window.addEventListener("scroll", handleViewportChange, true);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("resize", handleViewportChange);
      window.removeEventListener("scroll", handleViewportChange, true);
    };
  }, [closePanel, isOpen, updatePanelPosition]);

  const handleMarkRead = useCallback(
    async (notification: NotificationItem) => {
      if (notification.read_at || busyId === notification.id) {
        return true;
      }

      setBusyId(notification.id);
      setError(null);

      try {
        const updated = await notificationApi.markRead(
          notification.id,
        );

        setItems((current) =>
          current.map((item) =>
            item.id === notification.id ? updated : item,
          ),
        );

        setUnreadCount((current) => Math.max(0, current - 1));
        return true;
      } catch {
        setError("We couldn't update this notification. Please try again.");
        return false;
      } finally {
        setBusyId(null);
      }
    },
    [busyId],
  );

  const handleNotificationClick = useCallback(
    async (notification: NotificationItem) => {
      const success = await handleMarkRead(notification);

      if (!success) {
        return;
      }

      const route = getResourceRoute(notification.resource_type);

      if (route) {
        closePanel();
        navigate(route);
      }
    },
    [closePanel, handleMarkRead, navigate],
  );

  const handleMarkAllRead = useCallback(async () => {
    if (unreadCount === 0 || markingAll) {
      return;
    }

    setMarkingAll(true);
    setError(null);

    try {
      await notificationApi.markAllRead();

      const now = new Date().toISOString();

      setItems((current) =>
        current.map((item) =>
          item.read_at ? item : { ...item, read_at: now },
        ),
      );

      setUnreadCount(0);
    } catch {
      setError("We couldn't mark all notifications as read. Please try again.");
    } finally {
      setMarkingAll(false);
    }
  }, [markingAll, unreadCount]);

  const panel = isOpen
    ? createPortal(
        <div
          ref={panelRef}
          className="notification-panel"
          role="dialog"
          aria-label="Notifications"
          style={
            panelStyle
              ? {
                  top: panelStyle.top,
                  left: panelStyle.left,
                  width: panelStyle.width,
                  maxHeight: panelStyle.maxHeight,
                }
              : undefined
          }
        >
          <div className="notification-panel-header">
            <div className="notification-panel-heading">
              <div className="notification-panel-title-row">
                <h2 className="notification-panel-title">
                  Notifications
                </h2>

                {unreadCount > 0 && (
                  <span className="notification-unread-count">
                    {unreadCount > 99 ? "99+" : unreadCount}
                  </span>
                )}
              </div>

              <p className="notification-panel-subtitle">
                {unreadCount > 0
                  ? `You have ${unreadCount} unread ${
                      unreadCount === 1 ? "notification" : "notifications"
                    }`
                  : "You're all caught up"}
              </p>
            </div>

            <button
              type="button"
              className="notification-close-button"
              onClick={closePanel}
              aria-label="Close notifications"
            >
              <span aria-hidden="true">×</span>
            </button>
          </div>

          {unreadCount > 0 && (
            <div className="notification-toolbar">
              <button
                type="button"
                className="notification-mark-all-button"
                onClick={() => void handleMarkAllRead()}
                disabled={markingAll}
              >
                <CheckIcon />
                {markingAll ? "Marking as read…" : "Mark all as read"}
              </button>
            </div>
          )}

          <div className="notification-panel-body">
            {loading && items.length === 0 ? (
              <div className="notification-panel-status">
                <span
                  className="notification-loading-spinner"
                  aria-hidden="true"
                />
                <p className="notification-status-title">
                  Loading notifications
                </p>
                <p className="notification-status-message">
                  Just a moment while we fetch your updates.
                </p>
              </div>
            ) : error && items.length === 0 ? (
              <div className="notification-panel-status">
                <div className="notification-status-icon error">
                  <span aria-hidden="true">!</span>
                </div>
                <p className="notification-status-title">
                  Couldn't load notifications
                </p>
                <p className="notification-status-message">
                  {error}
                </p>
                <button
                  type="button"
                  className="notification-status-retry"
                  onClick={() => void loadNotifications(false)}
                >
                  Try again
                </button>
              </div>
            ) : items.length === 0 ? (
              <div className="notification-panel-status notification-empty-state">
                <div className="notification-empty-icon-wrap">
                  <EmptyInboxIcon />
                </div>
                <p className="notification-status-title">
                  You're all caught up
                </p>
                <p className="notification-status-message">
                  New notifications will appear here when there's something
                  you need to know.
                </p>
              </div>
            ) : (
              <ul className="notification-list">
                {items.map((notification) => (
                  <li
                    key={notification.id}
                    className={[
                      "notification-list-item",
                      notification.read_at ? "read" : "unread",
                    ].join(" ")}
                  >
                    <span
                      className="notification-item-indicator"
                      aria-hidden="true"
                    />

                    <div className="notification-item-content">
                      <button
                        type="button"
                        className="notification-item-open"
                        onClick={() =>
                          void handleNotificationClick(notification)
                        }
                      >
                        <span className="notification-item-title">
                          {notification.title}
                        </span>

                        <span className="notification-item-message">
                          {notification.message}
                        </span>

                        <span className="notification-item-time">
                          {formatRelativeTime(notification.created_at)}
                        </span>
                      </button>
                    </div>

                    {!notification.read_at && (
                      <button
                        type="button"
                        className="notification-item-mark-read"
                        onClick={() => void handleMarkRead(notification)}
                        disabled={busyId === notification.id}
                        aria-label={`Mark "${notification.title}" as read`}
                        title="Mark as read"
                      >
                        <CheckIcon />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}

            {error && items.length > 0 && (
              <p className="notification-inline-error" role="alert">
                {error}
              </p>
            )}
          </div>

          {items.length > 0 && hasMore && (
            <div className="notification-panel-footer">
              <button
                type="button"
                className="notification-load-more"
                onClick={() => void loadNotifications(true)}
                disabled={loadingMore}
              >
                {loadingMore ? "Loading…" : "Load older notifications"}
              </button>
            </div>
          )}
        </div>,
        document.body,
      )
    : null;

  return (
    <>
      <div className="notification-bell-wrapper">
        <button
          ref={triggerRef}
          type="button"
          className="notification-bell-button"
          onClick={togglePanel}
          aria-label={
            unreadCount > 0
              ? `Notifications, ${unreadCount} unread`
              : "Notifications"
          }
          aria-haspopup="dialog"
          aria-expanded={isOpen}
        >
          <BellIcon />

          {unreadCount > 0 && (
            <span className="notification-bell-badge" aria-hidden="true">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </button>
      </div>

      {panel}
    </>
  );
}
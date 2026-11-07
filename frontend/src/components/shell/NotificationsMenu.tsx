import { useEffect, useId, useRef, useState } from "react";
import { Bell } from "lucide-react";

import { Button } from "../ui";
import { useDismissOnOutside } from "../ui/useDismissOnOutside";
import { ErrorState, LoadingState, EmptyState } from "./RouteStates";

export interface NotificationEntry {
  id: string;
  title: string;
  message: string;
  createdAt: string;
  read: boolean;
  /** Resource the notification refers to, used to route on open. */
  resourceType?: string | null;
}

export interface NotificationsMenuLabels {
  trigger: string;
  panelTitle: string;
  unreadLabel: string;
  unreadCountLabel: (count: number) => string;
  markRead: string;
  markAllRead: string;
  loading: string;
  loadingMessage: string;
  emptyTitle: string;
  emptyMessage: string;
  errorTitle: string;
  errorMessage: string;
  retry: string;
}

export interface NotificationsMenuProps {
  labels: NotificationsMenuLabels;
  /** Loads the first page each time the panel opens. Pass a stable callback (useCallback) so it is not reloaded on every render. */
  load: () => Promise<NotificationEntry[]>;
  /** Unread count for the trigger badge. Loaded on mount, so the badge shows before the panel is opened. */
  unreadCount: () => Promise<number>;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  onOpenItem?: (entry: NotificationEntry) => void;
}

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; entries: NotificationEntry[] };

/**
 * Notification panel. Loads when opened, shows loading, empty and error states, and lets the user mark one or all as read.
 * Escape closes and returns focus to the trigger. Unread items carry a text label, not only a colour dot.
 */
export function NotificationsMenu({ labels, load, unreadCount, markRead, markAllRead, onOpenItem }: NotificationsMenuProps) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const requestId = useRef(0);
  const [badge, setBadge] = useState<number | null>(null);
  const [actionError, setActionError] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const panelId = useId();
  useDismissOnOutside(hostRef, open, () => {
    requestId.current++;
    setOpen(false);
  });

  const loadedUnread = state.status === "ready" ? state.entries.filter((entry) => !entry.read).length : 0;
  const unread = badge ?? loadedUnread;

  useEffect(() => {
    let cancelled = false;
    unreadCount()
      .then((count) => {
        if (!cancelled) setBadge(count);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [unreadCount]);

  function startLoad() {
    const request = ++requestId.current;
    setState({ status: "loading" });
    load()
      .then((entries) => {
        if (request === requestId.current) setState({ status: "ready", entries });
      })
      .catch(() => {
        if (request === requestId.current) setState({ status: "error" });
      });
  }

  function toggle() {
    if (open) {
      requestId.current++;
      setOpen(false);
      return;
    }
    setOpen(true);
    startLoad();
  }

  function close() {
    requestId.current++;
    setOpen(false);
    triggerRef.current?.focus();
  }

  async function handleMarkRead(id: string) {
    setActionError(false);
    try {
      await markRead(id);
      const wasUnread = state.status === "ready" && state.entries.some((entry) => entry.id === id && !entry.read);
      if (wasUnread) setBadge((count) => (count === null ? null : Math.max(0, count - 1)));
      setState((current) =>
        current.status === "ready"
          ? { status: "ready", entries: current.entries.map((entry) => (entry.id === id ? { ...entry, read: true } : entry)) }
          : current,
      );
    } catch {
      setActionError(true);
    }
  }

  async function handleMarkAll() {
    setActionError(false);
    try {
      await markAllRead();
      setBadge(0);
      setState((current) =>
        current.status === "ready"
          ? { status: "ready", entries: current.entries.map((entry) => ({ ...entry, read: true })) }
          : current,
      );
    } catch {
      setActionError(true);
    }
  }

  return (
    <div ref={hostRef} className="df-shell-popover-host">
      <button
        ref={triggerRef}
        type="button"
        className="df-shell-icon-button"
        aria-label={unread > 0 ? `${labels.trigger}, ${labels.unreadCountLabel(unread)}` : labels.trigger}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={toggle}
      >
        <Bell size={18} strokeWidth={1.8} aria-hidden="true" />
        {unread > 0 ? <span className="df-shell-count" aria-hidden="true">{unread > 9 ? "9+" : unread}</span> : null}
      </button>

      {open ? (
        <div
          id={panelId}
          role="dialog"
          aria-label={labels.panelTitle}
          className="df-shell-panel df-shell-panel--end"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              close();
            }
          }}
        >
          <div className="df-shell-panel-header">
            <h2 className="df-shell-panel-title">{labels.panelTitle}</h2>
            {state.status === "ready" && unread > 0 ? (
              <Button variant="tertiary" size="sm" onClick={handleMarkAll}>
                {labels.markAllRead}
              </Button>
            ) : null}
          </div>

          {actionError ? (
            <p className="df-field-error" role="alert">
              {labels.errorMessage}
            </p>
          ) : null}

          {state.status === "loading" || state.status === "idle" ? (
            <LoadingState title={labels.loading} message={labels.loadingMessage} />
          ) : null}

          {state.status === "error" ? (
            <ErrorState
              title={labels.errorTitle}
              message={labels.errorMessage}
              retryLabel={labels.retry}
              onRetry={startLoad}
            />
          ) : null}

          {state.status === "ready" && state.entries.length === 0 ? (
            <EmptyState title={labels.emptyTitle} message={labels.emptyMessage} />
          ) : null}

          {state.status === "ready" && state.entries.length > 0 ? (
            <ul className="df-shell-notification-list">
              {state.entries.map((entry) => (
                <li key={entry.id} className={`df-shell-notification${entry.read ? "" : " df-shell-notification--unread"}`}>
                  <button
                    type="button"
                    className="df-shell-notification-open"
                    onClick={() => {
                      onOpenItem?.(entry);
                      if (!entry.read) void handleMarkRead(entry.id);
                    }}
                  >
                    {entry.read ? null : <span className="df-visually-hidden">{labels.unreadLabel}: </span>}
                    <span className="df-shell-notification-title">{entry.title}</span>
                    <span className="df-shell-notification-message">{entry.message}</span>
                    <time dateTime={entry.createdAt} className="df-shell-notification-time">
                      {entry.createdAt}
                    </time>
                  </button>
                  {entry.read ? null : (
                    <Button variant="tertiary" size="sm" onClick={() => void handleMarkRead(entry.id)}>
                      {labels.markRead}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

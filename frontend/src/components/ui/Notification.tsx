import type { ReactNode } from "react";

export type NotificationTone = "info" | "success" | "warning" | "danger";

export interface NotificationProps {
  tone?: NotificationTone;
  title: string;
  children?: ReactNode;
  /** Shows a dismiss control. The label is required because the control is icon-only. */
  dismissLabel?: string;
  onDismiss?: () => void;
  action?: ReactNode;
}

/**
 * Inline notification. Danger and warning use role="alert" so the message is announced at once; other tones use role="status".
 * Colour is paired with a text label and an icon-free left rule, never colour alone.
 */
export function Notification({ tone = "info", title, children, dismissLabel, onDismiss, action }: NotificationProps) {
  const urgent = tone === "danger" || tone === "warning";
  return (
    <div role={urgent ? "alert" : "status"} className={`df-notification df-notification--${tone}`}>
      <div className="df-notification-body">
        <p className="df-notification-title">{title}</p>
        {children ? <div className="df-notification-text">{children}</div> : null}
        {action ? <div className="df-notification-action">{action}</div> : null}
      </div>
      {onDismiss && dismissLabel ? (
        <button type="button" className="df-btn df-btn--tertiary df-btn--sm df-btn--icon-only" aria-label={dismissLabel} onClick={onDismiss}>
          <span aria-hidden="true">×</span>
        </button>
      ) : null}
    </div>
  );
}

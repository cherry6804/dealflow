import { Settings } from "lucide-react";
import { useId, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import { useDismissOnOutside } from "../../../components/ui/useDismissOnOutside";
import { ThemeToggle } from "../../../theme/ThemeToggle";

/**
 * Settings menu in the common header. It reuses the existing destinations: the notification settings page and the
 * personal theme control. It holds no settings of its own.
 */
export function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const panelId = useId();
  useDismissOnOutside(hostRef, open, () => setOpen(false));

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  }

  return (
    <div ref={hostRef} className="df-ws-settings" onKeyDown={onKeyDown}>
      <button
        ref={triggerRef}
        type="button"
        className="df-shell-icon-button"
        aria-label="Settings"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <Settings size={18} strokeWidth={1.8} aria-hidden="true" />
      </button>

      {open ? (
        <div id={panelId} role="dialog" aria-label="Settings" className="df-ws-settings-panel">
          <section aria-labelledby={`${panelId}-notifications`}>
            <h2 id={`${panelId}-notifications`} className="df-ws-settings-heading">
              Notifications
            </h2>
            <Link to="/notification-preferences" className="df-ws-settings-link" onClick={() => setOpen(false)}>
              <span className="df-ws-settings-link-title">Notification settings</span>
              <span className="df-ws-settings-link-text">Email and in-app notification preferences</span>
            </Link>
          </section>

          <section aria-labelledby={`${panelId}-general`}>
            <h2 id={`${panelId}-general`} className="df-ws-settings-heading">
              General
            </h2>
            <div className="df-ws-settings-row">
              <div>
                <p className="df-ws-settings-link-title">Appearance</p>
                <p className="df-ws-settings-link-text">Light, dark, or match your system. Saved for your user on this browser.</p>
              </div>
              <ThemeToggle />
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

import { Check, ChevronDown, Building2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { useDismissOnOutside } from "../ui/useDismissOnOutside";

/* ---------- Organization switcher ---------- */

export interface OrganizationOption {
  id: string;
  name: string;
}

export interface OrganizationSwitcherLabels {
  trigger: string;
  listLabel: string;
  current: string;
  loading: string;
  error: string;
  retry: string;
  empty: string;
}

export interface OrganizationSwitcherProps {
  labels: OrganizationSwitcherLabels;
  organizations: readonly OrganizationOption[];
  selectedId: string | null;
  status: "ready" | "loading" | "error";
  onSelect: (organizationId: string) => void;
  onRetry: () => void;
}

/**
 * Switches the organization the session is scoped to. Selection calls `onSelect`, which the caller wires to the existing
 * organization context. The switcher holds no organization data of its own.
 * Listbox pattern: arrow keys move, Enter selects, Escape closes and returns focus to the trigger.
 */
export function OrganizationSwitcher({ labels, organizations, selectedId, status, onSelect, onRetry }: OrganizationSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();
  useDismissOnOutside(hostRef, open, () => setOpen(false));
  const selected = organizations.find((organization) => organization.id === selectedId);

  useEffect(() => {
    if (open && status === "ready") listRef.current?.focus();
  }, [open, status]);

  function choose(id: string) {
    setOpen(false);
    if (id !== selectedId) onSelect(id);
    triggerRef.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    if (event.key === "ArrowDown") setActive((index) => (index + 1) % organizations.length);
    else if (event.key === "ArrowUp") setActive((index) => (index - 1 + organizations.length) % organizations.length);
    else if (event.key === "Home") setActive(0);
    else if (event.key === "End") setActive(organizations.length - 1);
    else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    } else if (event.key === "Enter") {
      const option = organizations[active];
      if (option) choose(option.id);
      return;
    } else return;
    event.preventDefault();
  }

  const triggerName = status === "loading" ? labels.loading : selected?.name ?? labels.trigger;

  return (
    <div ref={hostRef} className="df-shell-popover-host">
      <button
        ref={triggerRef}
        type="button"
        className="df-shell-org-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`${labels.trigger}: ${triggerName}`}
        onClick={() => {
          if (!open) {
            setActive(Math.max(0, organizations.findIndex((organization) => organization.id === selectedId)));
          }
          setOpen((value) => !value);
        }}
      >
        <Building2 size={16} aria-hidden="true" />
        <span className="df-shell-org-name">{triggerName}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>

      {open ? (
        <div className="df-shell-panel df-shell-panel--start">
          {status === "loading" ? <p className="df-shell-panel-note" role="status">{labels.loading}</p> : null}
          {status === "error" ? (
            <div>
              <p className="df-field-error" role="alert">{labels.error}</p>
              <button type="button" className="df-btn df-btn--secondary df-btn--sm" onClick={onRetry}>
                {labels.retry}
              </button>
            </div>
          ) : null}
          {status === "ready" && organizations.length === 0 ? (
            <p className="df-shell-panel-note">{labels.empty}</p>
          ) : null}
          {status === "ready" && organizations.length > 0 ? (
            <ul
              id={listId}
              role="listbox"
              aria-label={labels.listLabel}
              tabIndex={-1}
              ref={listRef}
              className="df-shell-org-list"
              onKeyDown={onKeyDown}
            >
              {organizations.map((organization, index) => {
                const isSelected = organization.id === selectedId;
                return (
                  <li
                    key={organization.id}
                    role="option"
                    aria-selected={isSelected}
                    className={`df-shell-org-option${index === active ? " df-shell-org-option--active" : ""}`}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => choose(organization.id)}
                  >
                    <span>{organization.name}</span>
                    {isSelected ? (
                      <span className="df-shell-org-current">
                        <Check size={14} aria-hidden="true" />
                        <span className="df-visually-hidden">{labels.current}</span>
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/* ---------- Profile menu ---------- */

export interface ProfileMenuLabels {
  trigger: string;
  settings: string;
  signOut: string;
  signingOut: string;
}

export interface ProfileMenuProps {
  labels: ProfileMenuLabels;
  name: string;
  email: string;
  initials: string;
  signingOut: boolean;
  onOpenSettings: () => void;
  onSignOut: () => void;
}

/**
 * Account control. The header shows only the avatar. Activating it opens a dialog with the account information and the
 * supported account actions. Escape and an outside press close it and return focus to the avatar; focus moves into the
 * dialog when it opens.
 */
export function ProfileMenu({ labels, name, email, initials, signingOut, onOpenSettings, onSignOut }: ProfileMenuProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const panelId = useId();
  useDismissOnOutside(hostRef, open, () => setOpen(false));

  useEffect(() => {
    if (open) panelRef.current?.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
  }, [open]);

  function close() {
    setOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <div ref={hostRef} className="df-shell-popover-host df-shell-profile">
      <button
        ref={triggerRef}
        type="button"
        className="df-shell-avatar-trigger"
        aria-label={labels.trigger}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="df-shell-avatar" aria-hidden="true">
          {initials}
        </span>
      </button>

      {open ? (
        <div
          ref={panelRef}
          id={panelId}
          role="dialog"
          aria-label={labels.trigger}
          className="df-shell-panel df-shell-panel--end df-shell-profile-panel"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              close();
            }
          }}
        >
          <div className="df-shell-account">
            <span className="df-shell-avatar" aria-hidden="true">
              {initials}
            </span>
            <div className="df-shell-account-text">
              <p className="df-shell-account-name">{name}</p>
              <p className="df-shell-account-email">{email}</p>
            </div>
          </div>
          <div className="df-shell-account-actions">
            <button
              type="button"
              className="df-shell-menu-action"
              disabled={signingOut}
              onClick={() => {
                setOpen(false);
                onOpenSettings();
              }}
            >
              {labels.settings}
            </button>
            <button
              type="button"
              className="df-shell-menu-action df-shell-menu-action--danger"
              disabled={signingOut}
              onClick={() => {
                setOpen(false);
                onSignOut();
              }}
            >
              {signingOut ? labels.signingOut : labels.signOut}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

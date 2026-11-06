import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import type { KeyboardEvent, ReactElement, ReactNode } from "react";

/* ---------- Dialog and drawer ---------- */

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Translated name for the icon-only close control. */
  closeLabel: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  /** Drawers slide in from the right and use the full height. */
  placement?: "center" | "end";
}

/**
 * Modal dialog on the native <dialog> element. showModal traps focus and makes the rest of the page inert.
 * Where showModal is missing (older engines, jsdom), the open attribute is used instead and focus is moved manually.
 * On close, focus returns to the element that opened the dialog.
 */
export function Dialog({ open, onClose, title, closeLabel, description, children, footer, placement = "center" }: DialogProps) {
  const ref = useRef<HTMLDialogElement | null>(null);
  const opener = useRef<Element | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      if (typeof dialog.showModal === "function") dialog.showModal();
      else {
        dialog.setAttribute("open", "");
        dialog.querySelector<HTMLElement>("button, [href], input, select, textarea")?.focus();
      }
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      if (opener.current instanceof HTMLElement) opener.current.focus();
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`df-dialog df-dialog--${placement}`}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="df-dialog-header">
        <h2 id={titleId} className="df-dialog-title">
          {title}
        </h2>
        <button type="button" className="df-btn df-btn--tertiary df-btn--sm df-btn--icon-only" aria-label={closeLabel} onClick={onClose}>
          <span aria-hidden="true">×</span>
        </button>
      </header>
      {description ? (
        <p id={descriptionId} className="df-dialog-description">
          {description}
        </p>
      ) : null}
      <div className="df-dialog-body">{children}</div>
      {footer ? <footer className="df-dialog-footer">{footer}</footer> : null}
    </dialog>
  );
}

/* ---------- Menu ---------- */

export interface MenuItem {
  id: string;
  label: string;
  icon?: ReactNode;
  destructive?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

export interface MenuProps {
  triggerLabel: string;
  items: readonly MenuItem[];
  align?: "start" | "end";
}

/**
 * Contextual menu. Enter or Space on the trigger opens it and focuses the first item. Arrow keys move, Home and End jump,
 * Escape closes and returns focus to the trigger. Disabled items are skipped by the arrow keys.
 */
export function Menu({ triggerLabel, items, align = "start" }: MenuProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const panelId = useId();

  const enabledIndexes = items.map((item, index) => (item.disabled ? -1 : index)).filter((index) => index >= 0);

  function focusItem(position: number) {
    const index = enabledIndexes[(position + enabledIndexes.length) % enabledIndexes.length];
    if (index !== undefined) itemRefs.current[index]?.focus();
  }

  function close(returnFocus: boolean) {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }

  function onPanelKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = enabledIndexes.indexOf(itemRefs.current.indexOf(document.activeElement as HTMLButtonElement));
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      focusItem(current + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusItem(current < 0 ? enabledIndexes.length - 1 : current - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusItem(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusItem(enabledIndexes.length - 1);
    } else if (event.key === "Tab") {
      close(false);
    }
  }

  return (
    <div className="df-menu">
      <button
        ref={triggerRef}
        type="button"
        className="df-btn df-btn--secondary df-btn--md"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => {
          setOpen((value) => !value);
          if (!open) queueMicrotask(() => focusItem(0));
        }}
      >
        <span className="df-btn-label">{triggerLabel}</span>
      </button>
      {open ? (
        <div
          id={panelId}
          role="menu"
          aria-label={triggerLabel}
          className={`df-menu-panel df-menu-panel--${align}`}
          onKeyDown={onPanelKeyDown}
        >
          {items.map((item, index) => (
            <button
              key={item.id}
              ref={(node) => {
                itemRefs.current[index] = node;
              }}
              type="button"
              role="menuitem"
              tabIndex={-1}
              disabled={item.disabled}
              className={`df-menu-item${item.destructive ? " df-menu-item--destructive" : ""}`}
              onClick={() => {
                item.onSelect();
                close(true);
              }}
            >
              {item.icon ? <span className="df-menu-icon" aria-hidden="true">{item.icon}</span> : null}
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/* ---------- Popover (disclosure panel) ---------- */

export interface PopoverProps {
  triggerLabel: string;
  children: ReactNode;
}

/** Disclosure panel for rich content that is not a list of commands. Escape closes it and returns focus. */
export function Popover({ triggerLabel, children }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  return (
    <div className="df-popover">
      <button
        ref={triggerRef}
        type="button"
        className="df-btn df-btn--secondary df-btn--md"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="df-btn-label">{triggerLabel}</span>
      </button>
      {open ? (
        <div
          id={panelId}
          className="df-popover-panel"
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
              triggerRef.current?.focus();
            }
          }}
        >
          {children}
        </div>
      ) : null}
    </div>
  );
}

/* ---------- Tooltip ---------- */

export interface TooltipProps {
  label: string;
  children: ReactElement<{ "aria-describedby"?: string }>;
}

/**
 * Tooltip shown on hover and keyboard focus. It supplements a visible or accessible name; it never carries the only label.
 * Escape hides it. The tooltip text is linked to the child with aria-describedby.
 */
export function Tooltip({ label, children }: TooltipProps) {
  const [visible, setVisible] = useState(false);
  const tooltipId = useId();
  const child = Children.only(children);
  if (!isValidElement(child)) return children;
  return (
    <span
      className="df-tooltip-host"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
      onKeyDown={(event) => {
        if (event.key === "Escape") setVisible(false);
      }}
    >
      {cloneElement(child, { "aria-describedby": tooltipId })}
      {visible ? (
        <span id={tooltipId} role="tooltip" className="df-tooltip">
          {label}
        </span>
      ) : null}
    </span>
  );
}

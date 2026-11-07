import type { ReactNode } from "react";

import { Dialog } from "./Overlays";

export interface AppDrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Translated name for the close control. */
  closeLabel: string;
  /** Short description under the title, for example what the settings control. */
  description?: string;
  /** Fixed footer for the drawer's actions. */
  footer?: ReactNode;
  busy?: boolean;
  dirty?: boolean;
  children: ReactNode;
}

/**
 * A side drawer for configuration panels such as settings, preferences and column layout. It uses the shared dialog primitive, so
 * focus, Escape, backdrop and unsaved-change rules are the same as every other overlay. It is full-height on the right, and full
 * screen on phones.
 */
export function AppDrawer({ open, onClose, title, closeLabel, description, footer, busy, dirty, children }: AppDrawerProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      closeLabel={closeLabel}
      description={description}
      placement="end"
      busy={busy}
      dirty={dirty}
      footer={footer}
    >
      {children}
    </Dialog>
  );
}

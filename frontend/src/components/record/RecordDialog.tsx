import type { ReactNode } from "react";

import { Dialog, type DialogProps } from "../ui";
import "./record.css";

export interface RecordDialogProps {
  open: boolean;
  onClose: () => void;
  /** Record type or module context, shown above the title, for example "Contact". */
  eyebrow: string;
  /** Record name or identifier. */
  title: string;
  /** Translated name for the close control. */
  closeLabel: string;
  /** Optional status indicator shown beside the title. */
  status?: ReactNode;
  /** Contextual actions shown in the header, before the close control. */
  headerActions?: ReactNode;
  /** Main record information: fields, business information, notes, related records and activity. */
  main: ReactNode;
  /** Contextual sidebar: status, owner, dates and supported actions. Omit for single-column records. */
  aside?: ReactNode;
  /** Fixed footer with the primary and secondary actions. Omit for read-only records. */
  footer?: DialogProps["footer"];
  /** True while a request runs; dismissal is blocked until it settles. */
  busy?: boolean;
  /** True when the form has unsaved changes; dismissal asks for confirmation. */
  dirty?: boolean;
}

/**
 * The shared record dialog. The header (type, title, status, actions, close) and the footer stay fixed; the content scrolls on
 * its own. With an aside, desktop shows the main content and sidebar side by side; phones stack them. Each module supplies its
 * own fields, sections and actions.
 */
export function RecordDialog({ open, onClose, eyebrow, title, closeLabel, status, headerActions, main, aside, footer, busy, dirty }: RecordDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      closeLabel={closeLabel}
      eyebrow={eyebrow}
      status={status}
      headerActions={headerActions}
      footer={footer}
      size={aside ? "lg" : "md"}
      busy={busy}
      dirty={dirty}
    >
      {aside ? (
        <div className="df-record-layout">
          <section className="df-record-main" aria-label="Record information">
            {main}
          </section>
          <aside className="df-record-aside" aria-label="Record properties">
            {aside}
          </aside>
        </div>
      ) : (
        <section className="df-record-main" aria-label="Record information">
          {main}
        </section>
      )}
    </Dialog>
  );
}

/** A labelled property row. Read-only values use this; editable values use a field control instead. */
export function RecordProperty({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="df-record-property">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

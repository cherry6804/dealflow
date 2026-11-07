import type { ReactNode } from "react";

import { Dialog } from "../ui";
import "./record.css";

export interface RecordDetailDialogProps {
  open: boolean;
  onClose: () => void;
  /** Record identifier shown above the title, for example "Contact". */
  eyebrow: string;
  title: string;
  closeLabel: string;
  /** Main record information: details, notes and related records. */
  main: ReactNode;
  /** Contextual properties: status, dates and linked records. */
  aside: ReactNode;
  footer?: ReactNode;
}

/**
 * Shared record-detail dialog. A large centred dialog with the main record information on the left and contextual
 * properties on the right. Escape and the close control close it; focus returns to the row that opened it. On phones it
 * fills the screen and the two sections stack.
 */
export function RecordDetailDialog({ open, onClose, eyebrow, title, closeLabel, main, aside, footer }: RecordDetailDialogProps) {
  return (
    <Dialog open={open} onClose={onClose} title={title} closeLabel={closeLabel} size="lg" footer={footer}>
      <p className="df-record-eyebrow">{eyebrow}</p>
      <div className="df-record-layout">
        <section className="df-record-main" aria-label="Record information">
          {main}
        </section>
        <aside className="df-record-aside" aria-label="Record properties">
          {aside}
        </aside>
      </div>
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

import type { ReactNode } from "react";

import { Badge, type BadgeTone } from "../ui";
import "./nested-records.css";

export interface NestedSummaryItem {
  label: string;
  /** Visible value. Use formatMoney / totalsByCurrency output, never a computed figure of your own. */
  value: ReactNode;
  /** Highlights a value that needs attention, such as overdue items. */
  attention?: boolean;
}

/** Summary tiles above a nested list. Wraps to two columns on phones. */
export function NestedSummary({ items, label }: { items: readonly NestedSummaryItem[]; label: string }) {
  return (
    <dl className="df-nested-summary" aria-label={label}>
      {items.map((item) => (
        <div key={item.label} className={`df-nested-summary-tile${item.attention ? " df-nested-summary-tile--attention" : ""}`}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface NestedMetaItem {
  label: string;
  value: ReactNode;
}

export interface NestedRecordCardProps {
  /** Heading of the record, for example the milestone name or the commission basis. */
  title: string;
  /** Primary amount shown under the title. Already formatted. */
  amount: string;
  status: { label: string; tone: BadgeTone };
  meta: readonly NestedMetaItem[];
  notes?: string | null;
  /** Action buttons, shown at the foot of the card only when there are any. */
  actions?: ReactNode;
}

export function NestedRecordCard({ title, amount, status, meta, notes, actions }: NestedRecordCardProps) {
  return (
    <article className="df-nested-card">
      <header className="df-nested-card-header">
        <div className="df-nested-card-heading">
          <h4 className="df-nested-card-title">{title}</h4>
          <p className="df-nested-card-amount">{amount}</p>
        </div>
        <Badge tone={status.tone}>{status.label}</Badge>
      </header>

      {meta.length > 0 ? (
        <dl className="df-nested-card-meta">
          {meta.map((item) => (
            <div key={item.label}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {notes ? <p className="df-nested-card-notes">{notes}</p> : null}

      {actions ? <div className="df-nested-card-actions">{actions}</div> : null}
    </article>
  );
}

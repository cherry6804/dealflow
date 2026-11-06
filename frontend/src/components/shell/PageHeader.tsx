import type { ReactNode } from "react";

export interface PageHeaderProps {
  title: string;
  /** One line with counts or context, for example "48 records · 3 need attention". */
  description?: string;
  /** Contextual actions. One primary action per region; the rest are secondary or tertiary. */
  actions?: ReactNode;
}

/** Page title, description and contextual actions. Stacks on narrow widths so actions never overflow. */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <header className="df-page-header">
      <div className="df-page-header-text">
        <h1 className="df-page-title">{title}</h1>
        {description ? <p className="df-page-description">{description}</p> : null}
      </div>
      {actions ? <div className="df-page-actions">{actions}</div> : null}
    </header>
  );
}

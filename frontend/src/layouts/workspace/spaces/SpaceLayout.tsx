import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import type { SpaceDefinition, SpaceTab } from "./spaceConfig";

export interface SpaceLayoutProps {
  space: SpaceDefinition;
  /** Active tab, resolved from the route. Undefined when the route is not one of the space's tabs. */
  activeTab: SpaceTab | undefined;
  /** Accessible name of the secondary navigation, for example "Sales sections". */
  navigationLabel: string;
  /** Text under the space title. */
  description?: string;
  /** Contextual action area, right-aligned in the space bar. */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * Shared layout for every space. The space bar shows the space's icon, title and description; the secondary navigation
 * lists its tabs. The page content renders below. Placeholder tabs open a clearly marked "not yet available" state.
 */
export function SpaceLayout({ space, activeTab, navigationLabel, description, actions, children }: SpaceLayoutProps) {
  const Icon = space.icon;
  return (
    <section className="df-space" aria-labelledby={`df-space-title-${space.id}`}>
      <header className="df-space-bar">
        <div className="df-space-identity">
          <span className="df-space-icon" aria-hidden="true">
            <Icon size={20} strokeWidth={1.8} />
          </span>
          <div>
            <h2 id={`df-space-title-${space.id}`} className="df-space-title">
              {space.label}
            </h2>
            {description ? <p className="df-space-description">{description}</p> : null}
          </div>
        </div>
        {actions ? <div className="df-space-actions">{actions}</div> : null}
      </header>

      <nav aria-label={navigationLabel} className="df-space-tabs">
        <ul>
          {space.tabs.map((tab) => {
            const current = activeTab?.id === tab.id;
            return (
              <li key={tab.id}>
                <Link
                  to={tab.to ?? "/"}
                  aria-current={current ? "page" : undefined}
                  className={`df-space-tab${current ? " df-space-tab--active" : ""}${tab.placeholder ? " df-space-tab--placeholder" : ""}`}
                >
                  {tab.label}
                  {tab.placeholder ? <span className="df-space-tab-note">Not yet available</span> : null}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="df-space-content">{children}</div>
    </section>
  );
}

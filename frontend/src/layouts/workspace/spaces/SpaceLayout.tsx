import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { withBasePath } from "../../../components/shell/shellModel";
import type { SpaceDefinition, SpaceTab } from "./spaceConfig";

export interface SpaceLayoutProps {
  space: SpaceDefinition;
  /** Active tab, resolved from the route. Undefined when the route is not one of the space's tabs. */
  activeTab: SpaceTab | undefined;
  /** Accessible name of the secondary navigation, for example "Sales sections". */
  navigationLabel: string;
  /** Contextual action area, right-aligned in the space bar. */
  actions?: ReactNode;
  /** Prefix for preview mounts. Production leaves it empty. */
  basePath?: string;
  children: ReactNode;
}

/**
 * Shared layout for every space. The space bar shows the space's icon, title and description; the secondary navigation
 * lists its tabs. The page content renders below. Placeholder tabs open a clearly marked "not yet available" state.
 */
export function SpaceLayout({ space, activeTab, navigationLabel, actions, basePath = "", children }: SpaceLayoutProps) {
  return (
    <section className="df-space" aria-label={space.label}>
      <div className="df-space-tabbar">
      <nav aria-label={navigationLabel} className="df-space-tabs">
        <ul>
          {space.tabs.map((tab) => {
            const current = activeTab?.id === tab.id;
            return (
              <li key={tab.id}>
                <Link
                  to={withBasePath(tab.to ?? "/", basePath)}
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
      {actions ? <div className="df-space-actions">{actions}</div> : null}
      </div>

      <div className="df-space-content">{children}</div>
    </section>
  );
}

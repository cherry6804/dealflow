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
  /** Space-level actions, right-aligned in the space header. */
  actions?: ReactNode;
  /** Prefix for preview mounts. Production leaves it empty. */
  basePath?: string;
  children: ReactNode;
}

/**
 * Shared layout for every space: a space header (icon, name and space-level actions), then the horizontal tab bar with the
 * active tab underlined, then the page. Every space uses this component, so the structure is identical across spaces.
 * Placeholder tabs open a clearly marked "not yet available" state.
 */
export function SpaceLayout({ space, activeTab, navigationLabel, actions, basePath = "", children }: SpaceLayoutProps) {
  const Icon = space.icon;
  return (
    <section className="df-space" aria-label={space.label}>
      <header className="df-space-header">
        <div className="df-space-identity">
          <span className="df-space-icon" aria-hidden="true">
            <Icon size={18} strokeWidth={1.8} />
          </span>
          <h2 className="df-space-title">{space.label}</h2>
        </div>
        {actions ? <div className="df-space-actions">{actions}</div> : null}
      </header>

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
      </div>

      <div className="df-space-content">{children}</div>
    </section>
  );
}

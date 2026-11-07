import { Link } from "react-router-dom";

import type { SpaceDefinition } from "./spaceConfig";
import { resolveSpaceLocation } from "./spaceConfig";
import { spaceHref } from "./spaceNavigation";
import type { SidebarDensity } from "./spacePreferences";

export interface WorkspaceSidebarProps {
  spaces: readonly SpaceDefinition[];
  pathname: string;
  /** Icons only (true) or icons with labels (false). */
  rail: boolean;
  density: SidebarDensity;
  label: string;
  heading: string;
  onNavigate?: () => void;
}

/**
 * The personal sidebar. Pinned spaces come first; the active space is marked with aria-current. In rail mode every space
 * keeps an accessible name, because its label is not visible.
 */
export function WorkspaceSidebar({ spaces, pathname, rail, density, label, heading, onNavigate }: WorkspaceSidebarProps) {
  const active = resolveSpaceLocation(pathname)?.space.id;
  return (
    <nav
      aria-label={label}
      className={`df-ws-sidebar${rail ? " df-ws-sidebar--rail" : ""} df-ws-sidebar--${density}`}
    >
      {!rail ? <p className="df-ws-sidebar-heading">{heading}</p> : null}
      <ul className="df-ws-sidebar-list">
        {spaces.map((space) => {
          const Icon = space.icon;
          const isActive = active === space.id;
          return (
            <li key={space.id}>
              <Link
                to={spaceHref(space)}
                aria-current={isActive ? "page" : undefined}
                aria-label={rail ? space.label : undefined}
                title={rail ? space.label : undefined}
                className={`df-ws-space${isActive ? " df-ws-space--active" : ""}`}
                onClick={onNavigate}
              >
                <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
                {rail ? null : <span className="df-ws-space-label">{space.label}</span>}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

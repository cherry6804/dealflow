import { Link } from "react-router-dom";

import { withBasePath } from "../../../components/shell/shellModel";
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
  /** Prefix for preview mounts. Production leaves it empty. */
  basePath?: string;
}

/**
 * The personal sidebar. Spaces appear in the user's arrangement (pinned first). The active space is marked with
 * aria-current. In icons-only mode every space keeps an accessible name, because its label is not visible.
 */
export function WorkspaceSidebar({ spaces, pathname, rail, density, label, heading, basePath = "" }: WorkspaceSidebarProps) {
  const active = resolveSpaceLocation(pathname)?.space.id;
  return (
    <nav aria-label={label} className={`df-ws-sidebar${rail ? " df-ws-sidebar--rail" : ""} df-ws-sidebar--${density}`}>
      {rail ? null : <p className="df-ws-sidebar-heading">{heading}</p>}
      <ul className="df-ws-sidebar-list">
        {spaces.map((space) => {
          const Icon = space.icon;
          const isActive = active === space.id;
          return (
            <li key={space.id}>
              <Link
                to={withBasePath(spaceHref(space), basePath)}
                aria-current={isActive ? "page" : undefined}
                aria-label={rail ? space.label : undefined}
                title={rail ? space.label : undefined}
                className={`df-ws-space${isActive ? " df-ws-space--active" : ""}`}
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

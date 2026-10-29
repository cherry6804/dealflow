import { useMemo } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { NavLink } from "react-router-dom";

import type { WorkspacePreferences } from "./workspacePreferences";
import { buildSidebarSections } from "./sidebarSections";
import type { WorkspaceModule } from "./workspaceSpaces";
import "./GlobalSidebarNav.css";

interface GlobalSidebarNavProps {
  readonly preferences: WorkspacePreferences;
  readonly onToggleSpace: (spaceId: string) => void;
  readonly onNavigate?: () => void;
  /** Icon-only rail. Defaults to the user's collapsed preference. */
  readonly iconsOnly?: boolean;
}

export default function GlobalSidebarNav({
  preferences,
  onToggleSpace,
  onNavigate,
  iconsOnly,
}: GlobalSidebarNavProps) {
  const sections = useMemo(
    () => buildSidebarSections(preferences),
    [preferences],
  );

  const collapsed = iconsOnly ?? preferences.sidebarCollapsed;

  function renderItem(module: WorkspaceModule) {
    const Icon = module.icon;

    return (
      <NavLink
        key={module.to}
        to={module.to}
        end={module.to === "/"}
        onClick={onNavigate}
        className={({ isActive }) =>
          `workspace-nav-link${isActive ? " is-active" : ""}`
        }
        title={collapsed ? module.label : undefined}
      >
        <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
        <span>{module.label}</span>
      </NavLink>
    );
  }

  return (
    <>
      {sections.pinned.length > 0 && (
        <>
          <span className="workspace-nav-caption">PINNED</span>
          {sections.pinned.map(renderItem)}
          <div className="workspace-nav-separator" aria-hidden="true" />
        </>
      )}

      {sections.global.map(renderItem)}

      {sections.spaces.length > 0 && (
        <span className="workspace-nav-caption">SPACES</span>
      )}

      {sections.spaces.map(({ space, expanded, modules }) => {
        const SpaceIcon = space.icon;

        // Collapsed sidebar: show every destination as an icon so no
        // navigation is lost. Expanded sidebar: one toggle per space.
        if (collapsed) {
          return modules.map(renderItem);
        }

        const panelId = `workspace-space-${space.id}`;

        return (
          <div className="workspace-space" key={space.id}>
            <button
              type="button"
              className="workspace-space-toggle"
              aria-expanded={expanded}
              aria-controls={panelId}
              onClick={() => onToggleSpace(space.id)}
            >
              <SpaceIcon size={18} strokeWidth={1.8} aria-hidden="true" />
              <span>{space.label}</span>
              {expanded ? (
                <ChevronDown
                  size={16}
                  strokeWidth={1.8}
                  className="workspace-space-chevron"
                  aria-hidden="true"
                />
              ) : (
                <ChevronRight
                  size={16}
                  strokeWidth={1.8}
                  className="workspace-space-chevron"
                  aria-hidden="true"
                />
              )}
            </button>

            <div
              id={panelId}
              className="workspace-space-items"
              hidden={!expanded}
            >
              {modules.map(renderItem)}
            </div>
          </div>
        );
      })}
    </>
  );
}

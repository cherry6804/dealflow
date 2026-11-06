import { ChevronRight } from "lucide-react";
import { NavLink } from "react-router-dom";

import type { WorkspaceModule } from "../../layouts/workspace/workspaceSpaces";
import type { SidebarSections } from "../../layouts/workspace/sidebarSections";
import { isRouteActive, withBasePath, type Breadcrumb } from "./shellModel";

/* ---------- Breadcrumbs ---------- */

export interface BreadcrumbsProps {
  label: string;
  items: readonly Breadcrumb[];
}

export function Breadcrumbs({ label, items }: BreadcrumbsProps) {
  return (
    <nav aria-label={label} className="df-shell-breadcrumbs">
      <ol>
        {items.map((item, index) => {
          const current = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`}>
              {current || !item.to ? (
                <span aria-current={current ? "page" : undefined}>{item.label}</span>
              ) : (
                <NavLink to={item.to}>{item.label}</NavLink>
              )}
              {current ? null : <ChevronRight size={14} aria-hidden="true" />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/* ---------- Sidebar ---------- */

export interface SidebarNavProps {
  label: string;
  sections: SidebarSections;
  pathname: string;
  /** Collapsed rail shows icons only; each link keeps an accessible name. */
  collapsed: boolean;
  basePath?: string;
  pinnedLabel: string;
  globalLabel: string;
  /** Called with the space id when its disclosure is toggled. */
  onToggleSpace: (spaceId: string) => void;
  /** Called when a link is followed, so a mobile drawer can close. */
  onNavigate?: () => void;
}

function ModuleLink({
  module,
  pathname,
  collapsed,
  basePath,
  onNavigate,
}: {
  module: WorkspaceModule;
  pathname: string;
  collapsed: boolean;
  basePath: string;
  onNavigate?: () => void;
}) {
  const active = isRouteActive(pathname, module.to);
  const Icon = module.icon;
  return (
    <NavLink
      to={withBasePath(module.to, basePath)}
      end={module.to === "/"}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? module.label : undefined}
      title={collapsed ? module.label : undefined}
      className={`df-shell-link${active ? " df-shell-link--active" : ""}`}
      onClick={onNavigate}
    >
      <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
      {collapsed ? null : <span>{module.label}</span>}
    </NavLink>
  );
}

export function SidebarNav({
  label,
  sections,
  pathname,
  collapsed,
  basePath = "",
  pinnedLabel,
  globalLabel,
  onToggleSpace,
  onNavigate,
}: SidebarNavProps) {
  const linkProps = { pathname, collapsed, basePath, onNavigate };
  return (
    <nav aria-label={label} className={`df-shell-sidebar-nav${collapsed ? " df-shell-sidebar-nav--rail" : ""}`}>
      {sections.pinned.length > 0 ? (
        <div className="df-shell-group">
          {collapsed ? null : <h2 className="df-shell-group-label">{pinnedLabel}</h2>}
          {sections.pinned.map((module) => (
            <ModuleLink key={module.label} module={module} {...linkProps} />
          ))}
        </div>
      ) : null}

      <div className="df-shell-group">
        {collapsed ? null : <h2 className="df-shell-group-label">{globalLabel}</h2>}
        {sections.global.map((module) => (
          <ModuleLink key={module.label} module={module} {...linkProps} />
        ))}
      </div>

      {sections.spaces.map((section) => {
        const panelId = `df-space-${section.space.id}`;
        const SpaceIcon = section.space.icon;
        return (
          <div className="df-shell-group" key={section.space.id}>
            <button
              type="button"
              className="df-shell-space-toggle"
              aria-expanded={section.expanded}
              aria-controls={panelId}
              aria-label={collapsed ? section.space.label : undefined}
              title={collapsed ? section.space.label : undefined}
              onClick={() => onToggleSpace(section.space.id)}
            >
              <SpaceIcon size={18} strokeWidth={1.8} aria-hidden="true" />
              {collapsed ? null : (
                <>
                  <span>{section.space.label}</span>
                  <ChevronRight
                    size={14}
                    aria-hidden="true"
                    className={`df-shell-space-chevron${section.expanded ? " df-shell-space-chevron--open" : ""}`}
                  />
                </>
              )}
            </button>
            {section.expanded ? (
              <div id={panelId} className="df-shell-space-items">
                {section.modules.map((module) => (
                  <ModuleLink key={module.label} module={module} {...linkProps} />
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}

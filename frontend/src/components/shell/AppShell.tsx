import { Menu as MenuIcon, PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import type { SidebarSections } from "../../layouts/workspace/sidebarSections";
import type { WorkspaceModule } from "../../layouts/workspace/workspaceSpaces";
import { ThemeToggle } from "../../theme/ThemeToggle";
import { Dialog } from "../ui";
import { CommandPalette, type CommandPaletteLabels } from "./CommandPalette";
import { Breadcrumbs, SidebarNav } from "./Navigation";
import { NotificationsMenu, type NotificationEntry, type NotificationsMenuLabels } from "./NotificationsMenu";
import { OrganizationSwitcher, ProfileMenu, type OrganizationSwitcherLabels, type OrganizationOption, type ProfileMenuLabels } from "./HeaderMenus";
import { buildBreadcrumbs, filterVisibleModules, type CanAccess, type ShellCommand } from "./shellModel";
import { useViewport } from "./useViewport";

export interface AppShellLabels {
  productName: string;
  skipToContent: string;
  mainNavigation: string;
  navigationTitle: string;
  openNavigation: string;
  closeNavigation: string;
  collapseSidebar: string;
  expandSidebar: string;
  search: string;
  searchShortcut: string;
  homeBreadcrumb: string;
  breadcrumbs: string;
  pinnedGroup: string;
  globalGroup: string;
  closeLabel: string;
  palette: CommandPaletteLabels;
  organization: OrganizationSwitcherLabels;
  notifications: NotificationsMenuLabels;
  profile: ProfileMenuLabels;
}

export interface ShellUser {
  name: string;
  email: string;
  initials: string;
}

export interface AppShellProps {
  labels: AppShellLabels;
  pathname: string;
  /** Static module list, used for breadcrumbs and command lists. Permission filtering is applied inside the shell. */
  modules: readonly WorkspaceModule[];
  sections: SidebarSections;
  canAccess: CanAccess;
  /** Module label to permission key. Defaults to the shell's built-in map, which is empty until permissions are exposed. */
  permissionByModule?: Readonly<Record<string, string>>;
  /** Prefix for preview mounts. Production leaves it empty. */
  basePath?: string;
  commands: readonly ShellCommand[];
  user: ShellUser;
  signingOut: boolean;
  onSignOut: () => void;
  onOpenSettings: () => void;
  organizations: readonly OrganizationOption[];
  selectedOrganizationId: string | null;
  organizationStatus: "ready" | "loading" | "error";
  onSelectOrganization: (id: string) => void;
  onRetryOrganizations: () => void;
  notifications: {
    load: () => Promise<NotificationEntry[]>;
    unreadCount: () => Promise<number>;
    markRead: (id: string) => Promise<void>;
    markAllRead: () => Promise<void>;
    onOpenItem?: (entry: NotificationEntry) => void;
  };
  /** Sidebar preferences. The caller decides where they are stored (device or account). */
  sidebarCollapsed: boolean;
  onSidebarCollapsedChange: (collapsed: boolean) => void;
  onToggleSpace: (spaceId: string) => void;
  children: ReactNode;
}

/**
 * Application shell: header, organization switcher, search and commands, notifications, profile, sidebar and
 * breadcrumbs. Desktop shows the sidebar in full or as a rail; tablet forces the rail; mobile moves navigation into a
 * drawer opened from the header.
 *
 * Keyboard: Ctrl+K or Cmd+K opens the palette anywhere; "/" opens it when no text field has focus.
 */
export function AppShell({
  labels,
  pathname,
  modules,
  sections,
  canAccess,
  permissionByModule,
  basePath = "",
  commands,
  user,
  signingOut,
  onSignOut,
  onOpenSettings,
  organizations,
  selectedOrganizationId,
  organizationStatus,
  onSelectOrganization,
  onRetryOrganizations,
  notifications,
  sidebarCollapsed,
  onSidebarCollapsedChange,
  onToggleSpace,
  children,
}: AppShellProps) {
  const viewport = useViewport();
  const [paletteOpen, setPaletteOpen] = useState(false);
  // The drawer belongs to the route it was opened on and to the mobile band, so navigating or resizing closes it.
  const [drawerPath, setDrawerPath] = useState<string | null>(null);
  const drawerOpen = viewport === "mobile" && drawerPath === pathname;

  // Permission filtering happens once, here, so every surface shows the same visible set.
  const visibleSections = useMemo<SidebarSections>(() => {
    const spaces = sections.spaces
      .map((section) => ({ ...section, modules: filterVisibleModules(section.modules, canAccess, permissionByModule) }))
      .filter((section) => section.modules.length > 0);
    return {
      pinned: filterVisibleModules(sections.pinned, canAccess, permissionByModule),
      global: filterVisibleModules(sections.global, canAccess, permissionByModule),
      spaces,
    };
  }, [sections, canAccess, permissionByModule]);

  const visibleCommands = useMemo(
    () => commands.filter((command) => command.permission === undefined || canAccess(command.permission)),
    [commands, canAccess],
  );

  const breadcrumbs = useMemo(
    () => buildBreadcrumbs(pathname, modules, labels.homeBreadcrumb, basePath),
    [pathname, modules, labels.homeBreadcrumb, basePath],
  );

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target;
      const editable = target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable='true']") !== null;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      } else if (event.key === "/" && !editable && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        setPaletteOpen(true);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const railMode = sidebarCollapsed || viewport === "tablet";
  const sidebarNav = (
    <SidebarNav
      label={labels.mainNavigation}
      sections={visibleSections}
      pathname={pathname}
      collapsed={viewport === "mobile" ? false : railMode}
      basePath={basePath}
      pinnedLabel={labels.pinnedGroup}
      globalLabel={labels.globalGroup}
      onToggleSpace={onToggleSpace}
      onNavigate={() => setDrawerPath(null)}
    />
  );

  return (
    <div className={`df-shell${railMode && viewport !== "mobile" ? " df-shell--rail" : ""}`}>
      <a className="df-shell-skip" href="#df-shell-main">
        {labels.skipToContent}
      </a>

      <header className="df-shell-header">
        {viewport === "mobile" ? (
          <button
            type="button"
            className="df-shell-icon-button"
            aria-label={labels.openNavigation}
            aria-expanded={drawerOpen}
            aria-controls="df-shell-drawer"
            onClick={() => setDrawerPath(pathname)}
          >
            <MenuIcon size={18} aria-hidden="true" />
          </button>
        ) : null}

        <div className="df-shell-brand" aria-hidden="true">
          <span className="df-shell-brand-mark">D</span>
          {viewport === "mobile" ? null : <span className="df-shell-brand-name">{labels.productName}</span>}
        </div>

        <OrganizationSwitcher
          labels={labels.organization}
          organizations={organizations}
          selectedId={selectedOrganizationId}
          status={organizationStatus}
          onSelect={onSelectOrganization}
          onRetry={onRetryOrganizations}
        />

        <button
          type="button"
          className="df-shell-search-trigger"
          aria-haspopup="dialog"
          aria-label={`${labels.search} (${labels.searchShortcut})`}
          onClick={() => setPaletteOpen(true)}
        >
          <Search size={16} aria-hidden="true" />
          {viewport === "mobile" ? null : <span>{labels.search}</span>}
          {viewport === "mobile" ? null : <kbd aria-hidden="true">{labels.searchShortcut}</kbd>}
        </button>

        <div className="df-shell-header-end">
          <NotificationsMenu
            labels={labels.notifications}
            load={notifications.load}
            unreadCount={notifications.unreadCount}
            markRead={notifications.markRead}
            markAllRead={notifications.markAllRead}
            onOpenItem={notifications.onOpenItem}
          />
          <ThemeToggle />
          <ProfileMenu
            labels={labels.profile}
            name={user.name}
            email={user.email}
            initials={user.initials}
            signingOut={signingOut}
            onOpenSettings={onOpenSettings}
            onSignOut={onSignOut}
          />
        </div>
      </header>

      {viewport !== "mobile" ? (
        <aside id="df-shell-sidebar" className="df-shell-sidebar" aria-label={labels.navigationTitle}>
          <div className="df-shell-sidebar-tools">
            {viewport === "desktop" ? (
              <button
                type="button"
                className="df-shell-icon-button"
                aria-expanded={!sidebarCollapsed}
                aria-controls="df-shell-sidebar"
                aria-label={sidebarCollapsed ? labels.expandSidebar : labels.collapseSidebar}
                onClick={() => onSidebarCollapsedChange(!sidebarCollapsed)}
              >
                {sidebarCollapsed ? (
                  <PanelLeftOpen size={18} aria-hidden="true" />
                ) : (
                  <PanelLeftClose size={18} aria-hidden="true" />
                )}
              </button>
            ) : null}
          </div>
          {sidebarNav}
        </aside>
      ) : null}

      {viewport === "mobile" ? (
        <Dialog
          open={drawerOpen}
          onClose={() => setDrawerPath(null)}
          title={labels.navigationTitle}
          closeLabel={labels.closeNavigation}
          placement="end"
        >
          <div id="df-shell-drawer">{sidebarNav}</div>
        </Dialog>
      ) : null}

      <div className="df-shell-content">
        <div className="df-shell-page-bar">
          <Breadcrumbs label={labels.breadcrumbs} items={breadcrumbs} />
        </div>
        <main id="df-shell-main" tabIndex={-1} className="df-shell-main">
          {children}
        </main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={visibleCommands}
        labels={labels.palette}
      />
    </div>
  );
}

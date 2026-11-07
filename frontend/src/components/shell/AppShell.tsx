import { Menu as MenuIcon, PanelLeftClose, PanelLeftOpen, Search } from "lucide-react";
import "./shell.css";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { SidebarSections } from "../../layouts/workspace/sidebarSections";
import type { WorkspaceModule } from "../../layouts/workspace/workspaceSpaces";
import { Dialog } from "../ui";
import { CommandPalette, type CommandPaletteLabels } from "./CommandPalette";
import { SidebarNav } from "./Navigation";
import { NotificationsMenu, type NotificationEntry, type NotificationsMenuLabels } from "./NotificationsMenu";
import { OrganizationSwitcher, ProfileMenu, type OrganizationSwitcherLabels, type OrganizationOption, type ProfileMenuLabels } from "./HeaderMenus";
import { filterVisibleModules, type CanAccess, type ShellCommand } from "./shellModel";
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
  showSidebar: string;
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
  /** Module sidebar data (legacy layout). Ignored when `renderSidebar` is provided. */
  sections?: SidebarSections;
  /** Custom sidebar. Receives whether the rail (icons only) is showing. */
  renderSidebar?: (railMode: boolean) => ReactNode;
  /** Extra header controls, placed before notifications. */
  headerActions?: ReactNode;
  /** Content shown above the page, below the breadcrumbs (for example a space's secondary navigation). */
  contentHeader?: ReactNode;
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
  /** Sidebar removed from the screen (distinct from collapsed). Restored from the header. */
  sidebarHidden?: boolean;
  onSidebarHiddenChange?: (hidden: boolean) => void;
  /** Expanded sidebar width in pixels. Resizable by pointer or keyboard on desktop. */
  sidebarWidth?: number;
  onSidebarWidthChange?: (width: number) => void;
  onSidebarWidthReset?: () => void;
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
/**
 * Resize handle on the sidebar's right edge. Pointer drag (mouse, pen, touch and trackpad) previews the width and commits on
 * release; ArrowLeft and ArrowRight adjust by 8px (Shift for 32px); Home resets to the default width.
 */
function SidebarResizeHandle({
  width,
  onPreview,
  onCommit,
  onReset,
}: {
  width: number;
  onPreview: (width: number) => void;
  onCommit: (width: number) => void;
  onReset: () => void;
}) {
  const min = 176;
  const max = 320;
  const clamp = (value: number) => Math.min(max, Math.max(min, Math.round(value)));

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = width;
    const target = event.currentTarget;
    target.setPointerCapture(event.pointerId);
    document.body.style.userSelect = "none";
    let latest = startWidth;
    const move = (moveEvent: PointerEvent) => {
      latest = clamp(startWidth + (moveEvent.clientX - startX));
      onPreview(latest);
    };
    const up = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", up);
      target.removeEventListener("pointercancel", up);
      document.body.style.userSelect = "";
      onCommit(latest);
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", up);
    target.addEventListener("pointercancel", up);
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? 32 : 8;
    if (event.key === "ArrowLeft") onCommit(clamp(width - step));
    else if (event.key === "ArrowRight") onCommit(clamp(width + step));
    else if (event.key === "Home") onReset();
    else return;
    event.preventDefault();
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar. Use arrow keys, or Home to reset."
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={width}
      tabIndex={0}
      className="df-shell-resize"
      onPointerDown={onPointerDown}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
    />
  );
}

export function AppShell({
  labels,
  pathname,
  sections,
  renderSidebar,
  headerActions,
  contentHeader,
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
  sidebarHidden = false,
  onSidebarHiddenChange,
  sidebarWidth = 208,
  onSidebarWidthChange,
  onSidebarWidthReset,
  onToggleSpace,
  children,
}: AppShellProps) {
  const viewport = useViewport();
  const mainRef = useRef<HTMLElement | null>(null);
  // A new page starts at the top, so the reader does not inherit the previous page's scroll position.
  useEffect(() => {
    const main = mainRef.current;
    if (main) main.scrollTop = 0;
  }, [pathname]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // The drawer belongs to the route it was opened on and to the mobile band, so navigating or resizing closes it.
  const [drawerPath, setDrawerPath] = useState<string | null>(null);
  const drawerOpen = viewport === "mobile" && drawerPath === pathname;

  // Permission filtering happens once, here, so every surface shows the same visible set.
  const visibleSections = useMemo<SidebarSections | undefined>(() => {
    if (!sections) return undefined;
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
  const desktopHidden = sidebarHidden && viewport !== "mobile";
  const resizable = viewport === "desktop" && !sidebarCollapsed && !sidebarHidden;
  const [dragWidth, setDragWidth] = useState<number | null>(null);
  const shownWidth = dragWidth ?? sidebarWidth;
  const sidebarColumn =
    viewport === "mobile" || desktopHidden ? "0px" : railMode ? "64px" : `${shownWidth}px`;
  const sidebarNav = renderSidebar ? (
    renderSidebar(viewport === "mobile" ? false : railMode)
  ) : visibleSections ? (
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
  ) : null;

  return (
    <div
      className={`df-shell${railMode && viewport !== "mobile" && !desktopHidden ? " df-shell--rail" : ""}${
        desktopHidden ? " df-shell--hidden" : ""
      }${dragWidth !== null ? " df-shell--dragging" : ""}`}
      style={{ "--df-shell-sidebar-current": sidebarColumn } as CSSProperties}
    >
      <a className="df-shell-skip" href="#df-shell-main">
        {labels.skipToContent}
      </a>

      <header className="df-shell-header">
        <div className="df-shell-header-start">
          {viewport !== "mobile" && desktopHidden ? (
            <button
              type="button"
              className="df-shell-icon-button"
              aria-label={labels.showSidebar}
              aria-expanded={false}
              onClick={() => onSidebarHiddenChange?.(false)}
            >
              <PanelLeftOpen size={18} aria-hidden="true" />
            </button>
          ) : viewport === "mobile" ? (
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
          ) : (
            <button
              type="button"
              className="df-shell-icon-button"
              aria-expanded={true}
              aria-controls="df-shell-sidebar"
              aria-label={labels.collapseSidebar}
              title={labels.collapseSidebar}
              onClick={() => onSidebarHiddenChange?.(true)}
            >
              <PanelLeftClose size={18} aria-hidden="true" />
            </button>
          )}

          <div className="df-shell-brand">
            <span className="df-shell-brand-mark" aria-hidden="true">D</span>
            <span className="df-shell-brand-name">{labels.productName}</span>
          </div>

          <OrganizationSwitcher
            labels={labels.organization}
            organizations={organizations}
            selectedId={selectedOrganizationId}
            status={organizationStatus}
            onSelect={onSelectOrganization}
            onRetry={onRetryOrganizations}
          />
        </div>

        <button
          type="button"
          className="df-shell-search-trigger"
          aria-haspopup="dialog"
          aria-label={`${labels.search} (${labels.searchShortcut})`}
          onClick={() => setPaletteOpen(true)}
        >
          <Search size={16} aria-hidden="true" />
          <span className="df-shell-search-text">{labels.search}</span>
          <kbd aria-hidden="true">{labels.searchShortcut}</kbd>
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
          {headerActions}
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

      {viewport !== "mobile" && !desktopHidden ? (
        <aside id="df-shell-sidebar" className="df-shell-sidebar" aria-label={labels.navigationTitle}>
          {sidebarNav}
          {resizable ? (
            <SidebarResizeHandle
              width={shownWidth}
              onPreview={setDragWidth}
              onCommit={(width) => {
                setDragWidth(null);
                onSidebarWidthChange?.(width);
              }}
              onReset={() => onSidebarWidthReset?.()}
            />
          ) : null}
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
        {contentHeader}
        <main ref={mainRef} id="df-shell-main" tabIndex={-1} className="df-shell-main">
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

import { useCallback, useMemo, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { AppShell } from "../../components/shell/AppShell";
import { getNotificationResourceRoute } from "../../components/notificationRoutes";
import { Button } from "../../components/ui";
import type { ShellCommand } from "../../components/shell/shellModel";
import { useAppContext } from "../../contexts/useAppContext";
import { notificationApi } from "../../services/notificationApi";
import "./spaces/spaces.css";
import { SidebarCustomizer } from "./spaces/SidebarCustomizer";
import { SettingsMenu } from "./spaces/SettingsMenu";
import { SpaceFrame } from "./spaces/SpaceFrame";
import { WorkspaceSidebar } from "./spaces/WorkspaceSidebar";
import { UNLISTED_ROUTES, listSpaceRoutes } from "./spaces/spaceConfig";
import { arrangeSpaces, resetSidebarWidth, setSidebarWidth } from "./spaces/spacePreferences";
import { useSpacePreferences } from "./spaces/useSpacePreferences";
import {
  DEFAULT_WORKSPACE_PREFERENCES,
  loadWorkspacePreferences,
  saveWorkspacePreferences,
  type TableDensity,
  type WorkspacePreferences,
} from "./workspacePreferences";
import { WORKSPACE_SHELL_LABELS } from "./workspaceShellLabels";
import { GLOBAL_MODULES, WORKSPACE_MODULES, WORKSPACE_MODULE_LABELS } from "./workspaceSpaces";
import { initialsFor, toNotificationEntry } from "./workspaceShellData";

const ALL_MODULES = (() => {
  const seen = new Map<string, (typeof WORKSPACE_MODULES)[number]>();
  for (const module of [...GLOBAL_MODULES, ...WORKSPACE_MODULES]) {
    if (!seen.has(module.label)) seen.set(module.label, module);
  }
  return [...seen.values()];
})();

const MODULE_LABELS = [...WORKSPACE_MODULE_LABELS];

/**
 * Connects the redesigned shell to the production session. Identity, organizations, sign-out and notifications come from
 * the same sources as before. The sidebar layout is personal (see useSpacePreferences). Table density, which the grids
 * read, is kept in the existing workspace preference store and is scoped the same way.
 *
 * Permissions: no per-user permission list exists in the session, so no space or module is hidden for permissions here.
 * Route guards still enforce access.
 */
export default function WorkspaceShellBridge() {
  const { user, organizations, selectedOrganization, selectOrganization, status, refreshOrganizations, signOut } =
    useAppContext();
  const location = useLocation();
  const navigate = useNavigate();

  const organizationId = selectedOrganization?.id ?? "";
  const userKey = String(user?.id ?? user?.email ?? "");

  const spaces = useSpacePreferences(user?.id ?? null, selectedOrganization?.id ?? null);
  const layout = spaces.preferences;

  // Table density lives in the existing workspace preference store; it is loaded and saved per user and organization.
  const [legacyStore, setLegacyStore] = useState<{ key: string; value: WorkspacePreferences } | null>(null);
  const legacyKey = userKey && organizationId ? `${organizationId}::${userKey}` : "";
  const legacy = useMemo<WorkspacePreferences>(() => {
    if (legacyStore && legacyStore.key === legacyKey) return legacyStore.value;
    if (!legacyKey) return { ...DEFAULT_WORKSPACE_PREFERENCES, navigationOrder: [...MODULE_LABELS] };
    return loadWorkspacePreferences(organizationId, userKey, MODULE_LABELS);
  }, [legacyStore, legacyKey, organizationId, userKey]);

  const setTableDensity = useCallback(
    (density: TableDensity) => {
      const next = { ...legacy, tableDensity: density };
      setLegacyStore({ key: legacyKey, value: next });
      if (legacyKey) saveWorkspacePreferences(organizationId, userKey, next);
    },
    [legacy, legacyKey, organizationId, userKey],
  );

  const [customizerOpen, setCustomizerOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  const visibleSpaces = useMemo(() => arrangeSpaces(layout), [layout]);

  const commands = useMemo<ShellCommand[]>(
    () => [
      ...listSpaceRoutes().map((route) => ({
        id: `nav-${route.id}`,
        label: `Open ${route.label}`,
        group: route.space,
        keywords: route.to,
        run: () => navigate(route.to),
      })),
      ...UNLISTED_ROUTES.map((route) => ({
        id: `nav-${route.to}`,
        label: `Open ${route.label}`,
        group: route.group,
        keywords: route.to,
        run: () => navigate(route.to),
      })),
      {
        id: "customise-sidebar",
        label: "Customize sidebar",
        group: "Preferences",
        keywords: "spaces order pin hide sidebar",
        run: () => setCustomizerOpen(true),
      },
      {
        id: "toggle-sidebar",
        label: layout.collapsed ? "Expand sidebar" : "Collapse sidebar",
        group: "Preferences",
        keywords: "icons rail",
        run: () => spaces.update({ ...layout, collapsed: !layout.collapsed }),
      },
    ],
    [navigate, layout, spaces],
  );

  const notifications = useMemo(
    () => ({
      load: async () => (await notificationApi.list(10)).items.map(toNotificationEntry),
      unreadCount: async () => (await notificationApi.unreadCount()).unread_count,
      markRead: async (id: string) => {
        await notificationApi.markRead(id);
      },
      markAllRead: async () => {
        await notificationApi.markAllRead();
      },
      onOpenItem: (entry: { resourceType?: string | null }) => {
        const route = getNotificationResourceRoute(entry.resourceType ?? null);
        if (route) navigate(route);
      },
    }),
    [navigate],
  );

  async function handleSignOut() {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await signOut();
    } finally {
      setSigningOut(false);
    }
  }

  const organizationStatus = status === "loading" ? "loading" : status === "error" ? "error" : "ready";

  return (
    <>
      <AppShell
        labels={WORKSPACE_SHELL_LABELS}
        pathname={location.pathname}
        modules={ALL_MODULES}
        renderSidebar={(rail) => (
          <>
            <div className="df-ws-sidebar-body">
              <WorkspaceSidebar
                spaces={visibleSpaces}
                pathname={location.pathname}
                rail={rail}
                density={layout.density}
                label="Workspace spaces"
                heading="Spaces"
              />
            </div>
            <div className="df-ws-sidebar-footer">
              <Button
                variant="secondary"
                size="sm"
                iconOnly={rail}
                aria-label="Customize sidebar"
                icon={<SlidersHorizontal size={16} strokeWidth={1.8} aria-hidden="true" />}
                onClick={() => setCustomizerOpen(true)}
              >
                Customize sidebar
              </Button>
            </div>
          </>
        )}
        headerActions={<SettingsMenu />}
        canAccess={() => true}
        commands={commands}
        user={{
          name: user?.display_name ?? user?.email ?? "",
          email: user?.email ?? "",
          initials: initialsFor(user?.display_name, user?.email),
        }}
        signingOut={signingOut}
        onSignOut={() => void handleSignOut()}
        onOpenSettings={() => navigate("/notification-preferences")}
        organizations={organizations.map((organization) => ({ id: organization.id, name: organization.name }))}
        selectedOrganizationId={selectedOrganization?.id ?? null}
        organizationStatus={organizationStatus}
        onSelectOrganization={(id) => {
          if (id !== selectedOrganization?.id) selectOrganization(id);
        }}
        onRetryOrganizations={() => void refreshOrganizations()}
        notifications={notifications}
        sidebarCollapsed={layout.collapsed}
        sidebarHidden={layout.sidebarHidden}
        onSidebarHiddenChange={(hidden) => spaces.update({ ...layout, sidebarHidden: hidden })}
        sidebarWidth={layout.sidebarWidth}
        onSidebarWidthChange={(width) => spaces.update(setSidebarWidth(layout, width))}
        onSidebarWidthReset={() => spaces.update(resetSidebarWidth(layout))}
        onToggleSpace={() => undefined}
      >
        <SpaceFrame navigationSuffix="sections">
          <Outlet />
        </SpaceFrame>
      </AppShell>

      <SidebarCustomizer
        open={customizerOpen}
        onClose={() => setCustomizerOpen(false)}
        preferences={layout}
        onChange={spaces.update}
        onRestoreDefaults={spaces.restoreDefaults}
        tableDensity={legacy.tableDensity}
        onTableDensityChange={setTableDensity}
      />
    </>
  );
}

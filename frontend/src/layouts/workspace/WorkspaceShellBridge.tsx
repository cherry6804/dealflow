import { useCallback, useMemo, useState } from "react";
import { useLocation, useNavigate, Outlet } from "react-router-dom";

import { AppShell } from "../../components/shell/AppShell";
import { getNotificationResourceRoute } from "../../components/notificationRoutes";
import type { ShellCommand } from "../../components/shell/shellModel";
import { useAppContext } from "../../contexts/useAppContext";
import { notificationApi } from "../../services/notificationApi";
import WorkspaceCustomizer from "./WorkspaceCustomizer";
import { WORKSPACE_SHELL_LABELS } from "./workspaceShellLabels";
import { buildSidebarSections } from "./sidebarSections";
import {
  DEFAULT_WORKSPACE_PREFERENCES,
  loadWorkspacePreferences,
  resetWorkspacePreferences,
  saveWorkspacePreferences,
  type WorkspacePreferences,
} from "./workspacePreferences";
import { GLOBAL_MODULES, WORKSPACE_MODULES, WORKSPACE_MODULE_LABELS } from "./workspaceSpaces";
import { getPreferenceKey, initialsFor, toNotificationEntry } from "./workspaceShellData";

const MODULE_LABELS = [...WORKSPACE_MODULE_LABELS];
const ALL_MODULES = (() => {
  const seen = new Map<string, (typeof WORKSPACE_MODULES)[number]>();
  for (const module of [...GLOBAL_MODULES, ...WORKSPACE_MODULES]) {
    if (!seen.has(module.label)) seen.set(module.label, module);
  }
  return [...seen.values()];
})();

/**
 * Connects the redesigned shell to the production session. It reads the same sources as the existing layout:
 * AppContext for the user, organizations and sign-out; the stored workspace preferences for each organization and user;
 * and notificationApi for notifications. Nothing is replaced with fixtures.
 *
 * Permissions: AppContext carries no per-user permission list, so no module is hidden here. Route guards still enforce
 * access. Entitlement and permission states remain the responsibility of the individual routes.
 */
export default function WorkspaceShellBridge() {
  const { user, organizations, selectedOrganization, selectOrganization, status, refreshOrganizations, signOut } =
    useAppContext();
  const location = useLocation();
  const navigate = useNavigate();

  const organizationId = selectedOrganization?.id ?? "";
  const userKey = String(user?.id ?? user?.email ?? "");
  const preferenceKey = userKey && organizationId ? getPreferenceKey(organizationId, userKey) : "";

  // Preferences are read from storage when the organization or user changes, and held in state after that.
  const [stored, setStored] = useState<{ key: string; preferences: WorkspacePreferences } | null>(null);
  const preferences = useMemo<WorkspacePreferences>(() => {
    if (stored && stored.key === preferenceKey) return stored.preferences;
    if (!preferenceKey) return { ...DEFAULT_WORKSPACE_PREFERENCES, navigationOrder: [...MODULE_LABELS] };
    return loadWorkspacePreferences(organizationId, userKey, MODULE_LABELS);
  }, [stored, preferenceKey, organizationId, userKey]);

  const updatePreferences = useCallback(
    (next: WorkspacePreferences) => {
      setStored({ key: preferenceKey, preferences: next });
      if (preferenceKey) saveWorkspacePreferences(organizationId, userKey, next);
    },
    [preferenceKey, organizationId, userKey],
  );

  const [customizerOpen, setCustomizerOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  const sections = useMemo(() => buildSidebarSections(preferences), [preferences]);

  const commands = useMemo<ShellCommand[]>(
    () => [
      ...ALL_MODULES.map((module) => ({
        id: `nav-${module.label}`,
        label: `Open ${module.label}`,
        group: "Navigate",
        keywords: module.to,
        run: () => navigate(module.to),
      })),
      {
        id: "customise-navigation",
        label: "Customise navigation",
        group: "Preferences",
        keywords: "sidebar order hide pin",
        run: () => setCustomizerOpen(true),
      },
      {
        id: "toggle-sidebar",
        label: preferences.sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar",
        group: "Preferences",
        keywords: "rail",
        run: () => updatePreferences({ ...preferences, sidebarCollapsed: !preferences.sidebarCollapsed }),
      },
    ],
    [navigate, preferences, updatePreferences],
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
        sections={sections}
        canAccess={() => true}
        commands={commands}
        user={{
          name: user?.display_name ?? user?.email ?? "",
          email: user?.email ?? "",
          initials: initialsFor(user?.display_name, user?.email),
        }}
        signingOut={signingOut}
        onSignOut={() => void handleSignOut()}
        onOpenSettings={() => navigate("/settings")}
        organizations={organizations.map((organization) => ({ id: organization.id, name: organization.name }))}
        selectedOrganizationId={selectedOrganization?.id ?? null}
        organizationStatus={organizationStatus}
        onSelectOrganization={(id) => {
          if (id !== selectedOrganization?.id) selectOrganization(id);
        }}
        onRetryOrganizations={() => void refreshOrganizations()}
        notifications={notifications}
        sidebarCollapsed={preferences.sidebarCollapsed}
        onSidebarCollapsedChange={(collapsed) => updatePreferences({ ...preferences, sidebarCollapsed: collapsed })}
        onToggleSpace={(spaceId) => {
          const collapsed = new Set(preferences.collapsedSpaces);
          if (collapsed.has(spaceId)) collapsed.delete(spaceId);
          else collapsed.add(spaceId);
          updatePreferences({ ...preferences, collapsedSpaces: [...collapsed] });
        }}
      >
        <Outlet />
      </AppShell>

      <WorkspaceCustomizer
        open={customizerOpen}
        preferences={preferences}
        availableModules={MODULE_LABELS}
        onClose={() => setCustomizerOpen(false)}
        onChange={updatePreferences}
        onReset={() => {
          if (userKey && organizationId) resetWorkspacePreferences(organizationId, userKey);
          setStored({
            key: preferenceKey,
            preferences: { ...DEFAULT_WORKSPACE_PREFERENCES, navigationOrder: [...MODULE_LABELS] },
          });
        }}
      />
    </>
  );
}

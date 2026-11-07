import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Routes, Route, useLocation, useNavigate } from "react-router-dom";

import { GLOBAL_MODULES, WORKSPACE_MODULES } from "../../layouts/workspace/workspaceSpaces";
import { SidebarCustomizer } from "../../layouts/workspace/spaces/SidebarCustomizer";
import { SettingsMenu } from "../../layouts/workspace/spaces/SettingsMenu";
import { SpaceFrame } from "../../layouts/workspace/spaces/SpaceFrame";
import { WorkspaceSidebar } from "../../layouts/workspace/spaces/WorkspaceSidebar";
import { listSpaceRoutes, UNLISTED_ROUTES } from "../../layouts/workspace/spaces/spaceConfig";
import {
  DEFAULT_SPACE_PREFERENCES,
  arrangeSpaces,
  setCollapsed,
  type SpacePreferences,
} from "../../layouts/workspace/spaces/spacePreferences";
import {
  AppShell,
  EmptyState,
  ErrorState,
  LoadingState,
  PageHeader,
  PermissionDeniedState,
  type AppShellLabels,
  type NotificationEntry,
  type ShellCommand,
} from "../../components/shell";
import { Button } from "../../components/ui";

/**
 * Development-only shell preview, mounted at /design-system/shell. It exercises the real shell components with fixture
 * data only. Nothing here calls the backend, and no authentication is bypassed: production routes keep their own guards.
 *
 * Fixture behaviour, labelled so it is not mistaken for product behaviour:
 * - Organizations are fixtures; switching changes only this preview's state.
 * - The first notification load fails once so the error and retry path can be seen.
 * - "Restricted" is gated by a fixture permission the preview does not grant.
 */

const BASE = "/design-system/shell";

const PREVIEW_PERMISSION_BY_MODULE: Readonly<Record<string, string>> = {
  Commissions: "preview:commissions",
};

const LABELS: AppShellLabels = {
  productName: "Dealsflo",
  skipToContent: "Skip to content",
  mainNavigation: "Main navigation",
  navigationTitle: "Navigation",
  openNavigation: "Open navigation",
  closeNavigation: "Close navigation",
  collapseSidebar: "Collapse sidebar",
  expandSidebar: "Expand sidebar",
  showSidebar: "Show sidebar",
  search: "Search",
  searchShortcut: "Ctrl K",
  homeBreadcrumb: "Overview",
  breadcrumbs: "Breadcrumbs",
  pinnedGroup: "Pinned",
  globalGroup: "Workspace",
  closeLabel: "Close",
  palette: {
    title: "Search and commands",
    description: "Find a module or run a command. Record search is not available in this preview.",
    closeLabel: "Close search",
    placeholder: "Search modules and commands",
    listLabel: "Results",
    empty: "No matches",
  },
  organization: {
    trigger: "Organization",
    listLabel: "Organizations",
    current: "Current",
    loading: "Loading organizations",
    error: "Organizations could not be loaded",
    retry: "Try again",
    empty: "No organizations",
  },
  notifications: {
    trigger: "Notifications",
    panelTitle: "Notifications",
    unreadLabel: "Unread",
    unreadCountLabel: (count) => `${count} unread`,
    markRead: "Mark as read",
    markAllRead: "Mark all as read",
    loading: "Loading notifications",
    loadingMessage: "Fetching your latest updates.",
    emptyTitle: "You are all caught up",
    emptyMessage: "New notifications appear here.",
    errorTitle: "Notifications could not be loaded",
    errorMessage: "Check your connection and try again.",
    retry: "Try again",
  },
  profile: { trigger: "Account", settings: "Settings", signOut: "Sign out", signingOut: "Signing out" },
};

const FIXTURE_ORGANIZATIONS = [
  { id: "org-acme", name: "Acme Realty" },
  { id: "org-northwind", name: "Northwind Capital" },
];

const FIXTURE_NOTIFICATIONS: NotificationEntry[] = [
  { id: "n1", title: "Deal won", message: "Meridian Tower HQ lease closed", createdAt: "Today, 09:00", read: false },
  { id: "n2", title: "Visit booked", message: "Site visit tomorrow at 10:00", createdAt: "Today, 08:20", read: false },
  { id: "n3", title: "Follow-up due", message: "Call Elena Ruiz before 17:00", createdAt: "Yesterday", read: true },
];

let notificationCalls = 0;

/** Fixture loader: fails on the first call so the error and retry states can be checked. */
function loadFixtureNotifications(): Promise<NotificationEntry[]> {
  notificationCalls += 1;
  return new Promise((resolve, reject) => {
    window.setTimeout(() => {
      if (notificationCalls === 1) reject(new Error("fixture failure"));
      else resolve(FIXTURE_NOTIFICATIONS.map((entry) => ({ ...entry })));
    }, 500);
  });
}

function PreviewPage({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <>
      <PageHeader
        title={title}
        description={description}
        actions={
          <>
            <Button variant="secondary">Export</Button>
            <Button variant="primary">Add record</Button>
          </>
        }
      />
      {children}
    </>
  );
}

function PreviewRoutes() {
  const [leadsStatus, setLeadsStatus] = useState<"error" | "loading" | "ready">("error");

  function retryLeads() {
    setLeadsStatus("loading");
    window.setTimeout(() => setLeadsStatus("ready"), 500);
  }

  return (
    <Routes>
      <Route
        index
        element={
          <PreviewPage title="Good morning" description="Overview fixture. Shell interactions are the focus here.">
            <LoadingState title="Loading your overview" message="Fixture state: content would appear here." />
          </PreviewPage>
        }
      />
      <Route
        path="deals"
        element={
          <PreviewPage title="Deals" description="0 records · fixture">
            <EmptyState title="Your pipeline starts here" message="Add your first deal, or import your existing pipeline." />
          </PreviewPage>
        }
      />
      <Route
        path="leads"
        element={
          <PreviewPage title="Leads" description="Fixture error and retry">
            {leadsStatus === "error" ? (
              <ErrorState
                title="Leads could not be loaded"
                message="Your view and filters are safe. Check your connection and try again."
                retryLabel="Retry"
                onRetry={retryLeads}
              />
            ) : null}
            {leadsStatus === "loading" ? <LoadingState title="Loading leads" message="Fixture retry in progress." /> : null}
            {leadsStatus === "ready" ? <EmptyState title="No leads yet" message="Fixture: the retry succeeded." /> : null}
          </PreviewPage>
        }
      />
      <Route
        path="commissions"
        element={
          <PreviewPage title="Commissions" description="Gated by a fixture permission">
            <PermissionDeniedState
              title="Admin access required"
              message="Only workspace admins can open reports. Ask an admin to grant access."
            />
          </PreviewPage>
        }
      />
      <Route
        path="*"
        element={
          <PreviewPage title="Not found" description="The preview has no page at this address.">
            <EmptyState title="Page not found" message="Choose a module in the sidebar or press Ctrl K." />
          </PreviewPage>
        }
      />
    </Routes>
  );
}

export default function ShellPreview() {
  const location = useLocation();
  const route = location.pathname.startsWith(BASE) ? location.pathname.slice(BASE.length) || "/" : "/";
  const [organizationId, setOrganizationId] = useState(FIXTURE_ORGANIZATIONS[0].id);
  const [organizationStatus] = useState<"ready" | "loading" | "error">("ready");
  const [layout, setLayout] = useState<SpacePreferences>(DEFAULT_SPACE_PREFERENCES);
  const [customizerOpen, setCustomizerOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const navigate = useNavigate();

  // Workspace and global lists overlap (Overview, Notifications, Billing, Settings). Keep one entry per label.
  const modules = useMemo(() => {
    const byLabel = new Map<string, (typeof GLOBAL_MODULES)[number]>();
    for (const module of [...GLOBAL_MODULES, ...WORKSPACE_MODULES]) {
      if (!byLabel.has(module.label)) byLabel.set(module.label, module);
    }
    return [...byLabel.values()];
  }, []);
  const canAccess = useCallback((permission: string) => permission !== "preview:commissions", []);

  const commands = useMemo<ShellCommand[]>(
    () => [
      ...listSpaceRoutes().map((route) => ({
        id: `nav-${route.id}`,
        label: `Open ${route.label}`,
        group: route.space,
        keywords: route.to,
        run: () => navigate(`${BASE}${route.to}`),
      })),
      ...UNLISTED_ROUTES.map((route) => ({
        id: `nav-${route.to}`,
        label: `Open ${route.label}`,
        group: route.group,
        keywords: route.to,
        run: () => navigate(`${BASE}${route.to}`),
      })),
      {
        id: "customise-sidebar",
        label: "Customize sidebar",
        group: "Preferences",
        keywords: "spaces order pin hide",
        run: () => setCustomizerOpen(true),
      },
      {
        id: "toggle-sidebar",
        label: layout.collapsed ? "Expand sidebar" : "Collapse sidebar",
        group: "Preferences",
        keywords: "icons rail",
        run: () => setLayout((current) => setCollapsed(current, !current.collapsed)),
      },
    ],
    [navigate, layout.collapsed, setCustomizerOpen, setLayout],
  );

  const notifications = useMemo(
    () => ({
      load: loadFixtureNotifications,
      unreadCount: async () => FIXTURE_NOTIFICATIONS.filter((entry) => !entry.read).length,
      markRead: async () => undefined,
      markAllRead: async () => undefined,
    }),
    [],
  );

  return (
    <>
    <AppShell
      labels={LABELS}
      pathname={route}
      basePath={BASE}
      modules={modules}
      renderSidebar={(rail) => (
        <>
          <div className="df-ws-sidebar-body">
            <WorkspaceSidebar
              spaces={arrangeSpaces(layout)}
              pathname={route}
              rail={rail}
              density={layout.density}
              label="Workspace spaces"
              heading="Spaces"
              basePath={BASE}
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
      canAccess={canAccess}
      permissionByModule={PREVIEW_PERMISSION_BY_MODULE}
      commands={commands}
      user={{ name: "Elena Ruiz", email: "elena@example.com", initials: "ER" }}
      signingOut={signingOut}
      onSignOut={() => {
        setSigningOut(true);
        window.setTimeout(() => setSigningOut(false), 600);
      }}
      onOpenSettings={() => undefined}
      organizations={FIXTURE_ORGANIZATIONS}
      selectedOrganizationId={organizationId}
      organizationStatus={organizationStatus}
      onSelectOrganization={setOrganizationId}
      onRetryOrganizations={() => undefined}
      notifications={notifications}
      sidebarCollapsed={layout.collapsed}
      onToggleSpace={() => undefined}
      contentHeader={undefined}
    >
      <SpaceFrame navigationSuffix="sections" basePath={BASE}>
        <PreviewRoutes />
      </SpaceFrame>
    </AppShell>
    <SidebarCustomizer
      open={customizerOpen}
      onClose={() => setCustomizerOpen(false)}
      preferences={layout}
      onChange={setLayout}
      onRestoreDefaults={() => setLayout(DEFAULT_SPACE_PREFERENCES)}
      tableDensity="comfortable"
      onTableDensityChange={() => undefined}
    />
    </>
  );
}

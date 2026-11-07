import type { AppShellLabels } from "../../components/shell/AppShell";

/**
 * English shell labels. The existing workspace layout has no translation layer, so these match its wording. Move them
 * into the translation system when one is introduced for the app.
 */
export const WORKSPACE_SHELL_LABELS: AppShellLabels = {
  productName: "Dealsflo",
  skipToContent: "Skip to content",
  mainNavigation: "Main navigation",
  navigationTitle: "Navigation",
  openNavigation: "Open navigation",
  closeNavigation: "Close navigation",
  collapseSidebar: "Collapse sidebar",
  expandSidebar: "Expand sidebar",
  search: "Search",
  searchShortcut: "Ctrl K",
  homeBreadcrumb: "Overview",
  breadcrumbs: "Breadcrumbs",
  pinnedGroup: "Pinned",
  globalGroup: "Workspace",
  closeLabel: "Close",
  palette: {
    title: "Search and commands",
    description: "Find a module or run a command. Record search is not available here yet.",
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

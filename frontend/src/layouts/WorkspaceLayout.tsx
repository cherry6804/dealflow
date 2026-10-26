
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Bell,
  Bot,
  Building2,
  CalendarCheck,
  Check,
  ChevronDown,
  CircleDollarSign,
  ClipboardList,
  ContactRound,
  FileText,
  Handshake,
  LayoutDashboard,
  LogOut,
  MapPin,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  SlidersHorizontal,
  Upload,
  UserRound,
  Users,
  Workflow,
  BriefcaseBusiness,
  BellRing,
  X,
} from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAppContext } from "../contexts/useAppContext";
import "../styles/workspace-layout-responsive.css";
import WorkspaceCustomizer from "./workspace/WorkspaceCustomizer";
import {
  DEFAULT_WORKSPACE_PREFERENCES,
  loadWorkspacePreferences,
  resetWorkspacePreferences,
  saveWorkspacePreferences,
  type WorkspacePreferences,
} from "./workspace/workspacePreferences";

const navigation = [
  { label: "Overview", to: "/", icon: LayoutDashboard },
  { label: "Leads", to: "/leads", icon: Users },
  { label: "Contacts", to: "/contacts", icon: ContactRound },
  { label: "Customers", to: "/customers", icon: UserRound },
  { label: "Requirements", to: "/requirements", icon: ClipboardList },
  { label: "Pipeline", to: "/pipeline", icon: Workflow },
  { label: "Deals", to: "/deals", icon: Handshake },
  { label: "Properties", to: "/properties", icon: Building2 },
  { label: "Referrals", to: "/referrals", icon: BriefcaseBusiness },
  { label: "Site Visits", to: "/site-visits", icon: MapPin },
  { label: "Follow-ups", to: "/follow-ups", icon: CalendarCheck },
  { label: "Commissions", to: "/commissions", icon: CircleDollarSign },
  { label: "Documents", to: "/documents", icon: FileText },
  { label: "Imports", to: "/imports", icon: Upload },
  { label: "Automation Rules", to: "/automation-rules", icon: Bot },
  { label: "Activity", to: "/automation-history", icon: Activity },
  {
    label: "Notifications",
    to: "/notification-preferences",
    icon: BellRing,
  },
  { label: "Settings", to: "/settings", icon: Settings },
] as const;

const moduleNames = navigation.map((item) => item.label);

function getOrderedNavigation(order: string[]) {
  const rank = new Map(order.map((label, index) => [label, index]));

  return [...navigation].sort((a, b) => {
    const aRank = rank.get(a.label) ?? Number.MAX_SAFE_INTEGER;
    const bRank = rank.get(b.label) ?? Number.MAX_SAFE_INTEGER;

    return aRank - bRank;
  });
}

function getInitials(name?: string | null, email?: string | null) {
  const value = name?.trim() || email?.trim() || "U";
  return value.charAt(0).toUpperCase();
}

function getPreferenceKey(organizationId: string, userId: string) {
  return `${organizationId}::${userId}`;
}

export default function WorkspaceLayout() {
  const {
    user,
    organizations,
    selectedOrganization,
    selectOrganization,
    signOut,
  } = useAppContext();

  const location = useLocation();
  const navigate = useNavigate();

  const userKey = String(user?.id ?? user?.email ?? "");
  const organizationKey = String(selectedOrganization?.id ?? "");

  const preferenceKey =
    userKey && organizationKey
      ? getPreferenceKey(organizationKey, userKey)
      : "";

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [organizationMenuOpen, setOrganizationMenuOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [customizerOpen, setCustomizerOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [searchValue, setSearchValue] = useState("");

  const [preferences, setPreferences] = useState<WorkspacePreferences>({
    ...DEFAULT_WORKSPACE_PREFERENCES,
  });

  const [loadedPreferenceKey, setLoadedPreferenceKey] = useState("");

  const sidebarOrganizationMenuRef = useRef<HTMLDivElement>(null);
  const topbarOrganizationMenuRef = useRef<HTMLDivElement>(null);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!preferenceKey) {
      setPreferences({
        ...DEFAULT_WORKSPACE_PREFERENCES,
        navigationOrder: [...moduleNames],
      });
      setLoadedPreferenceKey("");
      return;
    }

    setLoadedPreferenceKey("");

    setPreferences(
      loadWorkspacePreferences(organizationKey, userKey, [...moduleNames]),
    );

    setLoadedPreferenceKey(preferenceKey);
  }, [preferenceKey, organizationKey, userKey]);

  useEffect(() => {
    if (!preferenceKey || loadedPreferenceKey !== preferenceKey) {
      return;
    }

    saveWorkspacePreferences(organizationKey, userKey, preferences);
  }, [
    preferences,
    preferenceKey,
    loadedPreferenceKey,
    organizationKey,
    userKey,
  ]);

  useEffect(() => {
    setSidebarOpen(false);
    setAccountOpen(false);
    setOrganizationMenuOpen(false);
    setNotificationOpen(false);
    setSearchValue("");
  }, [location.pathname, organizationKey]);

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }

      setSidebarOpen(false);
      setCustomizerOpen(false);
      setAccountOpen(false);
      setOrganizationMenuOpen(false);
      setNotificationOpen(false);

      if (document.activeElement === searchInputRef.current) {
        setSearchValue("");
        searchInputRef.current?.blur();
      }
    }

    function handleSearchShortcut(event: KeyboardEvent) {
      const target = event.target;

      const isTyping =
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName));

      if (
        event.key === "/" &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey &&
        !isTyping
      ) {
        event.preventDefault();
        searchInputRef.current?.focus();
      }
    }

    window.addEventListener("keydown", handleEscape);
    window.addEventListener("keydown", handleSearchShortcut);

    return () => {
      window.removeEventListener("keydown", handleEscape);
      window.removeEventListener("keydown", handleSearchShortcut);
    };
  }, []);

  useEffect(() => {
    function handleOutsidePointerDown(event: PointerEvent) {
      const target = event.target;

      if (!(target instanceof Node)) {
        return;
      }

      const insideOrganizationMenu =
        sidebarOrganizationMenuRef.current?.contains(target) ||
        topbarOrganizationMenuRef.current?.contains(target);

      if (!insideOrganizationMenu) {
        setOrganizationMenuOpen(false);
      }

      if (!accountMenuRef.current?.contains(target)) {
        setAccountOpen(false);
      }

      if (
        target instanceof Element &&
        !target.closest(".workspace-notification-menu") &&
        !target.closest(".workspace-notification-button")
      ) {
        setNotificationOpen(false);
      }
    }

    document.addEventListener("pointerdown", handleOutsidePointerDown);

    return () => {
      document.removeEventListener("pointerdown", handleOutsidePointerDown);
    };
  }, []);

  const orderedNavigation = useMemo(
    () => getOrderedNavigation(preferences.navigationOrder),
    [preferences.navigationOrder],
  );

  const visibleNavigation = orderedNavigation.filter(
    (item) =>
      !preferences.hiddenModules.includes(item.label) &&
      !preferences.pinnedModules.includes(item.label),
  );

  const pinnedNavigation = orderedNavigation.filter(
    (item) =>
      !preferences.hiddenModules.includes(item.label) &&
      preferences.pinnedModules.includes(item.label),
  );

  const avatar = getInitials(user?.display_name, user?.email);

  function updatePreferences(next: WorkspacePreferences) {
    setPreferences(next);
  }

  function resetPreferences() {
    if (userKey && organizationKey) {
      resetWorkspacePreferences(organizationKey, userKey);
    }

    setPreferences({
      ...DEFAULT_WORKSPACE_PREFERENCES,
      navigationOrder: [...moduleNames],
    });
  }

  function handleOrganizationSelect(organizationId: string) {
    if (!organizationId) {
      return;
    }

    setOrganizationMenuOpen(false);

    if (organizationId !== selectedOrganization?.id) {
      selectOrganization(organizationId);
    }
  }

  function handleSearchSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const query = searchValue.trim();

    if (!query) {
      searchInputRef.current?.focus();
      return;
    }

    // This is navigation assistance, not a backend/global record search.
    // Do not imply that results have been searched across the database.
    const normalizedQuery = query.toLowerCase();

    const match = navigation.find(
      (item) =>
        item.label.toLowerCase() === normalizedQuery ||
        item.label.toLowerCase().includes(normalizedQuery),
    );

    if (match) {
      navigate(match.to);
      setSearchValue("");
      searchInputRef.current?.blur();
      return;
    }

    // Keep the entered text visible so it is not silently discarded.
    // Global record search requires a dedicated search API/workflow.
  }

  async function handleSignOut() {
    if (signingOut) {
      return;
    }

    setSigningOut(true);
    setAccountOpen(false);
    setOrganizationMenuOpen(false);

    try {
      await signOut();
    } finally {
      setSigningOut(false);
    }
  }

  function renderNavigationItem(
    item: (typeof navigation)[number],
  ) {
    const Icon = item.icon;

    return (
      <NavLink
        key={item.to}
        to={item.to}
        end={item.to === "/"}
        onClick={() => setSidebarOpen(false)}
        className={({ isActive }) =>
          `workspace-nav-link${isActive ? " is-active" : ""}`
        }
        title={preferences.sidebarCollapsed ? item.label : undefined}
      >
        <Icon size={18} strokeWidth={1.8} aria-hidden="true" />
        <span>{item.label}</span>
      </NavLink>
    );
  }

  return (
    <div
      className={[
        "workspace-shell",
        preferences.sidebarCollapsed ? "sidebar-is-collapsed" : "",
        preferences.tableDensity === "compact"
          ? "table-density-compact"
          : "table-density-comfortable",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {sidebarOpen && (
        <button
          type="button"
          className="workspace-backdrop"
          aria-label="Close navigation"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={[
          "workspace-sidebar",
          sidebarOpen ? "is-open" : "",
          preferences.sidebarCollapsed ? "is-collapsed" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        aria-label="Workspace sidebar"
      >
        <div className="workspace-brand">
          <span className="workspace-brand-mark" aria-hidden="true">
            D
          </span>

          <span className="workspace-brand-copy">
            <strong>Dealsflo</strong>
            <small>Real estate operations</small>
          </span>

          <button
            type="button"
            className="workspace-icon-button workspace-sidebar-close"
            aria-label="Close navigation"
            onClick={() => setSidebarOpen(false)}
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div className="workspace-org-area">
          <span className="workspace-org-label">WORKSPACE</span>

          <div className="workspace-org-select">
            <Building2 size={17} aria-hidden="true" />

            {organizations.length > 1 ? (
              <div
                className="workspace-org-picker"
                ref={sidebarOrganizationMenuRef}
              >
                <button
                  type="button"
                  className="workspace-org-trigger"
                  aria-label="Select organization"
                  aria-haspopup="listbox"
                  aria-expanded={organizationMenuOpen}
                  title={
                    selectedOrganization?.name ?? "Select organization"
                  }
                  onClick={() => {
                    setOrganizationMenuOpen((open) => !open);
                    setAccountOpen(false);
                    setNotificationOpen(false);
                  }}
                >
                  <span>
                    {selectedOrganization?.name ?? "Select organization"}
                  </span>
                  <ChevronDown size={15} aria-hidden="true" />
                </button>

                {organizationMenuOpen && (
                  <div
                    className="workspace-org-dropdown"
                    role="listbox"
                    aria-label="Organizations"
                  >
                    <div className="workspace-org-dropdown-heading">
                      Switch workspace
                    </div>

                    {organizations.map((organization) => {
                      const selected =
                        organization.id === selectedOrganization?.id;

                      return (
                        <button
                          type="button"
                          role="option"
                          aria-selected={selected}
                          key={organization.id}
                          className={[
                            "workspace-org-option",
                            selected ? "is-selected" : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          onClick={() =>
                            handleOrganizationSelect(organization.id)
                          }
                        >
                          <Building2 size={16} aria-hidden="true" />
                          <span>{organization.name}</span>
                          {selected && (
                            <Check size={16} aria-hidden="true" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : (
              <span
                className="workspace-org-single"
                title={selectedOrganization?.name ?? "Your workspace"}
              >
                {selectedOrganization?.name ?? "Your workspace"}
              </span>
            )}
          </div>
        </div>

        <nav className="workspace-navigation" aria-label="Main navigation">
          {pinnedNavigation.length > 0 && (
            <>
              <span className="workspace-nav-caption">PINNED</span>
              {pinnedNavigation.map(renderNavigationItem)}
            </>
          )}

          <span className="workspace-nav-caption">WORKSPACE</span>
          {visibleNavigation.map(renderNavigationItem)}
        </nav>

        <div className="workspace-sidebar-tools">
          <button
            type="button"
            className="workspace-nav-link"
            onClick={() => setCustomizerOpen(true)}
            title={
              preferences.sidebarCollapsed
                ? "Customize workspace"
                : undefined
            }
          >
            <SlidersHorizontal
              size={18}
              strokeWidth={1.8}
              aria-hidden="true"
            />
            <span>Customize workspace</span>
          </button>

          <button
            type="button"
            className="workspace-nav-link workspace-collapse-button workspace-desktop-collapse-button"
            onClick={() =>
              updatePreferences({
                ...preferences,
                sidebarCollapsed: !preferences.sidebarCollapsed,
              })
            }
            aria-label={
              preferences.sidebarCollapsed
                ? "Expand sidebar"
                : "Collapse sidebar"
            }
            title={
              preferences.sidebarCollapsed
                ? "Expand sidebar"
                : "Collapse sidebar"
            }
          >
            {preferences.sidebarCollapsed ? (
              <PanelLeftOpen size={18} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={18} aria-hidden="true" />
            )}
            <span>
              {preferences.sidebarCollapsed
                ? "Expand sidebar"
                : "Collapse sidebar"}
            </span>
          </button>
        </div>

        <div className="workspace-sidebar-footer">
          <span className="workspace-avatar" aria-hidden="true">
            {avatar}
          </span>

          <span className="workspace-user-copy">
            <strong>{user?.display_name || "Account"}</strong>
            <small>{user?.email}</small>
          </span>

          <button
            type="button"
            className="workspace-icon-button workspace-signout-button"
            aria-label="Sign out"
            title="Sign out"
            disabled={signingOut}
            onClick={() => void handleSignOut()}
          >
            <LogOut size={17} aria-hidden="true" />
          </button>
        </div>
      </aside>

      <div className="workspace-main">
        <header className="workspace-topbar">
          <button
            type="button"
            className="workspace-icon-button workspace-menu-button"
            aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((open) => !open)}
          >
            {sidebarOpen ? (
              <PanelLeftOpen size={20} strokeWidth={1.8} aria-hidden="true" />
            ) : (
              <PanelLeftClose size={20} strokeWidth={1.8} aria-hidden="true" />
            )}
          </button>

          <div className="workspace-topbar-context">
            <span className="workspace-topbar-eyebrow">DEALSFLO</span>
            <span className="workspace-topbar-title">
              {selectedOrganization?.name ?? "Your workspace"}
            </span>
          </div>

          <form
            className="workspace-topbar-search"
            role="search"
            onSubmit={handleSearchSubmit}
          >
            <Search size={17} aria-hidden="true" />

            <input
              ref={searchInputRef}
              type="search"
              aria-label="Find a workspace module"
              placeholder="Find a page..."
              value={searchValue}
              onChange={(event) => setSearchValue(event.target.value)}
            />

            <kbd aria-hidden="true">/</kbd>
          </form>

          <div className="workspace-topbar-actions">
            {organizations.length > 1 && (
              <div
                className="workspace-topbar-organization"
                ref={topbarOrganizationMenuRef}
              >
                <button
                  type="button"
                  className="workspace-icon-button"
                  aria-label="Switch organization"
                  aria-haspopup="listbox"
                  aria-expanded={organizationMenuOpen}
                  title="Switch organization"
                  onClick={() => {
                    setOrganizationMenuOpen((open) => !open);
                    setAccountOpen(false);
                    setNotificationOpen(false);
                  }}
                >
                  <Building2 size={18} aria-hidden="true" />
                </button>

                {organizationMenuOpen && (
                  <div className="workspace-account-menu workspace-organization-menu">
                    <div className="workspace-account-details">
                      <strong>Switch workspace</strong>
                      <small>Select an organization</small>
                    </div>

                    {organizations.map((organization) => {
                      const selected =
                        organization.id === selectedOrganization?.id;

                      return (
                        <button
                          type="button"
                          key={organization.id}
                          className="workspace-organization-option"
                          aria-current={selected ? "true" : undefined}
                          onClick={() =>
                            handleOrganizationSelect(organization.id)
                          }
                        >
                          <Building2 size={16} aria-hidden="true" />
                          <span>{organization.name}</span>
                          {selected && (
                            <Check size={16} aria-label="Selected" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            <button
              type="button"
              className="workspace-icon-button workspace-notification-button"
              aria-label="Notifications"
              title="Notifications"
              aria-haspopup="dialog"
              aria-expanded={notificationOpen}
              onClick={() => {
                setNotificationOpen((open) => !open);
                setAccountOpen(false);
                setOrganizationMenuOpen(false);
              }}
            >
              <Bell size={18} aria-hidden="true" />
            </button>

            {notificationOpen && (
              <div
                className="workspace-account-menu workspace-notification-menu"
                role="dialog"
                aria-label="Notifications"
              >
                <div className="workspace-account-details">
                  <strong>Notifications</strong>
                  <small>No notifications to show yet.</small>
                </div>

                <p className="workspace-notification-empty">
                  Workspace notifications will appear here when the
                  notification feed is connected.
                </p>

                <NavLink
                  to="/notification-preferences"
                  onClick={() => setNotificationOpen(false)}
                >
                  Notification settings
                </NavLink>
              </div>
            )}

            <div className="workspace-account" ref={accountMenuRef}>
              <button
                type="button"
                className="workspace-account-button workspace-profile-trigger"
                aria-label={`Account menu for ${
                  user?.display_name || user?.email || "user"
                }`}
                aria-haspopup="menu"
                aria-expanded={accountOpen}
                onClick={() => {
                  setAccountOpen((open) => !open);
                  setOrganizationMenuOpen(false);
                  setNotificationOpen(false);
                }}
              >
                <span className="workspace-avatar" aria-hidden="true">
                  {avatar}
                </span>

                <span className="workspace-account-name">
                  {user?.display_name || user?.email || "Account"}
                </span>

                <ChevronDown size={15} aria-hidden="true" />
              </button>

              {accountOpen && (
                <div
                  className="workspace-account-menu"
                  role="menu"
                  aria-label="Account menu"
                >
                  <div className="workspace-account-details">
                    <strong>{user?.display_name || "Account"}</strong>
                    <small>{user?.email}</small>
                  </div>

                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void handleSignOut()}
                    disabled={signingOut}
                  >
                    <LogOut size={16} aria-hidden="true" />
                    {signingOut ? "Signing out…" : "Sign out"}
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="workspace-content">
          <Outlet />
        </main>
      </div>

      <WorkspaceCustomizer
        open={customizerOpen}
        preferences={preferences}
        availableModules={[...moduleNames]}
        onClose={() => setCustomizerOpen(false)}
        onChange={updatePreferences}
        onReset={resetPreferences}
      />
    </div>
  );
}

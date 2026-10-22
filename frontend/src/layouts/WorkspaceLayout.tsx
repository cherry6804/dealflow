
import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Activity,
  Bell,
  Building2,
  CalendarCheck,
  Check,
  ChevronDown,
  CircleDollarSign,
  ContactRound,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  SlidersHorizontal,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAppContext } from "../contexts/useAppContext";
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
  { label: "Requirements", to: "/requirements", icon: FileText },
  { label: "Pipeline", to: "/pipeline", icon: Workflow },
  { label: "Deals", to: "/deals", icon: Building2 },
  { label: "Follow-ups", to: "/follow-ups", icon: CalendarCheck },
  { label: "Commissions", to: "/commissions", icon: CircleDollarSign },
  { label: "Documents", to: "/documents", icon: FileText },
  { label: "Activity", to: "/automation-history", icon: Activity },
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

function getInitials(
  name?: string | null,
  email?: string | null,
) {
  const value = name?.trim() || email?.trim() || "U";
  return value.charAt(0).toUpperCase();
}

function getPreferenceKey(
  organizationId: string,
  userId: string,
) {
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

  const userKey = String(user?.id ?? user?.email ?? "");
  const organizationKey = String(selectedOrganization?.id ?? "");
  const preferenceKey =
    userKey && organizationKey
      ? getPreferenceKey(organizationKey, userKey)
      : "";

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [organizationMenuOpen, setOrganizationMenuOpen] =
    useState(false);
  const [customizerOpen, setCustomizerOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  const [preferences, setPreferences] =
    useState<WorkspacePreferences>({
      ...DEFAULT_WORKSPACE_PREFERENCES,
    });

  // Preferences are loaded separately for each user/organization pair.
  // Do not save until the corresponding preferences have finished loading.
  const [loadedPreferenceKey, setLoadedPreferenceKey] = useState("");

  const organizationMenuRef = useRef<HTMLDivElement>(null);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const organizationTriggerRef = useRef<HTMLButtonElement>(null);
  const accountTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!preferenceKey) {
      setPreferences({ ...DEFAULT_WORKSPACE_PREFERENCES });
      setLoadedPreferenceKey("");
      return;
    }

    setLoadedPreferenceKey("");

    setPreferences(
      loadWorkspacePreferences(organizationKey, userKey),
    );

    setLoadedPreferenceKey(preferenceKey);
  }, [preferenceKey, organizationKey, userKey]);

  useEffect(() => {
    if (!preferenceKey || loadedPreferenceKey !== preferenceKey) {
      return;
    }

    saveWorkspacePreferences(
      organizationKey,
      userKey,
      preferences,
    );
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
  }, [location.pathname, organizationKey]);

  useEffect(() => {
    if (!sidebarOpen && !customizerOpen) return;

    function handleEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;

      setSidebarOpen(false);
      setCustomizerOpen(false);
      setAccountOpen(false);
      setOrganizationMenuOpen(false);
    }

    window.addEventListener("keydown", handleEscape);

    return () => {
      window.removeEventListener("keydown", handleEscape);
    };
  }, [sidebarOpen, customizerOpen]);

  useEffect(() => {
    function handleOutsidePointerDown(event: PointerEvent) {
      const target = event.target;

      if (!(target instanceof Node)) return;

      if (
        organizationMenuRef.current &&
        !organizationMenuRef.current.contains(target)
      ) {
        setOrganizationMenuOpen(false);
      }

      if (
        accountMenuRef.current &&
        !accountMenuRef.current.contains(target)
      ) {
        setAccountOpen(false);
      }
    }

    document.addEventListener(
      "pointerdown",
      handleOutsidePointerDown,
    );

    return () => {
      document.removeEventListener(
        "pointerdown",
        handleOutsidePointerDown,
      );
    };
  }, []);

  const orderedNavigation = useMemo(
    () => getOrderedNavigation(preferences.navigationOrder),
    [preferences.navigationOrder],
  );

  const visibleNavigation = orderedNavigation.filter(
    (item) => !preferences.hiddenModules.includes(item.label),
  );

  const avatar = getInitials(
    user?.display_name,
    user?.email,
  );

  function updatePreferences(next: WorkspacePreferences) {
    setPreferences(next);
  }

  function resetPreferences() {
    if (userKey && organizationKey) {
      resetWorkspacePreferences(organizationKey, userKey);
    }

    setPreferences({ ...DEFAULT_WORKSPACE_PREFERENCES });
  }

  function handleOrganizationSelect(organizationId: string) {
    if (!organizationId) return;

    setOrganizationMenuOpen(false);

    if (organizationId !== selectedOrganization?.id) {
      selectOrganization(organizationId);
    }
  }

  async function handleSignOut() {
    if (signingOut) return;

    setSigningOut(true);
    setAccountOpen(false);
    setOrganizationMenuOpen(false);

    try {
      await signOut();
    } finally {
      setSigningOut(false);
    }
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
          <span
            className="workspace-brand-mark"
            aria-hidden="true"
          >
            D
          </span>

          <span className="workspace-brand-copy">
            <strong>DealFlow</strong>
            <small>Real estate workspace</small>
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
          <span className="workspace-org-label">
            WORKSPACE
          </span>

          <div className="workspace-org-select">
            <Building2 size={17} aria-hidden="true" />

            {organizations.length > 1 ? (
              <div
                className="workspace-org-picker"
                ref={organizationMenuRef}
              >
                <button
                  ref={organizationTriggerRef}
                  type="button"
                  className="workspace-org-trigger"
                  aria-label="Select organization"
                  aria-haspopup="listbox"
                  aria-expanded={organizationMenuOpen}
                  title={
                    selectedOrganization?.name ??
                    "Select organization"
                  }
                  onClick={() => {
                    setOrganizationMenuOpen((open) => !open);
                    setAccountOpen(false);
                  }}
                  onKeyDown={(event) => {
                    if (
                      event.key === "ArrowDown" ||
                      event.key === "Enter" ||
                      event.key === " "
                    ) {
                      event.preventDefault();
                      setOrganizationMenuOpen(true);
                    }
                  }}
                >
                  <span>
                    {selectedOrganization?.name ??
                      "Select organization"}
                  </span>
                  <ChevronDown
                    size={15}
                    aria-hidden="true"
                  />
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
                        organization.id ===
                        selectedOrganization?.id;

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
                            handleOrganizationSelect(
                              organization.id,
                            )
                          }
                        >
                          <Building2
                            size={16}
                            aria-hidden="true"
                          />
                          <span>{organization.name}</span>
                          {selected && (
                            <Check
                              size={16}
                              aria-hidden="true"
                            />
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
                title={
                  selectedOrganization?.name ??
                  "Your workspace"
                }
              >
                {selectedOrganization?.name ??
                  "Your workspace"}
              </span>
            )}
          </div>
        </div>

        <nav
          className="workspace-navigation"
          aria-label="Main navigation"
        >
          <span className="workspace-nav-caption">
            WORKSPACE
          </span>

          {visibleNavigation.map(
            ({ label, to, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                onClick={() => setSidebarOpen(false)}
                className={({ isActive }) =>
                  `workspace-nav-link${isActive ? " is-active" : ""}`
                }
                title={
                  preferences.sidebarCollapsed
                    ? label
                    : undefined
                }
              >
                <Icon
                  size={18}
                  strokeWidth={1.8}
                  aria-hidden="true"
                />
                <span>{label}</span>
              </NavLink>
            ),
          )}
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
            className="workspace-nav-link workspace-collapse-button"
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
          <span
            className="workspace-avatar"
            aria-hidden="true"
          >
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
            aria-label="Open navigation"
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen(true)}
          >
            <Menu size={20} aria-hidden="true" />
          </button>

          <div className="workspace-topbar-context">
            <span className="workspace-topbar-eyebrow">
              WORKSPACE
            </span>
            <span className="workspace-topbar-title">
              {selectedOrganization?.name ?? "DealFlow"}
            </span>
          </div>

          <div className="workspace-topbar-search">
            <Search size={17} aria-hidden="true" />
            <input
              type="search"
              aria-label="Search workspace"
              placeholder="Search leads, contacts, properties..."
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.currentTarget.value = "";
                  event.currentTarget.blur();
                }
              }}
            />
            <kbd aria-hidden="true">/</kbd>
          </div>

          <div className="workspace-topbar-actions">
            {organizations.length > 1 && (
              <div
                className="workspace-topbar-organization"
                ref={organizationMenuRef}
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
                  }}
                >
                  <Building2 size={18} aria-hidden="true" />
                </button>

                {organizationMenuOpen && (
                  <div className="workspace-account-menu workspace-organization-menu">
                    <div className="workspace-account-details">
                      <strong>Switch workspace</strong>
                      <small>
                        Select an organization
                      </small>
                    </div>

                    {organizations.map((organization) => {
                      const selected =
                        organization.id ===
                        selectedOrganization?.id;

                      return (
                        <button
                          type="button"
                          key={organization.id}
                          className="workspace-organization-option"
                          aria-current={
                            selected ? "true" : undefined
                          }
                          onClick={() =>
                            handleOrganizationSelect(
                              organization.id,
                            )
                          }
                        >
                          <Building2
                            size={16}
                            aria-hidden="true"
                          />
                          <span>{organization.name}</span>
                          {selected && (
                            <Check
                              size={16}
                              aria-label="Selected"
                            />
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
              onClick={() => {
                // Connect to the real notification feature when available.
              }}
            >
              <Bell size={18} aria-hidden="true" />
            </button>

            <div
              className="workspace-account"
              ref={accountMenuRef}
            >
              <button
                ref={accountTriggerRef}
                type="button"
                className="workspace-account-button"
                aria-haspopup="menu"
                aria-expanded={accountOpen}
                onClick={() => {
                  setAccountOpen((open) => !open);
                  setOrganizationMenuOpen(false);
                }}
              >
                <span
                  className="workspace-avatar"
                  aria-hidden="true"
                >
                  {avatar}
                </span>
                <span className="workspace-account-name">
                  {user?.display_name ||
                    user?.email ||
                    "Account"}
                </span>
                <ChevronDown
                  size={15}
                  aria-hidden="true"
                />
              </button>

              {accountOpen && (
                <div
                  className="workspace-account-menu"
                  role="menu"
                  aria-label="Account menu"
                >
                  <div className="workspace-account-details">
                    <strong>
                      {user?.display_name || "Account"}
                    </strong>
                    <small>{user?.email}</small>
                  </div>

                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => void handleSignOut()}
                    disabled={signingOut}
                  >
                    <LogOut size={16} aria-hidden="true" />
                    {signingOut
                      ? "Signing out…"
                      : "Sign out"}
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

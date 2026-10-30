import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import NotificationBell from "../components/NotificationBell";

type IconName =
  | "today"
  | "pipeline"
  | "deals"
  | "leads"
  | "contacts"
  | "customers"
  | "referrals"
  | "properties"
  | "visits"
  | "requirements"
  | "documents"
  | "imports"
  | "automation"
  | "history"
  | "settings"
  | "help"
  | "menu"
  | "chevron";

type NavigationItem = {
  label: string;
  path: string;
  icon: IconName;
  end?: boolean;
};

type NavigationGroup = {
  label: string;
  items: NavigationItem[];
};

const navigationGroups: NavigationGroup[] = [
  {
    label: "WORKSPACE",
    items: [
      { label: "Today", path: "/", end: true, icon: "today" },
      { label: "Pipeline", path: "/pipeline", icon: "pipeline" },
      { label: "Deals", path: "/deals", icon: "deals" },
    ],
  },
  {
    label: "RELATIONSHIPS",
    items: [
      { label: "Leads", path: "/leads", icon: "leads" },
      { label: "Contacts", path: "/contacts", icon: "contacts" },
      { label: "Customers", path: "/customers", icon: "customers" },
      { label: "Referrals", path: "/referrals", icon: "referrals" },
    ],
  },
  {
    label: "INVENTORY",
    items: [
      { label: "Properties", path: "/properties", icon: "properties" },
      { label: "Site visits", path: "/site-visits", icon: "visits" },
      { label: "Requirements", path: "/requirements", icon: "requirements" },
    ],
  },
  {
    label: "OPERATIONS",
    items: [
      { label: "Documents", path: "/documents", icon: "documents" },
      { label: "Imports", path: "/imports", icon: "imports" },
      { label: "Automation rules", path: "/automation-rules", icon: "automation" },
      { label: "Automation history", path: "/automation-history", icon: "history" },
      {
        label: "Notification settings",
        path: "/notification-preferences",
        icon: "settings",
      },
    ],
  },
];

function getPageTitle(pathname: string): string {
  for (const group of navigationGroups) {
    const item = group.items.find(
      (candidate) =>
        candidate.path === pathname ||
        (candidate.path !== "/" && pathname.startsWith(`${candidate.path}/`)),
    );

    if (item) return item.label;
  }

  return "Workspace";
}

function NavigationIcon({ name }: { name: IconName }) {
  const shared = {
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true as const,
  };

  switch (name) {
    case "today":
      return <svg {...shared}><rect x="3.5" y="5" width="17" height="16" rx="3" /><path d="M8 3v4M16 3v4M3.5 10h17M8 14h3M8 17h6" /></svg>;
    case "pipeline":
      return <svg {...shared}><path d="M4 5h16M4 12h11M4 19h7" /><circle cx="18" cy="12" r="2" /><circle cx="14" cy="19" r="2" /></svg>;
    case "deals":
      return <svg {...shared}><path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5z" /><path d="m4.5 7.8 7.5 4.4 7.5-4.4M12 12.2V21" /></svg>;
    case "leads":
      return <svg {...shared}><circle cx="9" cy="8" r="3" /><path d="M3.5 20v-1.3a5.5 5.5 0 0 1 11 0V20M16 5.5a3 3 0 0 1 0 5.8M17 14.5a4.5 4.5 0 0 1 3.5 4.2v1.3" /></svg>;
    case "contacts":
    case "customers":
      return <svg {...shared}><circle cx="9" cy="8" r="3" /><circle cx="17" cy="9" r="2.2" /><path d="M3 20v-1.5a6 6 0 0 1 12 0V20M16 15a4.5 4.5 0 0 1 5 4.5" /></svg>;
    case "referrals":
      return <svg {...shared}><path d="M7 17 17 7M8 7h9v9" /><path d="M5 12v7h7" /></svg>;
    case "properties":
      return <svg {...shared}><path d="m3 10 9-7 9 7M5.5 9v12h13V9M9 21v-7h6v7" /></svg>;
    case "visits":
      return <svg {...shared}><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="3" /><path d="M12 2v3M22 12h-3" /></svg>;
    case "requirements":
      return <svg {...shared}><rect x="4" y="3.5" width="16" height="17" rx="2.5" /><path d="M8 8h8M8 12h8M8 16h5" /></svg>;
    case "documents":
      return <svg {...shared}><path d="M6 3.5h8l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20z" /><path d="M14 3.5V8h4M9 13h6M9 17h6" /></svg>;
    case "imports":
      return <svg {...shared}><path d="M12 15V3M7 8l5-5 5 5M4 15v5h16v-5" /></svg>;
    case "automation":
      return <svg {...shared}><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" /><circle cx="12" cy="12" r="5" /></svg>;
    case "history":
      return <svg {...shared}><path d="M3.5 11a8.5 8.5 0 1 1 2.4 6M3.5 5v6h6" /><path d="M12 7v5l3 2" /></svg>;
    case "settings":
      return <svg {...shared}><circle cx="12" cy="12" r="3" /><path d="m19.4 15 .1.1a1.8 1.8 0 0 1-2.5 2.5l-.1-.1a1.8 1.8 0 0 0-3 .9v.2a1.8 1.8 0 0 1-3.6 0v-.2a1.8 1.8 0 0 0-3-.9l-.1.1a1.8 1.8 0 0 1-2.5-2.5l.1-.1a1.8 1.8 0 0 0-.9-3h-.2a1.8 1.8 0 0 1 0-3.6h.2a1.8 1.8 0 0 0 .9-3l-.1-.1a1.8 1.8 0 0 1 2.5-2.5l.1.1a1.8 1.8 0 0 0 3-.9v-.2a1.8 1.8 0 0 1 3.6 0v.2a1.8 1.8 0 0 0 3 .9l.1-.1a1.8 1.8 0 0 1 2.5 2.5l-.1.1a1.8 1.8 0 0 0 .9 3h.2a1.8 1.8 0 0 1 0 3.6h-.2a1.8 1.8 0 0 0-.9 3Z" /></svg>;
    case "help":
      return <svg {...shared}><circle cx="12" cy="12" r="9" /><path d="M9.7 9a2.4 2.4 0 1 1 4.1 1.7c-1.1 1.1-1.8 1.4-1.8 3M12 17h.01" /></svg>;
    case "menu":
      return <svg {...shared}><path d="M4 7h16M4 12h16M4 17h16" /></svg>;
    case "chevron":
      return <svg {...shared}><path d="m9 18 6-6-6-6" /></svg>;
  }
}

export default function AppLayout() {
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const location = useLocation();
  const pageTitle = getPageTitle(location.pathname);

  return (
    <div className="app-shell">
      {mobileNavigationOpen && (
        <button
          type="button"
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobileNavigationOpen(false)}
        />
      )}

      <aside
        className={`app-sidebar${mobileNavigationOpen ? " app-sidebar-open" : ""}`}
        aria-label="Application sidebar"
      >
        <NavLink
          to="/"
          className="brand-link"
          aria-label="DealFlow home"
          onClick={() => setMobileNavigationOpen(false)}
        >
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M5 15.2 16 5l11 10.2" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M9 13.2V27h14V13.2M13 27v-8h6v8" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="brand-copy">
            <span className="brand-name">DealFlow</span>
            <span className="brand-subtitle">Real estate workspace</span>
          </span>
        </NavLink>

        <div className="sidebar-workspace">
          <span className="workspace-avatar" aria-hidden="true">D</span>
          <span className="sidebar-workspace-copy">
            <span className="sidebar-workspace-label">YOUR WORKSPACE</span>
            <span className="sidebar-workspace-name">Real Estate CRM</span>
          </span>
          <span className="workspace-chevron" aria-hidden="true">
            <NavigationIcon name="chevron" />
          </span>
        </div>

        <nav className="sidebar-navigation" aria-label="Main navigation">
          {navigationGroups.map((group) => (
            <div className="navigation-group" key={group.label}>
              <p className="navigation-group-label">{group.label}</p>
              <div className="navigation-group-items">
                {group.items.map((item) => (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    end={item.end}
                    className={({ isActive }) =>
                      `navigation-link${isActive ? " active" : ""}`
                    }
                    onClick={() => setMobileNavigationOpen(false)}
                  >
                    <span className="navigation-icon" aria-hidden="true">
                      <NavigationIcon name={item.icon} />
                    </span>
                    <span className="navigation-label">{item.label}</span>
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-help-card">
            <span className="sidebar-help-icon" aria-hidden="true">
              <NavigationIcon name="help" />
            </span>
            <div>
              <p className="sidebar-help-title">Need a hand?</p>
              <p className="sidebar-help-description">
                Keep your business moving.
              </p>
            </div>
          </div>
          <div className="sidebar-footer">
            <span className="sidebar-footer-dot" aria-hidden="true" />
            <span>Workspace operational</span>
          </div>
        </div>
      </aside>

      <div className="app-main">
        <header className="app-header">
          <div className="header-leading">
            <button
              type="button"
              className="mobile-menu-button"
              aria-label={mobileNavigationOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={mobileNavigationOpen}
              onClick={() => setMobileNavigationOpen((open) => !open)}
            >
              <NavigationIcon name="menu" />
            </button>
            <div className="header-breadcrumb" aria-label="Breadcrumb">
              <span className="header-breadcrumb-root">Workspace</span>
              <span className="header-breadcrumb-separator" aria-hidden="true">/</span>
              <span className="header-page-title">{pageTitle}</span>
            </div>
          </div>

          <div className="header-actions">
            <span className="header-context">
              <span className="workspace-indicator" aria-hidden="true" />
              <span>Workspace active</span>
            </span>
            <div className="header-notification">
              <NotificationBell />
            </div>
            <div className="header-profile" aria-label="Account">
              <span className="header-profile-avatar">D</span>
            </div>
          </div>
        </header>

        <main className="app-content" id="main-content">
          <Outlet />
        </main>

        <footer className="app-footer">
          <p>DealFlow · Your real estate business, organized.</p>
          <p>Built for better follow-ups and smarter decisions.</p>
        </footer>
      </div>
    </div>
  );
}

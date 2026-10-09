import { NavLink, Outlet } from "react-router-dom";

const navigation = [
  { label: "Today", path: "/", end: true },
  { label: "Contacts", path: "/contacts", end: false },
  { label: "Leads", path: "/leads", end: false },
  { label: "Properties", path: "/properties", end: false },
  { label: "Requirements", path: "/requirements", end: false },
];

export default function AppLayout() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink to="/" className="brand-link" aria-label="DealFlow home">
          <span className="brand-mark" aria-hidden="true">
            <svg
              viewBox="0 0 32 32"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M5 15.2 16 5l11 10.2"
                stroke="currentColor"
                strokeWidth="2.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M9 13.2V27h14V13.2M13 27v-8h6v8"
                stroke="currentColor"
                strokeWidth="2.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>

          <span className="brand-copy">
            <span className="brand-name">DealFlow</span>
            <span className="brand-subtitle">Real estate workspace</span>
          </span>
        </NavLink>

        <div className="header-context">
          <span className="workspace-indicator" aria-hidden="true" />
          <span>Workspace</span>
        </div>
      </header>

      <nav className="app-navigation" aria-label="Main navigation">
        <div className="navigation-inner">
          {navigation.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.end}
              className={({ isActive }) =>
                isActive ? "navigation-link active" : "navigation-link"
              }
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      <main className="app-content">
        <Outlet />
      </main>

      <footer className="app-footer">
        <p>DealFlow · Your real estate business, organized.</p>
        <p>Built for better follow-ups and smarter decisions.</p>
      </footer>
    </div>
  );
}
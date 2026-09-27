import { NavLink, Outlet } from "react-router-dom";

const navigation = [
  { label: "Today", path: "/" },
  { label: "Contacts", path: "/contacts" },
  { label: "Leads", path: "/leads" },
  { label: "Properties", path: "/properties" },
];

export default function AppLayout() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>DealFlow</h1>
          <p>Real-estate business workspace</p>
        </div>
      </header>

      <nav className="app-navigation" aria-label="Main navigation">
        {navigation.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) =>
              isActive ? "navigation-link active" : "navigation-link"
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="app-content">
        <Outlet />
      </main>
    </div>
  );
}
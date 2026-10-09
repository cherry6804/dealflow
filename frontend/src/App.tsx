import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import AppStatusScreen from "./components/AppStatusScreen";
import { AppProvider } from "./contexts/AppContext";
import { useAppContext } from "./contexts/useAppContext";
import AppLayout from "./layouts/AppLayout";
import ContactsPage from "./pages/ContactsPage";
import LeadsPage from "./pages/LeadsPage";
import LoginPage from "./pages/LoginPage";
import NotFoundPage from "./pages/NotFoundPage";
import PropertiesPage from "./pages/PropertiesPage";
import TodayPage from "./pages/TodayPage";
import RequirementsPage from "./pages/RequirementsPage";

function ApplicationRoutes() {
  const {
    user,
    organizations,
    selectedOrganization,
    status,
    error,
    refreshOrganizations,
  } = useAppContext();

  if (status === "loading") {
    return (
      <AppStatusScreen
        title="Loading your workspace"
        message="Checking your session and preparing your organization."
        loading
      />
    );
  }

  if (status === "error") {
    return (
      <AppStatusScreen
        title="Unable to load your workspace"
        message={error ?? "Something went wrong while loading your account."}
        actionLabel="Try again"
        onAction={() => window.location.reload()}
      />
    );
  }

  if (status === "unauthenticated" || !user) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  if (organizations.length === 0 || !selectedOrganization) {
    return (
      <AppStatusScreen
        title="No organization available"
        message="Your account does not currently have access to an active organization. Contact your workspace administrator to request access."
        actionLabel="Refresh organizations"
        onAction={() => {
          void refreshOrganizations().catch(() => {
            window.location.reload();
          });
        }}
      />
    );
  }

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<TodayPage />} />
        <Route path="/contacts" element={<ContactsPage />} />
        <Route path="/leads" element={<LeadsPage />} />
        <Route path="/properties" element={<PropertiesPage />} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/requirements" element={<RequirementsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <ApplicationRoutes />
      </AppProvider>
    </BrowserRouter>
  );
}

export default App;
import { Navigate, Outlet, useLocation } from "react-router-dom";

import AppStatusScreen from "../../components/AppStatusScreen";
import { useAppContext } from "../../contexts/useAppContext";

export default function RequireAuth() {
  const { status, user, error } = useAppContext();
  const location = useLocation();

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

  if (status !== "authenticated" || !user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}

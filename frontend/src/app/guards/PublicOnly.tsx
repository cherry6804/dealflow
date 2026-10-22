
import { Navigate, Outlet } from "react-router-dom";

import { useAppContext } from "../../contexts/useAppContext";
import AppStatusScreen from "../../components/AppStatusScreen";

export default function PublicOnly() {
  const { status, user } = useAppContext();

  if (status === "loading") {
    return (
      <AppStatusScreen
        title="Preparing DealFlow"
        message="Checking your account."
        loading
      />
    );
  }

  if (status === "error") {
    return (
      <AppStatusScreen
        title="Unable to load your account"
        message="Please retry loading the application."
        actionLabel="Try again"
        onAction={() => window.location.reload()}
      />
    );
  }

  if (status === "authenticated" && user) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}

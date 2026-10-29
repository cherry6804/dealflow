
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../../../lib/api";
import { useAppContext } from "../../../contexts/useAppContext";
import { organizationApi } from "../../../services/organizationApi";

interface SsoCallbackResponse {
  user_id: string;
  organization_id: string;
}

export default function SsoCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { refreshSession, selectOrganization } = useAppContext();
  const [message, setMessage] = useState(
    "Completing secure sign-in…",
  );

  useEffect(() => {
    let cancelled = false;

    async function completeSso() {
      const code = searchParams.get("code");
      const state = searchParams.get("state");
      const providerError = searchParams.get("error");

      if (providerError || !code || !state) {
        setMessage(
          "Sign-in was cancelled or the callback was incomplete. Please start again.",
        );
        return;
      }

      try {
        const result = await api.post<SsoCallbackResponse>(
          "/sso/callback",
          { code, state },
        );

        // The backend sets the existing Dealsflo session cookie.
        await refreshSession();

        const organizations = await organizationApi.list();

        if (cancelled) return;

        const organizationExists = organizations.some(
          (organization) =>
            organization.id === result.organization_id,
        );

        if (!organizationExists) {
          setMessage(
            "This account is linked, but the workspace is not available. Contact your administrator.",
          );
          return;
        }

        selectOrganization(result.organization_id);
        const requestedPath = window.sessionStorage.getItem(
          "dealsflo.sso.returnTo",
        );
        window.sessionStorage.removeItem("dealsflo.sso.returnTo");
        const safePath =
          requestedPath?.startsWith("/") &&
          !requestedPath.startsWith("//") &&
          !requestedPath.includes("\\")
            ? requestedPath
            : "/";
        navigate(safePath, { replace: true });
      } catch (error) {
        if (cancelled) return;

        setMessage(
          error instanceof ApiError
            ? error.message
            : "Secure sign-in could not be completed. Please try again.",
        );
      }
    }

    void completeSso();

    return () => {
      cancelled = true;
    };
  }, [
    navigate,
    refreshSession,
    searchParams,
    selectOrganization,
  ]);

  return (
    <main className="public-auth-page" aria-live="polite">
      <section className="public-auth-card">
        <h1>Sign in to Dealsflo</h1>
        <p>{message}</p>
        <a href="/login">Return to SIBVO sign-in</a>
      </section>
    </main>
  );
}

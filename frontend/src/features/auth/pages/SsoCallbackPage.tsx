
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../../../lib/api";
import { useAppContext } from "../../../contexts/useAppContext";
import { organizationApi } from "../../../services/organizationApi";
import { exchangeCodeOnce } from "../ssoExchange";

export default function SsoCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { refreshSession, selectOrganization } = useAppContext();
  // The effect below runs once per authorization code. Context functions change
  // identity on every state update, so they are read through a ref instead of
  // being effect dependencies. Otherwise each refresh would re-run the callback.
  const contextRef = useRef({ refreshSession, selectOrganization });
  useEffect(() => {
    contextRef.current = { refreshSession, selectOrganization };
  });
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const providerError = searchParams.get("error");
  const providerErrorDescription = searchParams.get("error_description") ?? "";
  const [message, setMessage] = useState(
    "Completing secure sign-in…",
  );

  useEffect(() => {
    let cancelled = false;

    async function completeSso() {
      if (providerError === "access_denied") {
        // SIBVO issued no code. The reason only selects the next step on the
        // access page; it grants nothing by itself.
        const reason = providerErrorDescription;
        navigate(
          `/access-required?${new URLSearchParams({ reason }).toString()}`,
          { replace: true },
        );
        return;
      }

      if (providerError || !code || !state) {
        setMessage(
          "Sign-in was cancelled or the callback was incomplete. Please start again.",
        );
        return;
      }

      try {
        const result = await exchangeCodeOnce(code, state);

        // The backend sets the existing Dealsflo session cookie.
        await contextRef.current.refreshSession();

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

        contextRef.current.selectOrganization(result.organization_id);
        // The backend only returns allowlisted pages; the path is still
        // validated below like any other stored return path.
        const requestedPath =
          result.return_to ??
          window.sessionStorage.getItem("dealsflo.sso.returnTo");
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
  }, [code, state, providerError, providerErrorDescription, navigate]);

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

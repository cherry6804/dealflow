import { useEffect, useMemo } from "react";
import { useLocation } from "react-router-dom";

function getSibvoAuthUrl(mode: "login" | "register"): string {
  const configuredUrl = (
    import.meta.env.VITE_SIBVO_AUTH_URL ?? "http://localhost:5173"
  ).trim();
  const baseUrl = new URL(configuredUrl);

  if (
    !["http:", "https:"].includes(baseUrl.protocol) ||
    baseUrl.username ||
    baseUrl.password ||
    baseUrl.search ||
    baseUrl.hash ||
    !["", "/"].includes(baseUrl.pathname) ||
    (import.meta.env.PROD && baseUrl.protocol !== "https:")
  ) {
    throw new Error("SIBVO authentication URL is invalid.");
  }

  const authUrl = new URL(
    mode === "register" ? "/register" : "/login",
    baseUrl.origin,
  );
  authUrl.searchParams.set("resume_product", "dealsflo");
  return authUrl.toString();
}

export default function SibvoSignInRedirectPage() {
  const location = useLocation();
  const mode = location.pathname === "/signup" ? "register" : "login";
  useEffect(() => {
    const from = (
      location.state as { from?: { pathname?: string; search?: string; hash?: string } } | null
    )?.from;
    const path = `${from?.pathname ?? ""}${from?.search ?? ""}${from?.hash ?? ""}`;
    if (
      path.startsWith("/") &&
      !path.startsWith("//") &&
      !path.includes("\\") &&
      !path.includes("#")
    ) {
      window.sessionStorage.setItem("dealsflo.sso.returnTo", path);
    }
  }, [location.state]);
  const target = useMemo(() => {
    try {
      return getSibvoAuthUrl(mode);
    } catch {
      return null;
    }
  }, [mode]);
  useEffect(() => {
    if (target) window.location.replace(target);
  }, [target]);

  return (
    <main className="public-auth-page" aria-live="polite">
      <section className="public-auth-card">
        <h1>
          {mode === "register"
            ? "Create your SIBVO account"
            : "Sign in with SIBVO"}
        </h1>
        {!target ? (
          <p role="alert">
            SIBVO sign-in is not configured correctly. Contact your administrator.
          </p>
        ) : (
          <p role="status">Taking you to SIBVO…</p>
        )}
        {target && <a href={target}>Continue to SIBVO</a>}
      </section>
    </main>
  );
}

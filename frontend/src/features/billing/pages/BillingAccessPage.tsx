import { useEffect, useState } from "react";
import { api, ApiError } from "../../../lib/api";

interface SibvoEntitlement {
  feature_key: string;
  enabled: boolean;
  limit_value: number | null;
  limit_unit: string | null;
}

interface SibvoAccess {
  subscription_status: string | null;
  plan_version_id: string | null;
  product_role: string | null;
  entitlements: SibvoEntitlement[];
}

/** SIBVO owns billing; Dealsflo shows SIBVO's snapshot and links there. */
function sibvoWorkspaceUrl(): string | null {
  try {
    const base = new URL(
      (import.meta.env.VITE_SIBVO_AUTH_URL ?? "http://localhost:5173").trim(),
    );
    if (
      !["http:", "https:"].includes(base.protocol) ||
      base.username ||
      base.password ||
      (import.meta.env.PROD && base.protocol !== "https:")
    ) {
      return null;
    }
    return new URL("/app", base.origin).toString();
  } catch {
    return null;
  }
}

const STATUS_TEXT: Record<string, string> = {
  trialing: "Free trial",
  active: "Active subscription",
  past_due: "Payment overdue — access continues during the grace period",
};

export default function BillingAccessPage() {
  const [access, setAccess] = useState<SibvoAccess | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const manageUrl = sibvoWorkspaceUrl();

  useEffect(() => {
    let current = true;
    api
      .get<SibvoAccess>("/auth/sibvo-access")
      .then((result) => current && setAccess(result))
      .catch((caught: unknown) => {
        if (!current) return;
        setError(
          caught instanceof ApiError && caught.status === 404
            ? "Plan details are available after you sign in through SIBVO."
            : "Plan details could not be loaded. Please try again.",
        );
      })
      .finally(() => current && setLoading(false));
    return () => {
      current = false;
    };
  }, []);

  return (
    <section className="module-placeholder">
      <div className="module-placeholder__content">
        <span className="module-placeholder__eyebrow">PLAN AND BILLING</span>
        <h1>Plan and billing</h1>
        <p>
          Subscriptions, payments, invoices, and seats are managed in your SIBVO
          account. Dealsflo shows the plan SIBVO has granted to this workspace.
        </p>
        {loading && <p role="status">Loading plan details…</p>}
        {error && <p role="alert">{error}</p>}
        {access && (
          <dl>
            <dt>Status</dt>
            <dd>
              {access.subscription_status
                ? (STATUS_TEXT[access.subscription_status] ??
                  access.subscription_status)
                : "Unknown"}
            </dd>
            <dt>Your product role</dt>
            <dd>{access.product_role ?? "—"}</dd>
            <dt>Included features</dt>
            <dd>
              {access.entitlements.filter((item) => item.enabled).length === 0
                ? "No optional features are included in this plan."
                : access.entitlements
                    .filter((item) => item.enabled)
                    .map((item) =>
                      item.limit_value !== null
                        ? `${item.feature_key.replace(/_/g, " ")} (up to ${item.limit_value}${item.limit_unit ? ` ${item.limit_unit}` : ""})`
                        : item.feature_key.replace(/_/g, " "),
                    )
                    .join(", ")}
            </dd>
          </dl>
        )}
        {manageUrl ? (
          <a className="button button--primary" href={manageUrl}>
            Manage billing in SIBVO
          </a>
        ) : (
          <p role="alert">The SIBVO account link is not configured.</p>
        )}
      </div>
    </section>
  );
}

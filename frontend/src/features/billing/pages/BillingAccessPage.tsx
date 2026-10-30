import { useEffect, useState } from "react";
import { api } from "../../../lib/api";
import {
  accessErrorMessage,
  formatEntitlement,
  seatErrorState,
  subscriptionStatusText,
  summarizeSeats,
  type SeatState,
  type SibvoAccess,
  type SibvoSeats,
} from "../billingAccess";

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

export default function BillingAccessPage() {
  const [access, setAccess] = useState<SibvoAccess | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [seats, setSeats] = useState<SibvoSeats | null>(null);
  const [seatState, setSeatState] = useState<SeatState>("hidden");
  const manageUrl = sibvoWorkspaceUrl();

  useEffect(() => {
    let current = true;

    api
      .get<SibvoAccess>("/auth/sibvo-access")
      .then(async (result) => {
        if (!current) return;
        setAccess(result);
        if (result.product_role !== "owner") {
          setSeatState("hidden");
          return;
        }
        setSeatState("loading");
        try {
          const capacity = await api.get<SibvoSeats>("/auth/sibvo-seats");
          if (!current) return;
          setSeats(capacity);
          setSeatState("ready");
        } catch (caught: unknown) {
          if (!current) return;
          setSeatState(seatErrorState(caught));
        }
      })
      .catch((caught: unknown) => {
        if (!current) return;
        setAccessError(accessErrorMessage(caught));
      })
      .finally(() => current && setLoading(false));

    return () => {
      current = false;
    };
  }, []);

  const summary = seats ? summarizeSeats(seats) : null;

  return (
    <section className="module-placeholder">
      <div className="module-placeholder__content">
        <span className="module-placeholder__eyebrow">PLAN AND BILLING</span>
        <h1>Plan and billing</h1>
        <p>
          Subscriptions, payments, invoices, and seats are managed in your SIBVO
          account. Dealsflo shows the plan and seat capacity SIBVO reports for
          this workspace.
        </p>
        {loading && <p role="status">Loading plan details…</p>}
        {accessError && <p role="alert">{accessError}</p>}
        {access && (
          <dl>
            <dt>Status</dt>
            <dd>{subscriptionStatusText(access.subscription_status)}</dd>
            <dt>Your product role</dt>
            <dd>{access.product_role ?? "—"}</dd>
            <dt>Included features</dt>
            <dd>
              {access.entitlements.filter((item) => item.enabled).length === 0
                ? "No optional features are included in this plan."
                : access.entitlements
                    .filter((item) => item.enabled)
                    .map(formatEntitlement)
                    .join(", ")}
            </dd>
          </dl>
        )}

        {access && (
          <section aria-labelledby="seat-capacity-heading">
            <h2 id="seat-capacity-heading">Seat capacity</h2>
            {seatState === "hidden" && (
              <p>Seat capacity is shown to product owners.</p>
            )}
            {seatState === "loading" && (
              <p role="status">Loading seat capacity…</p>
            )}
            {seatState === "denied" && (
              <p role="alert">
                Seat details are not available for this session.
              </p>
            )}
            {seatState === "unavailable" && (
              <p role="alert">
                Seat information is temporarily unavailable. Refresh the page to
                try again.
              </p>
            )}
            {seatState === "ready" && summary && (
              <>
                <dl>
                  <dt>Seats in use</dt>
                  <dd>{summary.inUse}</dd>
                  <dt>Pending invitations</dt>
                  <dd>{summary.pending}</dd>
                  <dt>Seat limit</dt>
                  <dd>{summary.limitLabel}</dd>
                  <dt>Seats available</dt>
                  <dd>{summary.availableLabel}</dd>
                </dl>
                {summary.atLimit && (
                  <p role="alert">
                    All seats are in use. Upgrade your plan in SIBVO to add
                    seats.
                  </p>
                )}
              </>
            )}
          </section>
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

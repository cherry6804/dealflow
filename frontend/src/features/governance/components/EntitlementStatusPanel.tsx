import { useEffect, useState } from "react";

import {
  governanceApi,
  type EntitlementStatus,
  type EntitlementSnapshotState,
} from "../../../services/governanceApi";

const STATE_TEXT: Record<EntitlementSnapshotState, { label: string; detail: string }> = {
  valid: {
    label: "Verified",
    detail: "SIBVO has verified the plan. Plan checks can use it until it expires.",
  },
  due_for_revalidation: {
    label: "Verified, refresh due",
    detail: "SIBVO has verified the plan, and it is due to be checked again. It stays usable until it expires.",
  },
  expired: {
    label: "Expired",
    detail: "The verified plan has expired. AI stays off until SIBVO verifies the plan again.",
  },
  missing: {
    label: "Not verified",
    detail: "SIBVO has not verified this organization's plan. AI stays off until it does.",
  },
};

function formatInstant(value: string | null): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "Unknown" : parsed.toLocaleString();
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "Plan verification status could not be loaded.";
}

export default function EntitlementStatusPanel() {
  const [status, setStatus] = useState<EntitlementStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    governanceApi
      .getEntitlementStatus()
      .then((value) => {
        if (active) setStatus(value);
      })
      .catch((error: unknown) => {
        if (active) setLoadError(errorText(error));
      });
    return () => {
      active = false;
    };
  }, []);

  if (loadError) {
    return (
      <section aria-labelledby="entitlement-status-heading">
        <h3 id="entitlement-status-heading">Plan verification from SIBVO</h3>
        <p role="alert" className="governance-error">
          {loadError}
        </p>
      </section>
    );
  }

  if (status === null) {
    return (
      <section aria-labelledby="entitlement-status-heading">
        <h3 id="entitlement-status-heading">Plan verification from SIBVO</h3>
        <p role="status">Checking plan verification…</p>
      </section>
    );
  }

  const text = STATE_TEXT[status.state];

  return (
    <section aria-labelledby="entitlement-status-heading" className="governance-group">
      <h3 id="entitlement-status-heading">Plan verification from SIBVO</h3>
      <p>
        <strong>{text.label}.</strong> {text.detail}
      </p>
      <dl className="governance-facts">
        <dt>Checked with SIBVO</dt>
        <dd>Every {status.revalidation_interval_seconds} seconds while SIBVO is reachable</dd>
        <dt>Last verified</dt>
        <dd>{formatInstant(status.fetched_at)}</dd>
        <dt>Valid until</dt>
        <dd>{formatInstant(status.expires_at)}</dd>
        <dt>Signing key</dt>
        <dd>{status.signing_key_configured ? "Configured" : "Not configured. AI stays off."}</dd>
      </dl>
      {status.backoff_active && status.next_refresh_attempt_at ? (
        <p className="governance-muted">
          SIBVO could not be reached. Retries are paused until {formatInstant(status.next_refresh_attempt_at)}.
          A retry never extends the plan's validity.
        </p>
      ) : null}
      <p className="governance-muted">
        A verified plan is necessary but not sufficient. Each capability below must also pass its own checks.
      </p>
    </section>
  );
}

import { useCallback, useEffect, useState } from "react";

import {
  governanceApi,
  type DataCategory,
  type LegalHold,
  type PrivacyRequest,
  type RetentionPolicy,
} from "../../../services/governanceApi";
import {
  requestStatusLabel,
  retentionLabel,
  sensitivityLabel,
} from "../governanceLabels";
import ConfirmChangeDialog from "./ConfirmChangeDialog";

interface PrivacyPanelProps {
  canManage: boolean;
}

interface PrivacyData {
  categories: DataCategory[];
  retention: RetentionPolicy[];
  holds: LegalHold[];
  requests: PrivacyRequest[];
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "The change could not be saved. Please try again.";
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function PrivacyPanel({ canManage }: PrivacyPanelProps) {
  const [data, setData] = useState<PrivacyData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [holdCategory, setHoldCategory] = useState("");
  const [holdReason, setHoldReason] = useState("");
  const [requestType, setRequestType] = useState<"export" | "deletion">("export");
  const [requestCategories, setRequestCategories] = useState<string[]>([]);
  const [pendingRelease, setPendingRelease] = useState<LegalHold | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [retentionCategory, setRetentionCategory] = useState("");
  const [retentionDays, setRetentionDays] = useState("");

  const load = useCallback(async () => {
    try {
      const [categories, retention, holds, requests] = await Promise.all([
        governanceApi.listDataCategories(),
        governanceApi.listRetention(),
        governanceApi.listLegalHolds(),
        governanceApi.listPrivacyRequests(),
      ]);
      setData({ categories, retention, holds, requests });
      setLoadError(null);
    } catch (error) {
      setLoadError(errorText(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>) {
    setSubmitting(true);
    setActionError(null);
    try {
      await action();
      await load();
      return true;
    } catch (error) {
      setActionError(errorText(error));
      return false;
    } finally {
      setSubmitting(false);
    }
  }

  async function placeHold() {
    const reason = holdReason.trim();
    if (!holdCategory || !reason) {
      setActionError("Choose a category and enter the reason for the hold.");
      return;
    }
    if (await run(() => governanceApi.placeLegalHold(holdCategory, reason))) {
      setHoldReason("");
    }
  }

  async function submitRequest() {
    if (requestCategories.length === 0) {
      setActionError("Select at least one data category.");
      return;
    }
    await run(() => governanceApi.createPrivacyRequest(requestType, requestCategories));
  }

  if (loadError) {
    return (
      <p role="alert" className="governance-error">
        {loadError}
      </p>
    );
  }
  if (data === null) {
    return <p role="status">Loading privacy controls…</p>;
  }

  const retentionByKey = new Map(data.retention.map((item) => [item.category_key, item]));
  const activeHolds = data.holds.filter((hold) => hold.released_at === null);

  return (
    <section aria-labelledby="privacy-heading">
      <h2 id="privacy-heading">Privacy, retention and requests</h2>
      <p className="governance-muted">
        Export and deletion requests are recorded and audited. This build does not generate export
        files or delete data; each request shows what is still outstanding.
      </p>
      {actionError ? (
        <p role="alert" className="governance-error">
          {actionError}
        </p>
      ) : null}

      <h3>Data categories</h3>
      <table className="governance-table">
        <caption className="governance-sr-only">Data classification and retention</caption>
        <thead>
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Sensitivity</th>
            <th scope="col">Treatment</th>
            <th scope="col">Retention</th>
            <th scope="col">Availability</th>
          </tr>
        </thead>
        <tbody>
          {data.categories.map((category) => {
            const policy = retentionByKey.get(category.category_key);
            return (
              <tr key={category.category_key}>
                <th scope="row">{category.label}</th>
                <td>{sensitivityLabel(category.sensitivity)}</td>
                <td>{retentionLabel(category.retention_treatment)}</td>
                <td>{policy?.retention_days ? `${policy.retention_days} days` : "Kept until removed"}</td>
                <td>
                  {category.producer_exists ? "Data exists in this product" : category.note || "Not yet built"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {canManage ? (
        <div className="governance-form">
          <h3>Retention</h3>
          <label htmlFor="retention-category">Category</label>
          <select
            id="retention-category"
            value={retentionCategory}
            onChange={(event) => setRetentionCategory(event.target.value)}
          >
            <option value="">Choose a category</option>
            {data.categories.map((category) => (
              <option key={category.category_key} value={category.category_key}>
                {category.label}
              </option>
            ))}
          </select>
          <label htmlFor="retention-days">Retain for (days, blank keeps until removed)</label>
          <input
            id="retention-days"
            inputMode="numeric"
            value={retentionDays}
            onChange={(event) => setRetentionDays(event.target.value)}
          />
          <button
            type="button"
            disabled={submitting || !retentionCategory}
            onClick={() => {
              const trimmed = retentionDays.trim();
              const value = trimmed === "" ? null : Number(trimmed);
              if (value !== null && (!Number.isInteger(value) || value < 1 || value > 36500)) {
                setActionError("Retention must be a whole number of days between 1 and 36500, or blank.");
                return;
              }
              void run(() => governanceApi.setRetention(retentionCategory, value)).then((ok) => {
                if (ok) setRetentionDays("");
              });
            }}
          >
            Save retention
          </button>
        </div>
      ) : null}

      <h3>Legal holds</h3>
      {activeHolds.length === 0 ? (
        <p className="governance-muted">No active legal holds.</p>
      ) : (
        <ul className="governance-list">
          {activeHolds.map((hold) => (
            <li key={hold.id}>
              <strong>{hold.category_key}</strong> — {hold.reason} (placed {formatDate(hold.placed_at)})
              {canManage ? (
                <button type="button" onClick={() => setPendingRelease(hold)} disabled={submitting}>
                  Release hold
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canManage ? (
        <div className="governance-form">
          <label htmlFor="hold-category">Category</label>
          <select id="hold-category" value={holdCategory} onChange={(event) => setHoldCategory(event.target.value)}>
            <option value="">Choose a category</option>
            {data.categories.map((category) => (
              <option key={category.category_key} value={category.category_key}>
                {category.label}
              </option>
            ))}
          </select>
          <label htmlFor="hold-reason">Reason</label>
          <input id="hold-reason" value={holdReason} maxLength={500} onChange={(event) => setHoldReason(event.target.value)} />
          <button type="button" onClick={() => void placeHold()} disabled={submitting}>
            Place legal hold
          </button>
        </div>
      ) : null}

      <h3>Privacy requests</h3>
      {data.requests.length === 0 ? (
        <p className="governance-muted">No requests yet.</p>
      ) : (
        <table className="governance-table">
          <caption className="governance-sr-only">Export and deletion requests</caption>
          <thead>
            <tr>
              <th scope="col">Type</th>
              <th scope="col">Categories</th>
              <th scope="col">Status</th>
              <th scope="col">Requested</th>
              {canManage ? <th scope="col">Action</th> : null}
            </tr>
          </thead>
          <tbody>
            {data.requests.map((request) => (
              <tr key={request.id}>
                <td>{request.request_type}</td>
                <td>{request.categories.join(", ")}</td>
                <td>{requestStatusLabel(request.status)}</td>
                <td>{formatDate(request.created_at)}</td>
                {canManage ? (
                  <td>
                    {["awaiting_artifact_generation", "eligibility_recorded", "ready"].includes(request.status) ? (
                      <button
                        type="button"
                        onClick={() => void run(() => governanceApi.cancelPrivacyRequest(request.id))}
                        disabled={submitting}
                      >
                        Cancel
                      </button>
                    ) : null}
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {canManage ? (
        <fieldset className="governance-form">
          <legend>New request</legend>
          <label htmlFor="request-type">Request type</label>
          <select
            id="request-type"
            value={requestType}
            onChange={(event) => setRequestType(event.target.value as "export" | "deletion")}
          >
            <option value="export">Export</option>
            <option value="deletion">Deletion (eligibility check only)</option>
          </select>
          <div role="group" aria-label="Categories">
            {data.categories.map((category) => (
              <label key={category.category_key} className="governance-checkbox">
                <input
                  type="checkbox"
                  checked={requestCategories.includes(category.category_key)}
                  onChange={(event) =>
                    setRequestCategories((current) =>
                      event.target.checked
                        ? [...current, category.category_key]
                        : current.filter((key) => key !== category.category_key),
                    )
                  }
                />{" "}
                {category.label}
              </label>
            ))}
          </div>
          <button type="button" onClick={() => void submitRequest()} disabled={submitting}>
            Submit request
          </button>
        </fieldset>
      ) : null}

      <ConfirmChangeDialog
        open={pendingRelease !== null}
        title="Release this legal hold?"
        description="Releasing a hold lets deletion requests for this category proceed. The release is audited."
        confirmLabel="Release hold"
        submitting={submitting}
        error={actionError}
        onConfirm={() => {
          if (pendingRelease) {
            void run(() => governanceApi.releaseLegalHold(pendingRelease.id)).then((ok) => {
              if (ok) setPendingRelease(null);
            });
          }
        }}
        onCancel={() => setPendingRelease(null)}
      />
    </section>
  );
}

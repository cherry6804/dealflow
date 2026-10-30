import { useCallback, useEffect, useState } from "react";

import {
  governanceApi,
  type CapabilityState,
} from "../../../services/governanceApi";
import {
  CATEGORY_LABELS,
  capabilityLabel,
  reasonLabel,
} from "../governanceLabels";
import ConfirmChangeDialog from "./ConfirmChangeDialog";

interface CapabilitiesPanelProps {
  canManage: boolean;
}

const CATEGORY_ORDER = ["master", "ai", "automation", "communication"];

function errorText(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "The change could not be saved. Please try again.";
}

export default function CapabilitiesPanel({ canManage }: CapabilitiesPanelProps) {
  const [items, setItems] = useState<CapabilityState[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<CapabilityState | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const response = await governanceApi.listCapabilities();
      setItems(response.items);
      setLoadError(null);
    } catch (error) {
      setLoadError(errorText(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function confirmChange() {
    if (!pending) return;
    setSubmitting(true);
    setSaveError(null);
    try {
      await governanceApi.setCapability(pending.capability_key, !pending.is_enabled);
      setPending(null);
      await load();
    } catch (error) {
      setSaveError(errorText(error));
    } finally {
      setSubmitting(false);
    }
  }

  if (loadError) {
    return (
      <p role="alert" className="governance-error">
        {loadError}
      </p>
    );
  }
  if (items === null) {
    return <p role="status">Loading capability settings…</p>;
  }
  if (items.length === 0) {
    return <p>No capabilities are defined.</p>;
  }

  return (
    <section aria-labelledby="capabilities-heading">
      <h2 id="capabilities-heading">AI and automation capabilities</h2>
      <p className="governance-muted">
        Every capability is off until it is turned on here. Turning on a capability does not
        make it run: each one must also pass the checks shown in the status column.
      </p>
      {CATEGORY_ORDER.map((category) => {
        const rows = items.filter((item) => item.category === category);
        if (rows.length === 0) return null;
        return (
          <div key={category} className="governance-group">
            <h3>{CATEGORY_LABELS[category] ?? category}</h3>
            <table className="governance-table">
              <caption className="governance-sr-only">{CATEGORY_LABELS[category] ?? category}</caption>
              <thead>
                <tr>
                  <th scope="col">Capability</th>
                  <th scope="col">Switch</th>
                  <th scope="col">Status</th>
                  <th scope="col">Policy version</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => (
                  <tr key={item.capability_key}>
                    <th scope="row">{capabilityLabel(item.capability_key)}</th>
                    <td>
                      {canManage ? (
                        <button
                          type="button"
                          aria-pressed={item.is_enabled}
                          aria-label={`${capabilityLabel(item.capability_key)}: ${item.is_enabled ? "on" : "off"}. Change`}
                          onClick={() => {
                            setSaveError(null);
                            setPending(item);
                          }}
                        >
                          {item.is_enabled ? "On" : "Off"}
                        </button>
                      ) : (
                        <span>{item.is_enabled ? "On" : "Off"}</span>
                      )}
                    </td>
                    <td>
                      {item.effective.allowed ? (
                        <span>{reasonLabel(item.effective.reason_code)}</span>
                      ) : (
                        <span>
                          {reasonLabel(item.effective.reason_code)}
                          <span className="governance-muted"> — {item.effective.explanation}</span>
                        </span>
                      )}
                    </td>
                    <td>{item.policy_version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
      <ConfirmChangeDialog
        open={pending !== null}
        title={pending ? `${pending.is_enabled ? "Turn off" : "Turn on"} ${capabilityLabel(pending.capability_key)}?` : ""}
        description={
          pending?.is_enabled
            ? "New executions stop immediately. Work already in progress follows the documented in-flight policy."
            : "Turning this on only permits it. It still runs only when every other check passes."
        }
        confirmLabel={pending?.is_enabled ? "Turn off" : "Turn on"}
        submitting={submitting}
        error={saveError}
        onConfirm={() => void confirmChange()}
        onCancel={() => setPending(null)}
      />
    </section>
  );
}

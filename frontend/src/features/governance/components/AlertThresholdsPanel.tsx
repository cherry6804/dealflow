import { useCallback, useEffect, useState } from "react";

import { governanceApi, type AlertThresholds } from "../../../services/governanceApi";
import ConfirmChangeDialog from "./ConfirmChangeDialog";
import { parseThresholdDraft } from "./alertThresholdDraft";

interface AlertThresholdsPanelProps {
  canManage: boolean;
}

const FIELD_LABELS = ["First alert", "Second alert", "Final alert"];

function errorText(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "The alert thresholds could not be saved. Please try again.";
}

export default function AlertThresholdsPanel({ canManage }: AlertThresholdsPanelProps) {
  const [settings, setSettings] = useState<AlertThresholds | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<string[]>(["", "", ""]);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      setSettings(await governanceApi.getAlertThresholds());
      setLoadError(null);
    } catch (error) {
      setLoadError(errorText(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function openEditor() {
    if (settings) {
      setDrafts(settings.thresholds.map((value) => String(value)));
    }
    setFormError(null);
    setEditing(true);
  }

  async function save() {
    const parsed = parseThresholdDraft(drafts);
    if (!parsed.ok) {
      setFormError(parsed.error);
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await governanceApi.setAlertThresholds(parsed.values);
      setEditing(false);
      await load();
    } catch (error) {
      setFormError(errorText(error));
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
  if (settings === null) {
    return <p role="status">Loading alert thresholds…</p>;
  }

  return (
    <section aria-labelledby="alert-thresholds-heading">
      <h3 id="alert-thresholds-heading">Usage alert thresholds</h3>
      <p className="governance-muted">
        When an AI usage budget reaches a threshold, organization administrators receive an in-app
        notification. No email or other message is sent.
        {settings.is_default ? " The organization is using the default thresholds." : null}
      </p>
      <p>
        Alerts at{" "}
        {settings.thresholds.map((value, index) => (
          <span key={value}>
            {index > 0 ? (index === settings.thresholds.length - 1 ? " and " : ", ") : null}
            {value}%
          </span>
        ))}{" "}
        of the budget.
      </p>
      {canManage ? (
        <button type="button" onClick={openEditor}>
          Change alert thresholds
        </button>
      ) : null}

      {editing ? (
        <ConfirmChangeDialog
          open
          title="Change usage alert thresholds"
          description="Thresholds apply to every unit for this organization, starting now. Usage already at or above a new threshold is announced once. Alerts are in-app notifications only."
          confirmLabel="Save thresholds"
          submitting={submitting}
          error={formError}
          onConfirm={() => void save()}
          onCancel={() => setEditing(false)}
        >
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            {FIELD_LABELS.map((label, index) => (
              <div key={label}>
                <label htmlFor={`alert-threshold-${index}`}>{label} (percent)</label>
                <input
                  id={`alert-threshold-${index}`}
                  inputMode="numeric"
                  value={drafts[index]}
                  onChange={(event) => {
                    const next = [...drafts];
                    next[index] = event.target.value;
                    setDrafts(next);
                  }}
                />
              </div>
            ))}
            <p className="governance-muted">
              Enter three whole numbers that increase, from 1 to 100. The final alert must be 100.
            </p>
          </form>
        </ConfirmChangeDialog>
      ) : null}
    </section>
  );
}

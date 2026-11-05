import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import { workflowApi, type RunStatus, type WorkflowRun } from "../services/workflowApi";

interface WorkflowRunsPanelProps {
  workflowId: string;
  canStart: boolean;
}

const ACTIVE: RunStatus[] = ["queued", "running", "waiting_approval", "waiting_timer"];
const RETRYABLE: RunStatus[] = ["failed", "dead_letter", "timed_out", "stopped"];

const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  waiting_approval: "Waiting for approval",
  waiting_timer: "Waiting for a delay",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
  stopped: "Stopped at a check",
  timed_out: "Timed out",
  dead_letter: "Dead-lettered after retries",
};

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.details as { detail?: { reason?: string; problems?: string[] } } | undefined;
    const inner = detail?.detail;
    if (inner?.problems?.length) return `${inner.reason ?? "Refused"}: ${inner.problems.join(" ")}`;
    return inner?.reason ?? error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

export default function WorkflowRunsPanel({ workflowId, canStart }: WorkflowRunsPanelProps) {
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [selected, setSelected] = useState<WorkflowRun | null>(null);
  const [inputText, setInputText] = useState("{}");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");

  const loadRuns = useCallback(async () => {
    try {
      setRuns((await workflowApi.listRuns(workflowId)).items);
    } catch (caught) {
      setError(messageFor(caught));
    }
  }, [workflowId]);

  const loadRun = useCallback(async (runId: string) => {
    try {
      setSelected(await workflowApi.getRun(runId));
    } catch (caught) {
      setError(messageFor(caught));
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  async function act(action: () => Promise<WorkflowRun | unknown>, done: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = (await action()) as WorkflowRun | undefined;
      setNotice(done);
      await loadRuns();
      if (result?.id) await loadRun(result.id);
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  }

  async function startRun() {
    let input: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(inputText || "{}");
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("The input must be a JSON object.");
      input = parsed as Record<string, unknown>;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The input is not valid JSON.");
      return;
    }
    await act(() => workflowApi.startRun(workflowId, input, `ui-${crypto.randomUUID()}`), "Run started.");
  }

  const pending = selected?.pending_approval ?? null;

  return (
    <section className="workflows-panel" aria-labelledby="workflow-runs-title">
      <h2 id="workflow-runs-title">Runs</h2>
      <p className="workflows-subtle">
        A run uses the version that was current when it started. Nothing here is simulated: a step shows only what the runtime recorded.
      </p>
      {error ? <p role="alert" className="workflows-alert">{error}</p> : null}
      {notice ? <p role="status" className="workflows-notice">{notice}</p> : null}

      {canStart ? (
        <div className="workflows-row">
          <label>
            Input (JSON object)
            <textarea value={inputText} onChange={(event) => setInputText(event.target.value)} rows={3} />
          </label>
          <button type="button" className="workflows-button" disabled={busy} onClick={() => void startRun()}>
            Start a run
          </button>
        </div>
      ) : (
        <p className="workflows-subtle">Publish the workflow and make sure it is active before starting a run.</p>
      )}

      {runs.length === 0 ? <p className="workflows-subtle">No runs yet.</p> : null}
      <ul className="workflows-list">
        {runs.map((run) => (
          <li key={run.id}>
            <button type="button" className="workflows-list-item" onClick={() => void loadRun(run.id)}>
              <span>
                Version {run.version_number} · {run.trigger.type === "event" ? `event ${run.trigger.event}` : "manual"} ·{" "}
                {run.created_at ? new Date(run.created_at).toLocaleString() : ""}
              </span>
              <span className={`workflows-badge workflows-badge-${run.status}`}>{STATUS_LABEL[run.status]}</span>
            </button>
          </li>
        ))}
      </ul>

      {selected ? (
        <div className="workflows-panel" aria-live="polite">
          <h3>Run details</h3>
          <p>
            {STATUS_LABEL[selected.status]} · version {selected.version_number}
            {selected.failure_reason ? ` · reason: ${selected.failure_reason}` : ""}
          </p>
          {selected.trigger.type === "event" ? (
            <p className="workflows-subtle">Triggered by event {selected.trigger.event} (key {selected.trigger.event_key}).</p>
          ) : null}
          {selected.retry_of_execution_id ? <p className="workflows-subtle">A retry of run {selected.retry_of_execution_id}.</p> : null}
          <ol className="workflows-history">
            {(selected.steps ?? []).map((step) => (
              <li key={step.step_id}>
                <strong>{step.step_id}</strong> ({step.type}): {step.status}
                {step.reason_code ? ` · ${step.reason_code}` : ""}
                {step.attempts > 1 ? ` · ${step.attempts} attempts` : ""}
              </li>
            ))}
          </ol>

          {pending ? (
            <div className="workflows-row">
              <p>
                Approval needed for step {pending.step_id}
                {pending.reason ? `: ${pending.reason}` : ""} (requires {pending.approver_permission}).
              </p>
              <label>
                Reason
                <input value={reason} maxLength={500} onChange={(event) => setReason(event.target.value)} />
              </label>
              <button type="button" className="workflows-button" disabled={busy} onClick={() =>
                void act(() => workflowApi.decideStep(selected.id, pending.step_id, "approve", reason), "Approved.")}>
                Approve
              </button>
              <button type="button" className="workflows-button workflows-button-secondary" disabled={busy} onClick={() =>
                void act(() => workflowApi.decideStep(selected.id, pending.step_id, "reject", reason), "Rejected.")}>
                Reject
              </button>
            </div>
          ) : null}

          <div className="workflows-row">
            {ACTIVE.includes(selected.status) ? (
              <button type="button" className="workflows-button workflows-button-secondary" disabled={busy} onClick={() =>
                void act(() => workflowApi.cancelRun(selected.id), "Cancellation requested.")}>
                Cancel run
              </button>
            ) : null}
            {RETRYABLE.includes(selected.status) ? (
              <button type="button" className="workflows-button workflows-button-secondary" disabled={busy} onClick={() =>
                void act(() => workflowApi.retryRun(selected.id), "A new run was started from the same version and input.")}>
                Retry as a new run
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

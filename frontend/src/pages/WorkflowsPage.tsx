import { useCallback, useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../lib/api";
import {
  workflowApi,
  type LifecycleEvent,
  type StepType,
  type VersionSummary,
  type WorkflowConfiguration,
  type WorkflowDetail,
  type WorkflowProblem,
  type WorkflowStep,
  type WorkflowSummary,
} from "../services/workflowApi";

import WorkflowRunsPanel from "./WorkflowRunsPanel";

import "./WorkflowsPage.css";

const CRM_ACTIONS = [
  "intake.process",
  "intake.resolve_identity",
  "lead.calculate_priority",
  "qualification.record",
  "matching.evaluate",
] as const;
const STEP_TYPES: StepType[] = ["crm_action", "condition", "agent", "approval", "delay"];
const OPERATORS = ["eq", "neq", "in", "not_in", "exists", "gt", "gte", "lt", "lte"];
const APPROVERS = ["leads.update", "requirements.update", "agents.approve"];
const CATEGORIES = ["sales", "operations", "research"];
const EVENTS = ["lead.created", "lead.updated", "site_visit.scheduled", "deal.created"];

interface StepDraft {
  id: string;
  type: StepType;
  next: string;
  action: string;
  argumentsText: string;
  left: string;
  operator: string;
  right: string;
  then: string;
  elseStep: string;
  agentId: string;
  agentArgumentsText: string;
  approver: string;
  reason: string;
  seconds: string;
}

interface Editor {
  name: string;
  description: string;
  category: string;
  purpose: string;
  triggerType: "manual" | "event";
  event: string;
  inputs: Array<{ name: string; type: string; required: boolean }>;
  entry: string;
  steps: StepDraft[];
  maxSteps: string;
  maxDuration: string;
  maxConcurrent: string;
  maxPerHour: string;
  labels: string;
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.details as { detail?: { reason?: string; problems?: WorkflowProblem[] } } | undefined;
    const inner = detail?.detail;
    if (inner?.problems?.length) {
      return `${inner.reason ?? "Refused"}: ${inner.problems.map((item) => `${item.path}: ${item.message}`).join(" ")}`;
    }
    return inner?.reason ?? error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

function emptyStep(id = "step_1"): StepDraft {
  return {
    id, type: "crm_action", next: "", action: CRM_ACTIONS[0], argumentsText: '{\n  "lead_id": "$input.lead_id"\n}',
    left: "", operator: "eq", right: "", then: "", elseStep: "", agentId: "", agentArgumentsText: "{}",
    approver: APPROVERS[0], reason: "", seconds: "60",
  };
}

function editorFrom(detail: WorkflowDetail): Editor {
  const draft: WorkflowConfiguration = detail.draft ?? {};
  const limits = draft.limits ?? {};
  return {
    name: detail.name,
    description: detail.description ?? "",
    category: draft.category ?? "",
    purpose: draft.purpose ?? "",
    triggerType: draft.trigger?.type === "event" ? "event" : "manual",
    event: draft.trigger?.type === "event" ? draft.trigger.event : EVENTS[0],
    inputs: draft.inputs ?? [],
    entry: draft.entry ?? "",
    steps: (draft.steps ?? []).map((step) => ({
      id: step.id,
      type: step.type,
      next: step.next ?? "",
      action: step.action ?? CRM_ACTIONS[0],
      argumentsText: JSON.stringify(step.arguments ?? {}, null, 2),
      left: step.condition?.left ?? "",
      operator: step.condition?.operator ?? "eq",
      right: step.condition?.right === undefined ? "" : String(step.condition.right),
      then: step.then ?? "",
      elseStep: step.else ?? "",
      agentId: step.agent_id ?? "",
      agentArgumentsText: JSON.stringify(step.arguments ?? {}, null, 2),
      approver: step.approver_permission ?? APPROVERS[0],
      reason: step.reason ?? "",
      seconds: step.seconds === undefined ? "60" : String(step.seconds),
    })),
    maxSteps: String(limits.max_steps ?? ""),
    maxDuration: String(limits.max_duration_seconds ?? ""),
    maxConcurrent: String(limits.max_concurrent_runs ?? ""),
    maxPerHour: String(limits.max_runs_per_hour ?? ""),
    labels: (draft.metadata?.labels ?? []).join(", "),
  };
}

function parseJsonObject(text: string, path: string): Record<string, string> {
  const parsed: unknown = JSON.parse(text || "{}");
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${path} must be a JSON object.`);
  }
  return parsed as Record<string, string>;
}

function buildConfiguration(editor: Editor): WorkflowConfiguration {
  const steps: WorkflowStep[] = editor.steps.map((draft) => {
    const base: WorkflowStep = { id: draft.id, type: draft.type };
    if (draft.type === "condition") {
      const right = draft.operator === "exists" ? undefined : draft.right;
      return {
        ...base,
        condition: { left: draft.left, operator: draft.operator, right },
        then: draft.then,
        else: draft.elseStep,
      };
    }
    if (draft.next) base.next = draft.next;
    if (draft.type === "crm_action") {
      return { ...base, action: draft.action, arguments: parseJsonObject(draft.argumentsText, `Step ${draft.id} arguments`) };
    }
    if (draft.type === "agent") {
      return { ...base, agent_id: draft.agentId, arguments: parseJsonObject(draft.agentArgumentsText, `Step ${draft.id} inputs`) };
    }
    if (draft.type === "approval") {
      return { ...base, approver_permission: draft.approver, reason: draft.reason };
    }
    return { ...base, seconds: Number(draft.seconds) };
  });
  const numberOrUndefined = (value: string) => (value.trim() === "" ? undefined : Number(value));
  const limits: Record<string, number> = {};
  const limitEntries: Array<[string, string]> = [
    ["max_steps", editor.maxSteps],
    ["max_duration_seconds", editor.maxDuration],
    ["max_concurrent_runs", editor.maxConcurrent],
    ["max_runs_per_hour", editor.maxPerHour],
  ];
  for (const [key, value] of limitEntries) {
    const parsed = numberOrUndefined(value);
    if (parsed !== undefined) limits[key] = parsed;
  }
  return {
    schema_version: "workflow.v1",
    category: editor.category || null,
    purpose: editor.purpose || null,
    trigger: editor.triggerType === "event" ? { type: "event", event: editor.event } : { type: "manual" },
    inputs: editor.inputs,
    entry: editor.entry || null,
    steps,
    limits,
    metadata: { labels: editor.labels.split(",").map((item) => item.trim()).filter(Boolean) },
  };
}

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<WorkflowDetail | null>(null);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [history, setHistory] = useState<LifecycleEvent[]>([]);
  const [problems, setProblems] = useState<WorkflowProblem[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");

  const loadList = useCallback(async () => {
    try {
      setWorkflows((await workflowApi.list()).items);
    } catch (caught) {
      setError(messageFor(caught));
    }
  }, []);

  const loadDetail = useCallback(async (workflowId: string) => {
    try {
      const [row, versionList, events] = await Promise.all([
        workflowApi.get(workflowId),
        workflowApi.versions(workflowId),
        workflowApi.history(workflowId),
      ]);
      setDetail(row);
      setEditor(editorFrom(row));
      setVersions(versionList.items);
      setHistory(events.items);
      setError(null);
    } catch (caught) {
      setError(messageFor(caught));
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    setProblems([]);
    try {
      await action();
      setNotice(done);
      await loadList();
      if (selectedId) await loadDetail(selectedId);
    } catch (caught) {
      setError(messageFor(caught));
      if (caught instanceof ApiError) {
        const inner = (caught.details as { detail?: { problems?: WorkflowProblem[] } } | undefined)?.detail;
        setProblems(inner?.problems ?? []);
      }
    } finally {
      setBusy(false);
    }
  }

  async function createWorkflow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    await run(async () => {
      const created = await workflowApi.create({ name });
      setNewName("");
      setSelectedId(created.id);
    }, "Draft workflow created.");
  }

  function updateEditor(patch: Partial<Editor>) {
    setEditor((current) => (current ? { ...current, ...patch } : current));
  }

  function updateStep(index: number, patch: Partial<StepDraft>) {
    setEditor((current) => {
      if (!current) return current;
      const steps = current.steps.map((step, position) => (position === index ? { ...step, ...patch } : step));
      return { ...current, steps };
    });
  }

  function saveDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail || !editor) return;
    let configuration: WorkflowConfiguration;
    try {
      configuration = buildConfiguration(editor);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The step configuration is not valid JSON.");
      return;
    }
    void run(
      () => workflowApi.saveDraft(detail.id, {
        revision: detail.revision,
        name: editor.name,
        description: editor.description || null,
        configuration,
      }),
      "Draft saved.",
    );
  }

  if (!selectedId) {
    return (
      <main className="workflows-page">
        <header className="workflows-header">
          <h1>Workflows</h1>
          <p className="workflows-subtle">
            Define how work moves between CRM actions, conditions, agents, approvals and delays. Nothing runs from a draft.
          </p>
        </header>
        {error ? <p role="alert" className="workflows-alert">{error}</p> : null}
        {notice ? <p role="status" className="workflows-notice">{notice}</p> : null}
        <section className="workflows-panel" aria-labelledby="workflow-new-title">
          <h2 id="workflow-new-title">New workflow</h2>
          <form className="workflows-row" onSubmit={createWorkflow}>
            <label>
              Name
              <input value={newName} onChange={(event) => setNewName(event.target.value)} maxLength={120} required />
            </label>
            <button type="submit" className="workflows-button" disabled={busy}>Create draft</button>
          </form>
        </section>
        <section className="workflows-panel" aria-labelledby="workflow-list-title">
          <h2 id="workflow-list-title">Workflows in this organization</h2>
          {workflows.length === 0 ? <p className="workflows-subtle">No workflows yet.</p> : null}
          <ul className="workflows-list">
            {workflows.map((item) => (
              <li key={item.id}>
                <button type="button" className="workflows-list-item" onClick={() => setSelectedId(item.id)}>
                  <span>{item.name}</span>
                  <span className={`workflows-badge workflows-badge-${item.status}`}>{item.status}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </main>
    );
  }

  if (!detail || !editor) {
    return (
      <main className="workflows-page">
        <button type="button" className="workflows-button workflows-button-secondary" onClick={() => setSelectedId(null)}>
          Back to workflows
        </button>
        {error ? <p role="alert" className="workflows-alert">{error}</p> : <p>Loading workflow…</p>}
      </main>
    );
  }

  const stepIds = editor.steps.map((step) => step.id).filter(Boolean);
  const editable = detail.status !== "archived";

  return (
    <main className="workflows-page">
      <header className="workflows-header">
        <button type="button" className="workflows-button workflows-button-secondary" onClick={() => setSelectedId(null)}>
          Back to workflows
        </button>
        <h1>{detail.name}</h1>
        <p>
          <span className={`workflows-badge workflows-badge-${detail.status}`}>{detail.status}</span>{" "}
          {detail.current_version ? `Current version ${detail.current_version.version_number}` : "No published version yet"}
          {detail.has_unpublished_changes ? " · draft has unpublished changes" : ""}
        </p>
      </header>

      {error ? <p role="alert" className="workflows-alert">{error}</p> : null}
      {notice ? <p role="status" className="workflows-notice">{notice}</p> : null}
      {problems.length > 0 ? (
        <ul role="alert" className="workflows-problems" aria-label="Validation problems">
          {problems.map((item, index) => (
            <li key={`${item.path}-${index}`}><strong>{item.path}</strong>: {item.message}</li>
          ))}
        </ul>
      ) : null}

      <form onSubmit={saveDraft} className="workflows-panel" aria-labelledby="workflow-form-title">
        <h2 id="workflow-form-title">Definition</h2>
        <div className="workflows-grid">
          <label>
            Name
            <input value={editor.name} onChange={(event) => updateEditor({ name: event.target.value })} disabled={!editable} required />
          </label>
          <label>
            Category
            <select value={editor.category} onChange={(event) => updateEditor({ category: event.target.value })} disabled={!editable}>
              <option value="">Not set</option>
              {CATEGORIES.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="workflows-wide">
            Description
            <input value={editor.description} onChange={(event) => updateEditor({ description: event.target.value })} disabled={!editable} maxLength={1000} />
          </label>
          <label className="workflows-wide">
            Purpose
            <textarea value={editor.purpose} onChange={(event) => updateEditor({ purpose: event.target.value })} disabled={!editable} maxLength={500} />
          </label>
          <label>
            Trigger
            <select value={editor.triggerType} onChange={(event) => updateEditor({ triggerType: event.target.value as "manual" | "event" })} disabled={!editable}>
              <option value="manual">Started by a member</option>
              <option value="event">Declared event</option>
            </select>
          </label>
          {editor.triggerType === "event" ? (
            <label>
              Event
              <select value={editor.event} onChange={(event) => updateEditor({ event: event.target.value })} disabled={!editable}>
                {EVENTS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
          ) : null}
          <label>
            Labels (comma separated)
            <input value={editor.labels} onChange={(event) => updateEditor({ labels: event.target.value })} disabled={!editable} />
          </label>
        </div>

        <h3>Execution limits</h3>
        <div className="workflows-grid">
          <label>Max steps<input type="number" min={1} max={50} value={editor.maxSteps} onChange={(event) => updateEditor({ maxSteps: event.target.value })} disabled={!editable} /></label>
          <label>Max duration (seconds)<input type="number" min={1} max={86400} value={editor.maxDuration} onChange={(event) => updateEditor({ maxDuration: event.target.value })} disabled={!editable} /></label>
          <label>Max concurrent runs<input type="number" min={1} max={10} value={editor.maxConcurrent} onChange={(event) => updateEditor({ maxConcurrent: event.target.value })} disabled={!editable} /></label>
          <label>Max runs per hour<input type="number" min={1} max={10000} value={editor.maxPerHour} onChange={(event) => updateEditor({ maxPerHour: event.target.value })} disabled={!editable} /></label>
        </div>

        <h3>Inputs</h3>
        <ul className="workflows-inline-list">
          {editor.inputs.map((item, index) => (
            <li key={`${item.name}-${index}`}>
              <code>{item.name}</code> ({item.type}, {item.required ? "required" : "optional"})
              {editable ? (
                <button type="button" className="workflows-link" onClick={() => updateEditor({ inputs: editor.inputs.filter((_, position) => position !== index) })}>
                  Remove
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {editable ? (
          <div className="workflows-row">
            <button type="button" className="workflows-button workflows-button-secondary" onClick={() => updateEditor({
              inputs: [...editor.inputs, { name: `input_${editor.inputs.length + 1}`, type: "uuid", required: true }],
            })}>
              Add input
            </button>
          </div>
        ) : null}

        <h3>Steps</h3>
        <label>
          Entry step
          <select value={editor.entry} onChange={(event) => updateEditor({ entry: event.target.value })} disabled={!editable}>
            <option value="">Choose the first step</option>
            {stepIds.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <ol className="workflows-steps">
          {editor.steps.map((step, index) => (
            <li key={`${step.id}-${index}`} className="workflows-step">
              <div className="workflows-grid">
                <label>Step id<input value={step.id} onChange={(event) => updateStep(index, { id: event.target.value })} disabled={!editable} /></label>
                <label>
                  Type
                  <select value={step.type} onChange={(event) => updateStep(index, { type: event.target.value as StepType })} disabled={!editable}>
                    {STEP_TYPES.map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </label>
                {step.type !== "condition" ? (
                  <label>
                    Next step
                    <select value={step.next} onChange={(event) => updateStep(index, { next: event.target.value })} disabled={!editable}>
                      <option value="">None (end)</option>
                      {stepIds.filter((item) => item !== step.id).map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                ) : null}
              </div>

              {step.type === "crm_action" ? (
                <div className="workflows-grid">
                  <label>
                    CRM action
                    <select value={step.action} onChange={(event) => updateStep(index, { action: event.target.value })} disabled={!editable}>
                      {CRM_ACTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                  <label className="workflows-wide">
                    Arguments (JSON of references, for example {"{"}"lead_id": "$input.lead_id"{"}"})
                    <textarea value={step.argumentsText} onChange={(event) => updateStep(index, { argumentsText: event.target.value })} disabled={!editable} rows={3} />
                  </label>
                </div>
              ) : null}

              {step.type === "condition" ? (
                <div className="workflows-grid">
                  <label>Left reference<input value={step.left} onChange={(event) => updateStep(index, { left: event.target.value })} placeholder="$steps.score.band" disabled={!editable} /></label>
                  <label>
                    Operator
                    <select value={step.operator} onChange={(event) => updateStep(index, { operator: event.target.value })} disabled={!editable}>
                      {OPERATORS.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                  <label>Value<input value={step.right} onChange={(event) => updateStep(index, { right: event.target.value })} disabled={!editable || step.operator === "exists"} /></label>
                  <label>
                    If true, go to
                    <select value={step.then} onChange={(event) => updateStep(index, { then: event.target.value })} disabled={!editable}>
                      <option value="">Choose</option>
                      {stepIds.filter((item) => item !== step.id).map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                  <label>
                    If false, go to
                    <select value={step.elseStep} onChange={(event) => updateStep(index, { elseStep: event.target.value })} disabled={!editable}>
                      <option value="">Choose</option>
                      {stepIds.filter((item) => item !== step.id).map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                </div>
              ) : null}

              {step.type === "agent" ? (
                <div className="workflows-grid">
                  <label>Agent identifier<input value={step.agentId} onChange={(event) => updateStep(index, { agentId: event.target.value })} disabled={!editable} /></label>
                  <label className="workflows-wide">
                    Inputs (JSON of references)
                    <textarea value={step.agentArgumentsText} onChange={(event) => updateStep(index, { agentArgumentsText: event.target.value })} disabled={!editable} rows={2} />
                  </label>
                </div>
              ) : null}

              {step.type === "approval" ? (
                <div className="workflows-grid">
                  <label>
                    Approver permission
                    <select value={step.approver} onChange={(event) => updateStep(index, { approver: event.target.value })} disabled={!editable}>
                      {APPROVERS.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                  </label>
                  <label className="workflows-wide">Reason shown to the approver<input value={step.reason} onChange={(event) => updateStep(index, { reason: event.target.value })} disabled={!editable} maxLength={500} /></label>
                </div>
              ) : null}

              {step.type === "delay" ? (
                <div className="workflows-grid">
                  <label>Wait (seconds)<input type="number" min={1} max={604800} value={step.seconds} onChange={(event) => updateStep(index, { seconds: event.target.value })} disabled={!editable} /></label>
                </div>
              ) : null}

              {editable ? (
                <button type="button" className="workflows-link" onClick={() => updateEditor({ steps: editor.steps.filter((_, position) => position !== index) })}>
                  Remove step
                </button>
              ) : null}
            </li>
          ))}
        </ol>
        {editable ? (
          <div className="workflows-row">
            <button type="button" className="workflows-button workflows-button-secondary" onClick={() => updateEditor({
              steps: [...editor.steps, emptyStep(`step_${editor.steps.length + 1}`)],
            })}>
              Add step
            </button>
          </div>
        ) : null}

        {editable ? (
          <div className="workflows-row">
            <button type="submit" className="workflows-button" disabled={busy}>Save draft</button>
            <button type="button" className="workflows-button workflows-button-secondary" disabled={busy} onClick={() =>
              void run(async () => {
                const result = await workflowApi.validate(detail.id);
                setProblems(result.problems);
                setNotice(result.valid ? "The draft is valid and can be published." : "The draft has problems to fix.");
              }, "")}>
              Validate
            </button>
          </div>
        ) : null}
      </form>

      <section className="workflows-panel" aria-labelledby="workflow-lifecycle-title">
        <h2 id="workflow-lifecycle-title">Publish and lifecycle</h2>
        <div className="workflows-row">
          {editable ? (
            <button type="button" className="workflows-button" disabled={busy} onClick={() =>
              void run(() => workflowApi.publish(detail.id), "Version published.")}>
              Publish draft
            </button>
          ) : null}
          {detail.status === "published" ? (
            <button type="button" className="workflows-button workflows-button-secondary" disabled={busy} onClick={() =>
              void run(() => workflowApi.pause(detail.id), "Workflow paused.")}>
              Pause
            </button>
          ) : null}
          {detail.status === "paused" ? (
            <button type="button" className="workflows-button workflows-button-secondary" disabled={busy} onClick={() =>
              void run(() => workflowApi.resume(detail.id), "Workflow resumed.")}>
              Resume
            </button>
          ) : null}
          {detail.status !== "archived" ? (
            <button type="button" className="workflows-button workflows-button-secondary" disabled={busy} onClick={() =>
              void run(() => workflowApi.archive(detail.id), "Workflow archived.")}>
              Archive
            </button>
          ) : null}
        </div>

        <h3>Version history</h3>
        {versions.length === 0 ? <p className="workflows-subtle">Nothing has been published yet.</p> : (
          <ul className="workflows-list">
            {versions.map((version) => (
              <li key={version.id} className="workflows-version">
                <span>
                  Version {version.version_number}
                  {detail.current_version?.id === version.id ? " (current)" : ""} · needs {version.required_permissions.join(", ") || "no permissions"}
                </span>
                {detail.current_version?.id !== version.id ? (
                  <button type="button" className="workflows-link" disabled={busy} onClick={() =>
                    void run(() => workflowApi.rollback(detail.id, version.version_number), `Rolled back to version ${version.version_number}.`)}>
                    Make current
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}

        <h3>Lifecycle history</h3>
        <ol className="workflows-history">
          {history.map((event, index) => (
            <li key={`${event.created_at ?? index}-${index}`}>
              {event.action}: {event.from_status ?? "new"} to {event.to_status}
              {event.created_at ? ` · ${new Date(event.created_at).toLocaleString()}` : ""}
            </li>
          ))}
        </ol>
      </section>

      <WorkflowRunsPanel workflowId={detail.id} canStart={detail.status === "published"} />
    </main>
  );
}

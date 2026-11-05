import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { ApiError } from "../lib/api";
import {
  agentApi,
  type Agent,
  type AgentExecution,
  type AgentExecutionMetrics,
  type AgentTemplateSummary,
  type AgentVersion,
  type ApprovedTool,
  type PreviewResult,
} from "../services/agentApi";
import {
  CATEGORY_OPTIONS,
  LANGUAGE_OPTIONS,
  LIMIT_FIELDS,
  buildAgentInput,
  canCancel,
  describeFailure,
  emptyForm,
  formFromConfiguration,
  statusTone,
  type AgentForm,
} from "./agentPageHelpers";

import "./AgentsPage.css";

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.details as { detail?: { reason?: string; problems?: string[] } | string } | undefined;
    const inner = detail?.detail;
    if (inner && typeof inner === "object") {
      const problems = inner.problems?.length ? ` ${inner.problems.join(" ")}` : "";
      return `${inner.reason ?? "The request was refused."}${problems}`;
    }
    if (typeof inner === "string") {
      return inner;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

function newIdempotencyKey(): string {
  return `agent-ui-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tools, setTools] = useState<ApprovedTool[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<AgentForm>(emptyForm());
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [executions, setExecutions] = useState<AgentExecution[]>([]);
  const [templates, setTemplates] = useState<AgentTemplateSummary[]>([]);
  const [templateKey, setTemplateKey] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [metrics, setMetrics] = useState<AgentExecutionMetrics | null>(null);
  const [activeExecution, setActiveExecution] = useState<AgentExecution | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [runInputs, setRunInputs] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const selected = useMemo(() => agents.find((agent) => agent.id === selectedId) ?? null, [agents, selectedId]);

  const loadAgents = useCallback(async () => {
    try {
      const [list, toolCatalogue, templateList] = await Promise.all([agentApi.list(), agentApi.tools(), agentApi.templates()]);
      setAgents(list.items);
      setTools(toolCatalogue.items);
      setTemplates(templateList.items);
      setTemplateKey((current) => current || templateList.items[0]?.key || "");
      setLoadError(null);
    } catch (caught) {
      setLoadError(messageFor(caught));
    }
  }, []);

  const loadAgentDetail = useCallback(async (agentId: string) => {
    try {
      const [versionList, executionList, metricsResult] = await Promise.all([
        agentApi.versions(agentId),
        agentApi.executions(agentId),
        agentApi.metrics(agentId),
      ]);
      setVersions(versionList.items);
      setExecutions(executionList.items);
      setMetrics(metricsResult);
    } catch (caught) {
      setError(messageFor(caught));
    }
  }, []);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  async function createFromTemplate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const template = templates.find((item) => item.key === templateKey);
    if (!template || !templateName.trim()) {
      return;
    }
    setError(null);
    setNotice(null);
    try {
      const created = await agentApi.createFromTemplate({ template_key: template.key, name: templateName.trim() });
      setTemplateName("");
      setNotice(`Draft "${created.name}" created from ${template.title}. Review it, then publish it before it can run.`);
      await loadAgents();
      selectAgent(created);
    } catch (caught) {
      setError(messageFor(caught));
    }
  }

  function selectAgent(agent: Agent) {
    setSelectedId(agent.id);
    setForm(formFromConfiguration(agent.name, agent.description, agent.draft_configuration));
    setPreview(null);
    setActiveExecution(null);
    void loadAgentDetail(agent.id);
  }

  function startNew() {
    setSelectedId(null);
    setVersions([]);
    setExecutions([]);
    setActiveExecution(null);
    setForm(emptyForm());
    setPreview(null);
    setNotice(null);
    setError(null);
  }

  async function runAction(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      await loadAgents();
      if (selectedId) {
        await loadAgentDetail(selectedId);
      }
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    let input;
    try {
      input = buildAgentInput(form);
    } catch (caught) {
      setError(messageFor(caught));
      return;
    }
    await runAction(async () => {
      if (selected) {
        const updated = await agentApi.update(selected.id, input);
        setSelectedId(updated.id);
      } else {
        const created = await agentApi.create(input);
        setSelectedId(created.id);
      }
    }, "Draft saved. The published version is unchanged until you publish.");
  }

  async function runPreview() {
    if (!selected) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setPreview(await agentApi.preview(selected.id));
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  }

  async function startRun() {
    if (!selected) {
      return;
    }
    const inputs = selected.draft_configuration.inputs ?? [];
    const payload: Record<string, unknown> = {};
    for (const spec of inputs) {
      const value = runInputs[spec.name] ?? "";
      if (value === "") {
        if (spec.required) {
          setError(`Input ${spec.name} is required.`);
          return;
        }
        continue;
      }
      payload[spec.name] = spec.type === "integer" ? Number(value) : value;
    }
    setBusy(true);
    setError(null);
    try {
      const execution = await agentApi.startExecution(selected.id, payload, newIdempotencyKey());
      setActiveExecution(execution);
      setActiveExecution(await agentApi.execution(execution.id));
      setNotice("Run queued. It will start when the worker picks it up.");
      await loadAgentDetail(selected.id);
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  }

  async function openExecution(executionId: string) {
    try {
      setActiveExecution(await agentApi.execution(executionId));
    } catch (caught) {
      setError(messageFor(caught));
    }
  }

  const waitingStep = activeExecution?.steps?.find((step) => step.status === "waiting");

  return (
    <main className="agents-page">
      <header className="agents-header">
        <div>
          <h1>Agents</h1>
          <p className="agents-subtle">
            Agents follow a fixed plan of approved tool, knowledge and model steps. Each run shows the status of every step.
          </p>
        </div>
        <button type="button" className="agents-button" onClick={startNew}>
          New agent
        </button>
      </header>

      {loadError ? (
        <p role="alert" className="agents-alert">
          {loadError}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="agents-alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="agents-notice">
          {notice}
        </p>
      ) : null}

      <div className="agents-layout">
        <section aria-labelledby="agents-list-title" className="agents-panel">
          <h2 id="agents-list-title">Your agents</h2>
          {agents.length === 0 ? <p className="agents-subtle">No agents yet.</p> : null}
          <ul className="agents-list">
            {agents.map((agent) => (
              <li key={agent.id}>
                <button
                  type="button"
                  className={agent.id === selectedId ? "agents-list-item agents-list-item-active" : "agents-list-item"}
                  onClick={() => selectAgent(agent)}
                  aria-current={agent.id === selectedId ? "true" : undefined}
                >
                  <span>{agent.name}</span>
                  <span className={`agents-badge agents-badge-${statusTone(agent.status)}`}>{agent.status}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="template-title" className="agents-panel">
          <h2 id="template-title">Start from a template</h2>
          <form onSubmit={createFromTemplate} className="agents-form">
            <label>
              Template
              <select value={templateKey} onChange={(event) => setTemplateKey(event.target.value)}>
                {templates.map((template) => (
                  <option key={template.key} value={template.key}>
                    {template.title}
                  </option>
                ))}
              </select>
            </label>
            <p className="agents-subtle">{templates.find((item) => item.key === templateKey)?.purpose}</p>
            <label>
              Draft name
              <input value={templateName} onChange={(event) => setTemplateName(event.target.value)} maxLength={120} required />
            </label>
            <button type="submit" className="agents-button" disabled={!templateKey}>
              Create draft
            </button>
          </form>
        </section>

        <section aria-labelledby="agent-form-title" className="agents-panel agents-panel-wide">
          <h2 id="agent-form-title">{selected ? `Edit ${selected.name}` : "Create an agent"}</h2>
          <form onSubmit={saveDraft} className="agents-form">
            <label>
              Name
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            </label>
            <label>
              Description
              <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </label>
            <label>
              Category
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                {CATEGORY_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Language
              <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
                {LANGUAGE_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="agents-span">
              Purpose
              <input value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} />
            </label>
            <label className="agents-span">
              Instructions
              <textarea rows={3} value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
            </label>

            <fieldset className="agents-span">
              <legend>Approved tools</legend>
              {tools.map((tool) => (
                <label key={tool.key} className="agents-check">
                  <input
                    type="checkbox"
                    checked={form.tools.includes(tool.key)}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        tools: e.target.checked ? [...form.tools, tool.key] : form.tools.filter((k) => k !== tool.key),
                      })
                    }
                  />
                  <span>
                    <code>{tool.key}</code> {tool.description}
                  </span>
                </label>
              ))}
            </fieldset>

            <label className="agents-span">
              Knowledge sources (document identifiers)
              <input value={form.knowledgeIds} onChange={(e) => setForm({ ...form, knowledgeIds: e.target.value })} />
            </label>
            <label className="agents-span">
              Inputs (JSON array of name, type and required)
              <textarea rows={3} value={form.inputsJson} onChange={(e) => setForm({ ...form, inputsJson: e.target.value })} />
            </label>
            <label className="agents-span">
              Plan (JSON array of steps)
              <textarea rows={6} value={form.stepsJson} onChange={(e) => setForm({ ...form, stepsJson: e.target.value })} />
            </label>

            <label>
              Autonomy
              <select
                value={form.autonomyLevel}
                onChange={(e) => setForm({ ...form, autonomyLevel: e.target.value as AgentForm["autonomyLevel"] })}
              >
                <option value="suggest">Suggest (needs a review step)</option>
                <option value="act">Act</option>
              </select>
            </label>
            <label>
              Approval before result
              <select
                value={form.approvalPolicy}
                onChange={(e) => setForm({ ...form, approvalPolicy: e.target.value as AgentForm["approvalPolicy"] })}
              >
                <option value="before_result">Required</option>
                <option value="none">Not required</option>
              </select>
            </label>

            {LIMIT_FIELDS.map((field) => (
              <label key={field.key}>
                {field.label}
                <input
                  type="number"
                  min={field.min}
                  max={field.max}
                  value={form.limits[field.key]}
                  onChange={(e) => setForm({ ...form, limits: { ...form.limits, [field.key]: e.target.value } })}
                />
              </label>
            ))}

            <div className="agents-actions agents-span">
              <button type="submit" className="agents-button" disabled={busy}>
                Save draft
              </button>
              {selected ? (
                <>
                  <button type="button" className="agents-button-secondary" onClick={runPreview} disabled={busy}>
                    Preview draft
                  </button>
                  <button
                    type="button"
                    className="agents-button"
                    disabled={busy || selected.status === "archived"}
                    onClick={() => runAction(() => agentApi.publish(selected.id), "Version published.")}
                  >
                    Publish
                  </button>
                  {selected.status === "paused" ? (
                    <button
                      type="button"
                      className="agents-button-secondary"
                      disabled={busy}
                      onClick={() => runAction(() => agentApi.resume(selected.id), "Agent resumed.")}
                    >
                      Resume
                    </button>
                  ) : selected.status === "published" ? (
                    <button
                      type="button"
                      className="agents-button-secondary"
                      disabled={busy}
                      onClick={() => runAction(() => agentApi.pause(selected.id), "Agent paused. No new runs will start.")}
                    >
                      Pause
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="agents-button-danger"
                    disabled={busy || selected.status === "archived"}
                    onClick={() => runAction(() => agentApi.archive(selected.id), "Agent archived.")}
                  >
                    Archive
                  </button>
                </>
              ) : null}
            </div>
          </form>

          {preview ? (
            <div className="agents-preview" aria-live="polite">
              <h3>Preview</h3>
              <p>{preview.publishable ? "This draft could be published now." : "This draft cannot be published yet."}</p>
              {preview.problems.length ? (
                <ul>
                  {preview.problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              ) : null}
              <p className="agents-subtle">No tool, model or provider was called to produce this preview.</p>
            </div>
          ) : null}
        </section>
      </div>

      {selected ? (
        <div className="agents-layout">
          {metrics ? (
            <section aria-labelledby="metrics-title" className="agents-panel">
              <h2 id="metrics-title">Execution metrics</h2>
              <p className="agents-subtle">
                {metrics.total} run(s). {Object.entries(metrics.by_status).map(([status, count]) => `${status}: ${count}`).join(", ") || "No runs yet."}
              </p>
              {metrics.failure_reasons.length > 0 ? (
                <ul className="agents-list">
                  {metrics.failure_reasons.map((item) => (
                    <li key={item.reason}>
                      {item.reason}: {item.count}
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          ) : null}

          <section aria-labelledby="versions-title" className="agents-panel">
            <h2 id="versions-title">Version history</h2>
            {versions.length === 0 ? <p className="agents-subtle">Nothing has been published yet.</p> : null}
            <ul className="agents-list">
              {versions.map((version) => (
                <li key={version.id} className="agents-version-row">
                  <span>
                    Version {version.version_number}
                    {selected.current_version_number === version.version_number ? " (current)" : ""}
                  </span>
                  {selected.current_version_number !== version.version_number ? (
                    <button
                      type="button"
                      className="agents-button-secondary"
                      disabled={busy}
                      onClick={() =>
                        runAction(() => agentApi.rollback(selected.id, version.version_number), `Rolled back to version ${version.version_number}.`)
                      }
                    >
                      Roll back to this version
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="run-title" className="agents-panel">
            <h2 id="run-title">Run this agent</h2>
            <p className="agents-subtle">Runs use the current published version. Nothing runs until you start one.</p>
            {(selected.draft_configuration.inputs ?? []).map((spec) => (
              <label key={spec.name}>
                {spec.name}
                {spec.required ? " (required)" : ""}
                <input
                  value={runInputs[spec.name] ?? ""}
                  onChange={(e) => setRunInputs({ ...runInputs, [spec.name]: e.target.value })}
                  placeholder={spec.type === "uuid" ? "Identifier" : spec.type}
                />
              </label>
            ))}
            <button type="button" className="agents-button" disabled={busy || selected.status !== "published"} onClick={startRun}>
              Start run
            </button>
            {selected.status !== "published" ? (
              <p className="agents-subtle">Publish the agent before starting a run.</p>
            ) : null}

            <h3>Recent runs</h3>
            <ul className="agents-list">
              {executions.map((execution) => (
                <li key={execution.id}>
                  <button type="button" className="agents-list-item" onClick={() => openExecution(execution.id)}>
                    <span>{new Date(execution.created_at).toLocaleString()}</span>
                    <span className={`agents-badge agents-badge-${statusTone(execution.status)}`}>{execution.status}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>
      ) : null}

      {activeExecution ? (
        <section aria-labelledby="execution-title" className="agents-panel agents-execution">
          <h2 id="execution-title">Run {activeExecution.id.slice(0, 8)}</h2>
          <p>
            Status: <span className={`agents-badge agents-badge-${statusTone(activeExecution.status)}`}>{activeExecution.status}</span>
          </p>
          {activeExecution.failure_reason ? (
            <p role="alert" className="agents-alert">
              {describeFailure(activeExecution.failure_reason)}
            </p>
          ) : null}
          {activeExecution.status === "timed_out" ? (
            <p role="alert" className="agents-alert">
              The run passed its deadline. No further steps ran.
            </p>
          ) : null}
          <p className="agents-subtle">
            Tool calls {activeExecution.tool_calls} · Model calls {activeExecution.model_calls} · Steps completed{" "}
            {activeExecution.steps_completed}
          </p>

          {activeExecution.steps && activeExecution.steps.length > 0 ? (
            <table className="agents-table">
              <caption>Steps</caption>
              <thead>
                <tr>
                  <th scope="col">Step</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Status</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Attempts</th>
                </tr>
              </thead>
              <tbody>
                {activeExecution.steps.map((step) => (
                  <tr key={step.index}>
                    <td>{step.index + 1}</td>
                    <td>{step.kind}</td>
                    <td>{step.status}</td>
                    <td>{step.reason_code ?? "—"}</td>
                    <td>{step.attempts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="agents-subtle">No steps have run yet.</p>
          )}

          {activeExecution.output ? (
            <pre className="agents-output" aria-label="Result">
              {JSON.stringify(activeExecution.output, null, 2)}
            </pre>
          ) : null}

          <div className="agents-actions">
            {canCancel(activeExecution.status) ? (
              <button
                type="button"
                className="agents-button-secondary"
                disabled={busy}
                onClick={() =>
                  runAction(async () => {
                    await agentApi.cancelExecution(activeExecution.id);
                    await openExecution(activeExecution.id);
                  }, "Cancellation requested.")
                }
              >
                Cancel run
              </button>
            ) : null}
            {activeExecution.status === "waiting_approval" && waitingStep ? (
              <>
                <button
                  type="button"
                  className="agents-button"
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      await agentApi.decideApproval(activeExecution.id, waitingStep.index, true);
                      await openExecution(activeExecution.id);
                    }, "Approved. The run will continue.")
                  }
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="agents-button-danger"
                  disabled={busy}
                  onClick={() =>
                    runAction(async () => {
                      await agentApi.decideApproval(activeExecution.id, waitingStep.index, false);
                      await openExecution(activeExecution.id);
                    }, "Rejected. The run has stopped.")
                  }
                >
                  Reject
                </button>
              </>
            ) : null}
          </div>
        </section>
      ) : null}
    </main>
  );
}

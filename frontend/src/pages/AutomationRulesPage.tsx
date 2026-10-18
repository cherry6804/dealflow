
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";

import {
  automationRulesApi,
  type AutomationRule,
  type AutomationRuleInput,
  type AutomationRuleStatus,
} from "../services/automationRuleApi";

import "./AutomationRulesPage.css";

const PAGE_SIZE = 10;

const DEFAULT_ACTIONS: Array<Record<string, unknown>> = [
  {
    type: "CREATE_FOLLOW_UP",
    config: {
      days_after: 1,
    },
  },
];

function createEmptyInput(): AutomationRuleInput {
  return {
    name: "",
    description: "",
    trigger_type: "DEAL_CREATED",
    trigger_config: {},
    conditions: [],
    actions: DEFAULT_ACTIONS,
  };
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function statusLabel(status: AutomationRuleStatus): string {
  switch (status) {
    case "DRAFT":
      return "Draft";
    case "ACTIVE":
      return "Active";
    case "DISABLED":
      return "Disabled";
  }
}

function parseJsonObject(
  value: string,
  fieldName: string,
): Record<string, unknown> {
  let parsed: unknown;

  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${fieldName} must contain valid JSON.`);
  }

  if (
    parsed === null ||
    typeof parsed !== "object" ||
    Array.isArray(parsed)
  ) {
    throw new Error(`${fieldName} must be a JSON object.`);
  }

  return parsed as Record<string, unknown>;
}

function parseJsonArray(
  value: string,
  fieldName: string,
): Array<Record<string, unknown>> {
  let parsed: unknown;

  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${fieldName} must contain valid JSON.`);
  }

  if (
    !Array.isArray(parsed) ||
    parsed.some(
      (item) =>
        item === null ||
        typeof item !== "object" ||
        Array.isArray(item),
    )
  ) {
    throw new Error(
      `${fieldName} must be a JSON array of objects.`,
    );
  }

  return parsed as Array<Record<string, unknown>>;
}

export default function AutomationRulesPage() {
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [statusFilter, setStatusFilter] = useState<
    "" | AutomationRuleStatus
  >("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyRuleId, setBusyRuleId] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingRule, setEditingRule] = useState<AutomationRule | null>(
    null,
  );

  const [form, setForm] = useState<AutomationRuleInput>(
    createEmptyInput,
  );

  const [triggerConfigText, setTriggerConfigText] = useState("{}");
  const [conditionsText, setConditionsText] = useState("[]");
  const [actionsText, setActionsText] = useState(
    JSON.stringify(DEFAULT_ACTIONS, null, 2),
  );

  const modalRef = useRef<HTMLElement>(null);

  const loadRules = useCallback(
    async (
      targetPage: number,
      targetStatus: "" | AutomationRuleStatus,
    ) => {
      setLoading(true);
      setError(null);

      try {
        const response = await automationRulesApi.list({
          page: targetPage,
          page_size: PAGE_SIZE,
          ...(targetStatus ? { status: targetStatus } : {}),
        });

        setRules(response.items);
        setTotal(response.total);
        setTotalPages(Math.max(1, response.total_pages));
        setPage(response.page);
      } catch (cause) {
        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to load automation rules.",
        );
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void loadRules(page, statusFilter);
  }, [loadRules, page, statusFilter]);

  // Modal behavior: lock background scrolling, focus the first field,
  // and close with Escape when no save operation is in progress.
  useEffect(() => {
    if (!editorOpen) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const timer = window.setTimeout(() => {
      modalRef.current
        ?.querySelector<HTMLInputElement | HTMLTextAreaElement>(
          "input:not(:disabled), textarea:not(:disabled)",
        )
        ?.focus();
    }, 50);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) {
        setEditorOpen(false);
        setEditingRule(null);
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(timer);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [editorOpen, saving]);

  const summary = useMemo(
    () => ({
      active: rules.filter((rule) => rule.status === "ACTIVE").length,
      drafts: rules.filter((rule) => rule.status === "DRAFT").length,
      disabled: rules.filter((rule) => rule.status === "DISABLED").length,
    }),
    [rules],
  );

  function openCreateEditor() {
    setEditingRule(null);
    setForm(createEmptyInput());
    setTriggerConfigText("{}");
    setConditionsText("[]");
    setActionsText(JSON.stringify(DEFAULT_ACTIONS, null, 2));
    setError(null);
    setNotice(null);
    setEditorOpen(true);
  }

  function openEditEditor(rule: AutomationRule) {
    setEditingRule(rule);

    setForm({
      name: rule.name,
      description: rule.description ?? "",
      trigger_type: rule.trigger_type,
      trigger_config: rule.trigger_config,
      conditions: rule.conditions,
      actions: rule.actions,
    });

    setTriggerConfigText(
      JSON.stringify(rule.trigger_config, null, 2),
    );
    setConditionsText(JSON.stringify(rule.conditions, null, 2));
    setActionsText(JSON.stringify(rule.actions, null, 2));

    setError(null);
    setNotice(null);
    setEditorOpen(true);
  }

  function closeEditor() {
    if (saving) {
      return;
    }

    setEditorOpen(false);
    setEditingRule(null);
  }

  function handleBackdropClick(
    event: MouseEvent<HTMLDivElement>,
  ) {
    if (event.target === event.currentTarget) {
      closeEditor();
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);

    const name = form.name.trim();
    const triggerType = form.trigger_type.trim();

    if (!name) {
      setError("Enter a name for this automation rule.");
      return;
    }

    if (!triggerType) {
      setError("Enter a trigger type.");
      return;
    }

    let input: AutomationRuleInput;

    try {
      input = {
        name,
        description: form.description?.trim() || null,
        trigger_type: triggerType,
        trigger_config: parseJsonObject(
          triggerConfigText,
          "Trigger configuration",
        ),
        conditions: parseJsonArray(
          conditionsText,
          "Conditions",
        ),
        actions: parseJsonArray(actionsText, "Actions"),
      };
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Check the JSON configuration fields.",
      );
      return;
    }

    setSaving(true);

    try {
      if (editingRule) {
        await automationRulesApi.update(editingRule.id, input);
        setNotice("Automation rule updated successfully.");
      } else {
        await automationRulesApi.create(input);
        setNotice("Automation rule saved as a draft.");
      }

      setEditorOpen(false);
      setEditingRule(null);
      setPage(1);

      await loadRules(1, statusFilter);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Unable to save the automation rule.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleLifecycle(
    rule: AutomationRule,
    action: "activate" | "disable",
  ) {
    const verb = action === "activate" ? "activate" : "disable";

    if (
      !window.confirm(
        `Are you sure you want to ${verb} "${rule.name}"?`,
      )
    ) {
      return;
    }

    setBusyRuleId(rule.id);
    setError(null);
    setNotice(null);

    try {
      if (action === "activate") {
        await automationRulesApi.activate(rule.id);
        setNotice(`"${rule.name}" is now active.`);
      } else {
        await automationRulesApi.disable(rule.id);
        setNotice(`"${rule.name}" has been disabled.`);
      }

      await loadRules(page, statusFilter);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : `Unable to ${verb} this rule.`,
      );
    } finally {
      setBusyRuleId(null);
    }
  }

  function handleStatusFilterChange(
    value: "" | AutomationRuleStatus,
  ) {
    setStatusFilter(value);
    setPage(1);
  }

  const editorModal = editorOpen
    ? createPortal(
        <div
          className="automation-modal-backdrop"
          onMouseDown={handleBackdropClick}
        >
          <section
            ref={modalRef}
            className="automation-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="automation-editor-title"
          >
            <header className="automation-modal-header">
              <div>
                <span className="automation-eyebrow">
                  {editingRule ? "EDIT CONFIGURATION" : "NEW WORKFLOW"}
                </span>

                <h2 id="automation-editor-title">
                  {editingRule
                    ? "Edit automation rule"
                    : "Create automation rule"}
                </h2>

                <p>
                  Configure the trigger, conditions and actions for
                  this workflow.
                </p>
              </div>

              <button
                className="automation-modal-close"
                type="button"
                aria-label="Close dialog"
                disabled={saving}
                onClick={closeEditor}
              >
                ×
              </button>
            </header>

            {editingRule?.status === "ACTIVE" && (
              <div className="automation-inline-note">
                Active rules cannot be edited. Disable this rule before
                changing its configuration.
              </div>
            )}

            <form
              className="automation-modal-form"
              onSubmit={handleSubmit}
            >
              <div className="automation-modal-body">
                {error && (
                  <div
                    className="automation-alert automation-alert-error automation-form-error"
                    role="alert"
                  >
                    <span aria-hidden="true">!</span>
                    <p>{error}</p>
                  </div>
                )}

                <h3 className="automation-form-section-title">
                  Rule details
                </h3>

                <div className="automation-form-grid">
                  <label className="automation-field">
                    Rule name <span className="required">*</span>

                    <input
                      value={form.name}
                      maxLength={150}
                      required
                      disabled={
                        saving || editingRule?.status === "ACTIVE"
                      }
                      placeholder="e.g. Follow up on new deals"
                      onChange={(event) =>
                        setForm({
                          ...form,
                          name: event.target.value,
                        })
                      }
                    />
                  </label>

                  <label className="automation-field">
                    Trigger type <span className="required">*</span>

                    <input
                      value={form.trigger_type}
                      maxLength={100}
                      required
                      disabled={
                        saving || editingRule?.status === "ACTIVE"
                      }
                      placeholder="e.g. DEAL_CREATED"
                      onChange={(event) =>
                        setForm({
                          ...form,
                          trigger_type: event.target.value,
                        })
                      }
                    />

                    <small>
                      Use a trigger identifier supported by your
                      automation implementation.
                    </small>
                  </label>

                  <label className="automation-field automation-field-full">
                    Description

                    <textarea
                      value={form.description ?? ""}
                      maxLength={20000}
                      rows={3}
                      disabled={
                        saving || editingRule?.status === "ACTIVE"
                      }
                      placeholder="Describe the purpose of this rule."
                      onChange={(event) =>
                        setForm({
                          ...form,
                          description: event.target.value,
                        })
                      }
                    />
                  </label>
                </div>

                <h3 className="automation-form-section-title">
                  Trigger configuration
                </h3>

                <div className="automation-form-grid">
                  <label className="automation-field automation-field-full">
                    Trigger configuration JSON

                    <textarea
                      className="automation-code-field"
                      value={triggerConfigText}
                      rows={5}
                      spellCheck={false}
                      disabled={
                        saving || editingRule?.status === "ACTIVE"
                      }
                      onChange={(event) =>
                        setTriggerConfigText(event.target.value)
                      }
                    />

                    <small>
                      Enter a valid JSON object, for example {"{}"}.
                    </small>
                  </label>
                </div>

                <h3 className="automation-form-section-title">
                  Conditions and actions
                </h3>

                <div className="automation-form-grid">
                  <label className="automation-field automation-field-full">
                    Conditions JSON

                    <textarea
                      className="automation-code-field"
                      value={conditionsText}
                      rows={5}
                      spellCheck={false}
                      disabled={
                        saving || editingRule?.status === "ACTIVE"
                      }
                      onChange={(event) =>
                        setConditionsText(event.target.value)
                      }
                    />

                    <small>
                      Enter an array of condition objects. Use [] if
                      there are no conditions.
                    </small>
                  </label>

                  <label className="automation-field automation-field-full">
                    Actions JSON <span className="required">*</span>

                    <textarea
                      className="automation-code-field"
                      value={actionsText}
                      rows={7}
                      spellCheck={false}
                      disabled={
                        saving || editingRule?.status === "ACTIVE"
                      }
                      onChange={(event) =>
                        setActionsText(event.target.value)
                      }
                    />

                    <small>
                      Activation requires at least one action. Action
                      configuration must match the supported backend
                      contract.
                    </small>
                  </label>
                </div>

                <p className="automation-modal-help">
                  New rules are saved as drafts. Review the configuration
                  before activating a rule.
                </p>
              </div>

              <footer className="automation-modal-actions">
                <button
                  className="automation-secondary-button"
                  type="button"
                  disabled={saving}
                  onClick={closeEditor}
                >
                  Cancel
                </button>

                <button
                  className="automation-primary-button"
                  type="submit"
                  disabled={
                    saving || editingRule?.status === "ACTIVE"
                  }
                >
                  {saving
                    ? "Saving…"
                    : editingRule
                      ? "Save changes"
                      : "Save as draft"}
                </button>
              </footer>
            </form>
          </section>
        </div>,
        document.body,
      )
    : null;

  return (
    <div className="automation-page">
      <header className="automation-header">
        <div>
          <span className="automation-eyebrow">
            WORKFLOW MANAGEMENT
          </span>

          <h1>Automation rules</h1>

          <p className="automation-subtitle">
            Manage repeatable rules for your DealFlow workspace.
          </p>
        </div>

        <button
          className="automation-primary-button"
          type="button"
          onClick={openCreateEditor}
        >
          <span aria-hidden="true">＋</span>
          Create rule
        </button>
      </header>

      {notice && (
        <div
          className="automation-alert automation-alert-success"
          role="status"
        >
          <span aria-hidden="true">✓</span>
          <p>{notice}</p>
          <button
            type="button"
            aria-label="Dismiss notification"
            onClick={() => setNotice(null)}
          >
            ×
          </button>
        </div>
      )}

      {error && !editorOpen && (
        <div
          className="automation-alert automation-alert-error"
          role="alert"
        >
          <span aria-hidden="true">!</span>
          <p>{error}</p>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setError(null)}
          >
            ×
          </button>
        </div>
      )}

      <section
        className="automation-summary-grid"
        aria-label="Automation rule summary"
      >
        <article className="automation-summary-card">
          <span className="automation-summary-icon">≡</span>
          <div>
            <span className="automation-summary-label">
              Rules on this page
            </span>
            <strong>{rules.length}</strong>
          </div>
        </article>

        <article className="automation-summary-card">
          <span className="automation-summary-icon active-icon">●</span>
          <div>
            <span className="automation-summary-label">
              Active on this page
            </span>
            <strong>{summary.active}</strong>
          </div>
        </article>

        <article className="automation-summary-card">
          <span className="automation-summary-icon draft-icon">◷</span>
          <div>
            <span className="automation-summary-label">
              Drafts on this page
            </span>
            <strong>{summary.drafts}</strong>
          </div>
        </article>
      </section>

      <section className="automation-list-panel">
        <div className="automation-list-heading">
          <div>
            <h2>Your rules</h2>
            <p>
              {total} {total === 1 ? "rule" : "rules"} in this workspace
            </p>
          </div>

          <div className="automation-filter">
            <label htmlFor="automation-status-filter">Status</label>

            <select
              id="automation-status-filter"
              value={statusFilter}
              onChange={(event) =>
                handleStatusFilterChange(
                  event.target.value as "" | AutomationRuleStatus,
                )
              }
            >
              <option value="">All statuses</option>
              <option value="DRAFT">Draft</option>
              <option value="ACTIVE">Active</option>
              <option value="DISABLED">Disabled</option>
            </select>

            <button
              className="automation-secondary-button"
              type="button"
              disabled={loading}
              onClick={() => void loadRules(page, statusFilter)}
            >
              {loading ? "Refreshing…" : "↻ Refresh"}
            </button>
          </div>
        </div>

        {loading ? (
          <div className="automation-state" aria-live="polite">
            <span className="automation-spinner" />
            <strong>Loading automation rules…</strong>
            <p>Retrieving rules for your workspace.</p>
          </div>
        ) : rules.length === 0 ? (
          <div className="automation-state">
            <span className="automation-empty-icon" aria-hidden="true">
              ◇
            </span>

            <h3>No automation rules found</h3>

            <p>
              {statusFilter
                ? "Try another status filter or create a new rule."
                : "Create your first rule to define a repeatable workflow."}
            </p>

            <button
              className="automation-primary-button"
              type="button"
              onClick={openCreateEditor}
            >
              Create your first rule
            </button>
          </div>
        ) : (
          <>
            <div className="automation-table-wrap">
              <table className="automation-table">
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Trigger</th>
                    <th>Actions</th>
                    <th>Status</th>
                    <th>Last updated</th>
                    <th>
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>

                <tbody>
                  {rules.map((rule) => (
                    <tr key={rule.id}>
                      <td>
                        <div className="automation-rule-name">
                          {rule.name}
                        </div>

                        <div className="automation-rule-description">
                          {rule.description || "No description provided"}
                        </div>
                      </td>

                      <td>
                        <code className="automation-trigger">
                          {rule.trigger_type}
                        </code>
                      </td>

                      <td>
                        {rule.actions.length}{" "}
                        {rule.actions.length === 1 ? "action" : "actions"}
                      </td>

                      <td>
                        <span
                          className={`automation-status status-${rule.status.toLowerCase()}`}
                        >
                          {statusLabel(rule.status)}
                        </span>
                      </td>

                      <td className="automation-date">
                        {formatDate(rule.updated_at)}
                      </td>

                      <td>
                        <div className="automation-row-actions">
                          {rule.status !== "ACTIVE" && (
                            <button
                              className="automation-text-button"
                              type="button"
                              onClick={() => openEditEditor(rule)}
                            >
                              Edit
                            </button>
                          )}

                          {rule.status !== "ACTIVE" && (
                            <button
                              className="automation-text-button"
                              type="button"
                              disabled={busyRuleId === rule.id}
                              onClick={() =>
                                void handleLifecycle(rule, "activate")
                              }
                            >
                              {busyRuleId === rule.id
                                ? "Working…"
                                : "Activate"}
                            </button>
                          )}

                          {rule.status === "ACTIVE" && (
                            <button
                              className="automation-text-button danger-text"
                              type="button"
                              disabled={busyRuleId === rule.id}
                              onClick={() =>
                                void handleLifecycle(rule, "disable")
                              }
                            >
                              {busyRuleId === rule.id
                                ? "Working…"
                                : "Disable"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="automation-pagination">
              <span>
                Page {page} of {totalPages}
              </span>

              <div>
                <button
                  className="automation-secondary-button"
                  type="button"
                  disabled={page <= 1 || loading}
                  onClick={() =>
                    setPage((current) => Math.max(1, current - 1))
                  }
                >
                  Previous
                </button>

                <button
                  className="automation-secondary-button"
                  type="button"
                  disabled={page >= totalPages || loading}
                  onClick={() =>
                    setPage((current) =>
                      Math.min(totalPages, current + 1),
                    )
                  }
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </section>

      {editorModal}
    </div>
  );
}

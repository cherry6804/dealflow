
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

const FOLLOW_UP_TYPES = [
  { value: "CALL", label: "Phone call" },
  { value: "EMAIL", label: "Email" },
  { value: "MEETING", label: "Meeting" },
  { value: "VISIT", label: "Property visit" },
  { value: "TASK", label: "Task" },
  { value: "OTHER", label: "Other" },
] as const;

const CONDITION_FIELDS = [
  { value: "stage", label: "Deal stage" },
  { value: "expected_value", label: "Expected deal value" },
  { value: "currency", label: "Currency" },
  { value: "owner_user_id", label: "Deal owner ID" },
  { value: "lead_id", label: "Lead ID" },
  { value: "customer_profile_id", label: "Customer profile ID" },
  { value: "property_id", label: "Property ID" },
  { value: "notes", label: "Deal notes" },
] as const;

const CONDITION_OPERATORS = [
  { value: "equals", label: "Equals" },
  { value: "not_equals", label: "Does not equal" },
  { value: "in", label: "Is one of" },
  { value: "not_in", label: "Is not one of" },
  { value: "exists", label: "Has a value" },
] as const;

type ConditionField = (typeof CONDITION_FIELDS)[number]["value"];
type ConditionOperator =
  (typeof CONDITION_OPERATORS)[number]["value"];

interface AutomationForm {
  name: string;
  description: string;
  triggerSource: "deals";
  useCondition: boolean;
  conditionField: ConditionField;
  conditionOperator: ConditionOperator;
  conditionValue: string;
  conditionExists: boolean;
  daysAfter: string;
  followUpTitle: string;
  followUpDescription: string;
  followUpType: string;
}

interface RuleEditorData {
  form: AutomationForm;
  extraConditions: Array<Record<string, unknown>>;
  extraActions: Array<Record<string, unknown>>;
}

function createEmptyForm(): AutomationForm {
  return {
    name: "",
    description: "",
    triggerSource: "deals",
    useCondition: false,
    conditionField: "stage",
    conditionOperator: "equals",
    conditionValue: "NEW",
    conditionExists: true,
    daysAfter: "1",
    followUpTitle: "Contact lead about new deal",
    followUpDescription: "",
    followUpType: "CALL",
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function getString(
  record: Record<string, unknown>,
  key: string,
  fallback = "",
): string {
  const value = record[key];
  return typeof value === "string" ? value : fallback;
}

function getConditionValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }

  if (Array.isArray(value)) {
    return value.map(String).join(", ");
  }

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return String(value);
}

function getRuleEditorData(rule: AutomationRule): RuleEditorData {
  const firstCondition = isRecord(rule.conditions[0])
    ? rule.conditions[0]
    : null;

  const firstAction = isRecord(rule.actions[0])
    ? rule.actions[0]
    : null;

  const actionConfig =
    firstAction && isRecord(firstAction.config)
      ? firstAction.config
      : {};

  const rawField = firstCondition?.field;
  const conditionField = CONDITION_FIELDS.some(
    (field) => field.value === rawField,
  )
    ? (rawField as ConditionField)
    : "stage";

  const rawOperator = firstCondition?.operator;
  const conditionOperator = CONDITION_OPERATORS.some(
    (operator) => operator.value === rawOperator,
  )
    ? (rawOperator as ConditionOperator)
    : "equals";

  const rawSource = rule.trigger_config.source;

  return {
    form: {
      name: rule.name,
      description: rule.description ?? "",
      triggerSource: rawSource === "deals" ? "deals" : "deals",
      useCondition: rule.conditions.length > 0,
      conditionField,
      conditionOperator,
      conditionValue:
        firstCondition && "value" in firstCondition
          ? getConditionValue(firstCondition.value)
          : "",
      conditionExists:
        firstCondition?.value === true,
      daysAfter:
        typeof actionConfig.days_after === "number"
          ? String(actionConfig.days_after)
          : "1",
      followUpTitle: getString(
        actionConfig,
        "title",
        "Contact lead about new deal",
      ),
      followUpDescription: getString(
        actionConfig,
        "description",
      ),
      followUpType: getString(
        actionConfig,
        "follow_up_type",
        "TASK",
      ),
    },
    extraConditions: rule.conditions.slice(1),
    extraActions: rule.actions.slice(1),
  };
}

function buildCondition(
  form: AutomationForm,
): Record<string, unknown> {
  let value: unknown;

  if (form.conditionOperator === "exists") {
    value = form.conditionExists;
  } else if (
    form.conditionOperator === "in" ||
    form.conditionOperator === "not_in"
  ) {
    value = form.conditionValue
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  } else if (form.conditionField === "expected_value") {
    value = Number(form.conditionValue);
  } else {
    value = form.conditionValue.trim();
  }

  return {
    field: form.conditionField,
    operator: form.conditionOperator,
    value,
  };
}

function buildRuleInput(
  form: AutomationForm,
  extraConditions: Array<Record<string, unknown>>,
  extraActions: Array<Record<string, unknown>>,
): AutomationRuleInput {
  const daysAfter = Number(form.daysAfter);

  const conditions = form.useCondition
    ? [buildCondition(form), ...extraConditions]
    : [...extraConditions];

  const actions = [
    {
      type: "CREATE_FOLLOW_UP",
      config: {
        days_after: daysAfter,
        title: form.followUpTitle.trim(),
        description: form.followUpDescription.trim() || null,
        follow_up_type: form.followUpType,
      },
    },
    ...extraActions,
  ];

  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    trigger_type: "DEAL_CREATED",
    trigger_config: { source: form.triggerSource },
    conditions,
    actions,
  };
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
  const [form, setForm] = useState<AutomationForm>(createEmptyForm);
  const [extraConditions, setExtraConditions] = useState<
    Array<Record<string, unknown>>
  >([]);
  const [extraActions, setExtraActions] = useState<
    Array<Record<string, unknown>>
  >([]);

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
    setForm(createEmptyForm());
    setExtraConditions([]);
    setExtraActions([]);
    setError(null);
    setNotice(null);
    setEditorOpen(true);
  }

  function openEditEditor(rule: AutomationRule) {
    const data = getRuleEditorData(rule);

    setEditingRule(rule);
    setForm(data.form);
    setExtraConditions(data.extraConditions);
    setExtraActions(data.extraActions);
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

  function handleBackdropClick(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) {
      closeEditor();
    }
  }

  function updateForm<K extends keyof AutomationForm>(
    key: K,
    value: AutomationForm[K],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);

    if (!form.name.trim()) {
      setError("Enter a name for this automation rule.");
      return;
    }

    if (!form.followUpTitle.trim()) {
      setError("Enter a title for the automatic follow-up.");
      return;
    }

    if (form.followUpTitle.trim().length > 200) {
      setError("Follow-up title must be 200 characters or fewer.");
      return;
    }

    const daysAfter = Number(form.daysAfter);

    if (
      !Number.isInteger(daysAfter) ||
      daysAfter < 0 ||
      daysAfter > 3650
    ) {
      setError("Follow-up delay must be a whole number from 0 to 3650 days.");
      return;
    }

    if (
      form.useCondition &&
      form.conditionOperator !== "exists" &&
      !form.conditionValue.trim()
    ) {
      setError("Enter a value for the condition or disable the condition.");
      return;
    }

    if (
      form.useCondition &&
      ["in", "not_in"].includes(form.conditionOperator) &&
      !form.conditionValue.split(",").some((item) => item.trim())
    ) {
      setError("Enter at least one comma-separated condition value.");
      return;
    }

    if (
      form.useCondition &&
      form.conditionField === "expected_value" &&
      form.conditionOperator !== "exists" &&
      form.conditionValue.split(",").some(
        (item) => item.trim() && !Number.isFinite(Number(item.trim())),
      )
    ) {
      setError("Expected deal value must contain a valid number.");
      return;
    }

    let input: AutomationRuleInput;

    try {
      input = buildRuleInput(form, extraConditions, extraActions);
    } catch {
      setError("Check the automation rule configuration and try again.");
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

    if (!window.confirm(`Are you sure you want to ${verb} "${rule.name}"?`)) {
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
                  {editingRule ? "EDIT WORKFLOW" : "NEW WORKFLOW"}
                </span>
                <h2 id="automation-editor-title">
                  {editingRule ? "Edit automation rule" : "Create automation rule"}
                </h2>
                <p>
                  When a new deal matches your rule, automatically create a
                  follow-up for its lead.
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
                Disable this rule before changing its configuration.
              </div>
            )}

            <form className="automation-modal-form" onSubmit={handleSubmit}>
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

                <h3 className="automation-form-section-title">Rule details</h3>

                <div className="automation-form-grid">
                  <label className="automation-field automation-field-full">
                    Rule name <span className="required">*</span>
                    <input
                      value={form.name}
                      maxLength={150}
                      required
                      disabled={saving || editingRule?.status === "ACTIVE"}
                      placeholder="e.g. Follow up on new deals"
                      onChange={(event) => updateForm("name", event.target.value)}
                    />
                  </label>

                  <label className="automation-field automation-field-full">
                    Description
                    <textarea
                      value={form.description}
                      maxLength={20000}
                      rows={2}
                      disabled={saving || editingRule?.status === "ACTIVE"}
                      placeholder="What should this workflow accomplish?"
                      onChange={(event) =>
                        updateForm("description", event.target.value)
                      }
                    />
                  </label>
                </div>

                <h3 className="automation-form-section-title">
                  <span className="automation-step-number">1</span>
                  When should this run?
                </h3>

                <div className="automation-builder-card">
                  <div className="automation-builder-card-heading">
                    <span className="automation-builder-icon">↗</span>
                    <div>
                      <strong>Deal is created</strong>
                      <p>Start this workflow when a new deal is created.</p>
                    </div>
                  </div>

                  <label className="automation-field">
                    Event source
                    <select
                      value={form.triggerSource}
                      disabled={saving || editingRule?.status === "ACTIVE"}
                      onChange={(event) =>
                        updateForm("triggerSource", event.target.value as "deals")
                      }
                    >
                      <option value="deals">Deals</option>
                    </select>
                  </label>
                </div>

                <h3 className="automation-form-section-title">
                  <span className="automation-step-number">2</span>
                  Optional conditions
                </h3>

                <div className="automation-builder-card">
                  <label className="automation-toggle-row">
                    <input
                      type="checkbox"
                      checked={form.useCondition}
                      disabled={saving || editingRule?.status === "ACTIVE"}
                      onChange={(event) =>
                        updateForm("useCondition", event.target.checked)
                      }
                    />
                    <span>
                      <strong>Only run when a deal matches a condition</strong>
                      <small>
                        Leave this unchecked to run for every newly created deal.
                      </small>
                    </span>
                  </label>

                  {form.useCondition && (
                    <div className="automation-form-grid automation-condition-grid">
                      <label className="automation-field">
                        Deal field
                        <select
                          value={form.conditionField}
                          disabled={saving || editingRule?.status === "ACTIVE"}
                          onChange={(event) =>
                            updateForm(
                              "conditionField",
                              event.target.value as ConditionField,
                            )
                          }
                        >
                          {CONDITION_FIELDS.map((field) => (
                            <option key={field.value} value={field.value}>
                              {field.label}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="automation-field">
                        Operator
                        <select
                          value={form.conditionOperator}
                          disabled={saving || editingRule?.status === "ACTIVE"}
                          onChange={(event) =>
                            updateForm(
                              "conditionOperator",
                              event.target.value as ConditionOperator,
                            )
                          }
                        >
                          {CONDITION_OPERATORS.map((operator) => (
                            <option key={operator.value} value={operator.value}>
                              {operator.label}
                            </option>
                          ))}
                        </select>
                      </label>

                      {form.conditionOperator === "exists" ? (
                        <label className="automation-field automation-field-full">
                          Condition
                          <select
                            value={String(form.conditionExists)}
                            disabled={saving || editingRule?.status === "ACTIVE"}
                            onChange={(event) =>
                              updateForm(
                                "conditionExists",
                                event.target.value === "true",
                              )
                            }
                          >
                            <option value="true">Has a value</option>
                            <option value="false">Is empty</option>
                          </select>
                        </label>
                      ) : (
                        <label className="automation-field automation-field-full">
                          {form.conditionOperator === "in" ||
                          form.conditionOperator === "not_in"
                            ? "Values (comma-separated)"
                            : "Value"}
                          <input
                            value={form.conditionValue}
                            disabled={saving || editingRule?.status === "ACTIVE"}
                            placeholder={
                              form.conditionField === "stage"
                                ? "e.g. NEW"
                                : form.conditionField === "expected_value"
                                  ? "e.g. 5000000"
                                  : "Enter a value"
                            }
                            onChange={(event) =>
                              updateForm("conditionValue", event.target.value)
                            }
                          />
                          {(form.conditionOperator === "in" ||
                            form.conditionOperator === "not_in") && (
                            <small>
                              Separate each value with a comma.
                            </small>
                          )}
                        </label>
                      )}
                    </div>
                  )}
                </div>

                <h3 className="automation-form-section-title">
                  <span className="automation-step-number">3</span>
                  What should happen?
                </h3>

                <div className="automation-builder-card">
                  <div className="automation-builder-card-heading">
                    <span className="automation-builder-icon">✓</span>
                    <div>
                      <strong>Create a follow-up</strong>
                      <p>
                        Create a task linked to the lead associated with the
                        new deal and assign it to the deal owner.
                      </p>
                    </div>
                  </div>

                  <div className="automation-form-grid">
                    <label className="automation-field automation-field-full">
                      Follow-up title <span className="required">*</span>
                      <input
                        value={form.followUpTitle}
                        maxLength={200}
                        required
                        disabled={saving || editingRule?.status === "ACTIVE"}
                        placeholder="e.g. Contact lead about new deal"
                        onChange={(event) =>
                          updateForm("followUpTitle", event.target.value)
                        }
                      />
                    </label>

                    <label className="automation-field">
                      Follow-up type
                      <select
                        value={form.followUpType}
                        disabled={saving || editingRule?.status === "ACTIVE"}
                        onChange={(event) =>
                          updateForm("followUpType", event.target.value)
                        }
                      >
                        {FOLLOW_UP_TYPES.map((type) => (
                          <option key={type.value} value={type.value}>
                            {type.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="automation-field">
                      Create follow-up after (days)
                      <input
                        type="number"
                        min={0}
                        max={3650}
                        step={1}
                        value={form.daysAfter}
                        required
                        disabled={saving || editingRule?.status === "ACTIVE"}
                        onChange={(event) =>
                          updateForm("daysAfter", event.target.value)
                        }
                      />
                      <small>
                        0 means due immediately; maximum delay is 3650 days.
                      </small>
                    </label>

                    <label className="automation-field automation-field-full">
                      Follow-up description
                      <textarea
                        value={form.followUpDescription}
                        maxLength={10000}
                        rows={3}
                        disabled={saving || editingRule?.status === "ACTIVE"}
                        placeholder="Instructions for the assigned user (optional)."
                        onChange={(event) =>
                          updateForm("followUpDescription", event.target.value)
                        }
                      />
                    </label>
                  </div>
                </div>

                <p className="automation-modal-help">
                  New rules are saved as drafts. Activate a rule after reviewing
                  the configuration. Rules only execute when the backend
                  receives a matching deal-created event.
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
                  disabled={saving || editingRule?.status === "ACTIVE"}
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
          <span className="automation-eyebrow">WORKFLOW MANAGEMENT</span>
          <h1>Automation rules</h1>
          <p className="automation-subtitle">
            Automate follow-ups when new deals enter your workspace.
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
        <div className="automation-alert automation-alert-error" role="alert">
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
            <span className="automation-summary-label">Rules on this page</span>
            <strong>{rules.length}</strong>
          </div>
        </article>

        <article className="automation-summary-card">
          <span className="automation-summary-icon active-icon">●</span>
          <div>
            <span className="automation-summary-label">Active on this page</span>
            <strong>{summary.active}</strong>
          </div>
        </article>

        <article className="automation-summary-card">
          <span className="automation-summary-icon draft-icon">◷</span>
          <div>
            <span className="automation-summary-label">Drafts on this page</span>
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
                : "Create your first rule to automate follow-ups for new deals."}
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
                        <div className="automation-rule-name">{rule.name}</div>
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
                              {busyRuleId === rule.id ? "Working…" : "Activate"}
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
                              {busyRuleId === rule.id ? "Working…" : "Disable"}
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
                    setPage((current) => Math.min(totalPages, current + 1))
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

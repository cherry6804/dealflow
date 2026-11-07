import { useRef, useState, type FormEvent } from "react";

import { Button, Checkbox, Dialog, SelectField, TextareaField, TextField } from "../../../components/ui";
import { ApiError } from "../../../lib/api";
import { automationRulesApi, type AutomationRule } from "../../../services/automationRuleApi";
import {
  buildRuleInput,
  CONDITION_FIELDS,
  CONDITION_OPERATORS,
  createEmptyForm,
  FOLLOW_UP_TYPES,
  getRuleEditorData,
  isSameForm,
  MAX_DAYS_AFTER,
  validateAutomationForm,
  type AutomationForm,
  type AutomationFormErrors,
  type ConditionField,
  type ConditionOperator,
  type RuleEditorData,
} from "./automation-rule-model";

interface AutomationRuleEditorProps {
  /** The rule to edit, or null to create one. */
  rule: AutomationRule | null;
  onClose: () => void;
  onSaved: (message: string, rule: AutomationRule) => void;
}

function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "The rule could not be saved. Please try again.";
}

/**
 * Creates or edits a rule. The rule is saved as it is; activating it is a separate action on the rule, and the server checks the
 * rule again before it can be activated. Conditions and actions beyond the first are kept unchanged.
 */
export function AutomationRuleEditor({ rule, onClose, onSaved }: AutomationRuleEditorProps) {
  const [editorData] = useState<RuleEditorData | null>(() => (rule ? getRuleEditorData(rule) : null));
  const [initial] = useState<AutomationForm>(() => editorData?.form ?? createEmptyForm());
  const [form, setForm] = useState<AutomationForm>(initial);
  const [errors, setErrors] = useState<AutomationFormErrors>({});
  const [serverError, setServerError] = useState("");
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const dirty = !isSameForm(form, initial);
  const extraCount = (editorData?.extraConditions.length ?? 0) + (editorData?.extraActions.length ?? 0);

  function update<K extends keyof AutomationForm>(key: K, value: AutomationForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;

    const found = validateAutomationForm(form);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    inFlight.current = true;
    setBusy(true);
    setServerError("");
    try {
      const input = buildRuleInput(form, editorData?.extraConditions ?? [], editorData?.extraActions ?? []);
      const saved = rule ? await automationRulesApi.update(rule.id, input) : await automationRulesApi.create(input);
      onSaved(rule ? `"${saved.name}" was updated. Its status is unchanged.` : `"${saved.name}" was saved as a draft. Activate it when you are ready.`, saved);
    } catch (error) {
      setServerError(messageOf(error));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const conditionValueLabel = form.conditionOperator === "in" || form.conditionOperator === "not_in" ? "Values (separated by commas)" : "Value";

  return (
    <Dialog
      open
      onClose={onClose}
      title={rule ? "Edit rule" : "New rule"}
      eyebrow="Automation rule"
      closeLabel="Close rule editor"
      size="lg"
      busy={busy}
      dirty={dirty && !busy}
      footer={(close) => (
        <>
          <Button variant="secondary" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" form="automation-rule-form" variant="primary" loading={busy} disabled={busy}>
            {rule ? "Save changes" : "Save rule"}
          </Button>
        </>
      )}
    >
      <form id="automation-rule-form" className="df-nested-form" onSubmit={(event) => void handleSubmit(event)} noValidate>
        {serverError ? (
          <p className="df-sales-form-message df-sales-form-message--error" role="alert">
            {serverError}
          </p>
        ) : null}

        <section className="df-ops-section" aria-labelledby="rule-details-title">
          <h3 id="rule-details-title" className="df-sales-section-title">
            1. Rule details
          </h3>
          <TextField label="Name" required maxLength={150} value={form.name} onChange={(event) => update("name", event.target.value)} disabled={busy} error={errors.name} />
          <TextareaField
            label="Description"
            rows={2}
            maxLength={20000}
            value={form.description}
            onChange={(event) => update("description", event.target.value)}
            helper="Optional. Shown to everyone who manages automation."
            disabled={busy}
          />
        </section>

        <section className="df-ops-section" aria-labelledby="rule-when-title">
          <h3 id="rule-when-title" className="df-sales-section-title">
            2. When it runs
          </h3>
          <p className="df-sales-muted">When a deal is created. Other triggers are not available yet.</p>
          <Checkbox
            label="Only run when the new deal matches a condition"
            checked={form.useCondition}
            onChange={(event) => update("useCondition", event.target.checked)}
            disabled={busy}
          />
          {form.useCondition ? (
            <div className="df-nested-form-row">
              <SelectField
                label="Deal field"
                value={form.conditionField}
                options={CONDITION_FIELDS.map((item) => ({ value: item.value, label: item.label }))}
                onChange={(event) => update("conditionField", event.target.value as ConditionField)}
                disabled={busy}
              />
              <SelectField
                label="Condition"
                value={form.conditionOperator}
                options={CONDITION_OPERATORS.map((item) => ({ value: item.value, label: item.label }))}
                onChange={(event) => update("conditionOperator", event.target.value as ConditionOperator)}
                disabled={busy}
              />
            </div>
          ) : null}
          {form.useCondition && form.conditionOperator === "exists" ? (
            <SelectField
              label="Must the deal field have a value?"
              value={form.conditionExists ? "yes" : "no"}
              options={[
                { value: "yes", label: "Yes, it has a value" },
                { value: "no", label: "No, it is empty" },
              ]}
              onChange={(event) => update("conditionExists", event.target.value === "yes")}
              disabled={busy}
            />
          ) : null}
          {form.useCondition && form.conditionOperator !== "exists" ? (
            <TextField
              label={conditionValueLabel}
              value={form.conditionValue}
              onChange={(event) => update("conditionValue", event.target.value)}
              disabled={busy}
              error={errors.conditionValue}
            />
          ) : null}
        </section>

        <section className="df-ops-section" aria-labelledby="rule-then-title">
          <h3 id="rule-then-title" className="df-sales-section-title">
            3. What it does
          </h3>
          <p className="df-sales-muted">Creates a follow-up for the deal. Other actions are not available yet.</p>
          <div className="df-nested-form-row">
            <TextField
              label="Follow-up due in (days)"
              required
              inputMode="numeric"
              value={form.daysAfter}
              onChange={(event) => update("daysAfter", event.target.value)}
              helper={`0 means the same day. Up to ${MAX_DAYS_AFTER} days.`}
              disabled={busy}
              error={errors.daysAfter}
            />
            <SelectField
              label="Follow-up type"
              value={form.followUpType}
              options={FOLLOW_UP_TYPES.map((item) => ({ value: item.value, label: item.label }))}
              onChange={(event) => update("followUpType", event.target.value)}
              disabled={busy}
            />
          </div>
          <TextField
            label="Follow-up title"
            required
            maxLength={255}
            value={form.followUpTitle}
            onChange={(event) => update("followUpTitle", event.target.value)}
            disabled={busy}
            error={errors.followUpTitle}
          />
          <TextareaField
            label="Follow-up notes"
            rows={2}
            maxLength={5000}
            value={form.followUpDescription}
            onChange={(event) => update("followUpDescription", event.target.value)}
            disabled={busy}
          />
        </section>

        {extraCount > 0 ? (
          <p className="df-field-helper" role="note">
            This rule also has {extraCount} additional condition or action{extraCount === 1 ? "" : "s"} that this editor does not change. They are kept as they are.
          </p>
        ) : null}
      </form>
    </Dialog>
  );
}

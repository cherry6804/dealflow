import { useCallback, useEffect, useState } from "react";

import {
  governanceApi,
  type BudgetList,
  type BudgetStatus,
  type UsageBreakdown,
} from "../../../services/governanceApi";
import { formatUnitQuantity, unitLabel } from "../governanceLabels";
import AlertThresholdsPanel from "./AlertThresholdsPanel";
import ConfirmChangeDialog from "./ConfirmChangeDialog";

interface UsagePanelProps {
  canManage: boolean;
}

const ALL_UNITS = [
  "tokens_input",
  "tokens_output",
  "audio_ms",
  "images",
  "document_pages",
  "provider_cost_minor",
  "customer_credits",
];

function errorText(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "The budget could not be saved. Please try again.";
}

export default function UsagePanel({ canManage }: UsagePanelProps) {
  const [data, setData] = useState<BudgetList | null>(null);
  const [breakdown, setBreakdown] = useState<UsageBreakdown | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ unit: string; current: number | null } | null>(null);
  const [draft, setDraft] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const [budgets, usage] = await Promise.all([
        governanceApi.getBudgets(),
        governanceApi.getUsageBreakdown("capability"),
      ]);
      setData(budgets);
      setBreakdown(usage);
      setLoadError(null);
    } catch (error) {
      setLoadError(errorText(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function openEditor(unit: string, budget: BudgetStatus | undefined) {
    setFormError(null);
    setDraft(budget ? String(budget.limit_quantity) : "");
    setEditing({ unit, current: budget ? budget.limit_quantity : null });
  }

  function validDraft(): number | null {
    const trimmed = draft.trim();
    if (!/^\d+$/.test(trimmed)) return null;
    const value = Number(trimmed);
    return Number.isSafeInteger(value) ? value : null;
  }

  async function save() {
    const value = validDraft();
    if (editing === null) return;
    if (value === null) {
      setFormError("Enter a whole number of zero or more.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await governanceApi.setBudget(editing.unit, value);
      setEditing(null);
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
  if (data === null) {
    return <p role="status">Loading usage and budgets…</p>;
  }

  const byUnit = new Map(data.items.map((item) => [item.unit, item]));

  return (
    <section aria-labelledby="usage-heading">
      <h2 id="usage-heading">Usage and budgets</h2>
      <p className="governance-muted">
        Current period: {data.period_start} to {data.period_end} (UTC). Each unit is counted
        separately. Provider cost and customer credits never share a budget.
      </p>
      <p className="governance-muted">
        Figures come only from recorded usage. No AI provider is connected yet, so the breakdown
        below is empty until a provider produces usage. Usage that is still reserved is shown
        separately from recorded usage.
      </p>
      <table className="governance-table">
        <caption className="governance-sr-only">Budget status by unit</caption>
        <thead>
          <tr>
            <th scope="col">Unit</th>
            <th scope="col">Limit</th>
            <th scope="col">Used</th>
            <th scope="col">Reserved</th>
            <th scope="col">Remaining</th>
            <th scope="col">Alerts</th>
            {canManage ? <th scope="col">Action</th> : null}
          </tr>
        </thead>
        <tbody>
          {ALL_UNITS.map((unit) => {
            const budget = byUnit.get(unit);
            return (
              <tr key={unit}>
                <th scope="row">{unitLabel(unit)}</th>
                <td>{budget ? formatUnitQuantity(unit, budget.limit_quantity) : "Not set"}</td>
                <td>{budget ? formatUnitQuantity(unit, budget.consumed_quantity) : "—"}</td>
                <td>{budget ? formatUnitQuantity(unit, budget.reserved_quantity) : "—"}</td>
                <td>
                  {budget
                    ? budget.overrun
                      ? `Over by ${formatUnitQuantity(unit, -budget.remaining_quantity)}`
                      : formatUnitQuantity(unit, budget.remaining_quantity)
                    : "—"}
                </td>
                <td>
                  {budget
                    ? `${budget.utilization_percent}% used.`
                    : "—"}
                </td>
                {canManage ? (
                  <td>
                    <button type="button" onClick={() => openEditor(unit, budget)}>
                      {budget ? "Change limit" : "Set limit"}
                    </button>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3>Usage by capability this month</h3>
      {breakdown === null || breakdown.items.length === 0 ? (
        <p className="governance-muted">No usage has been recorded this month.</p>
      ) : (
        <table className="governance-table">
          <caption className="governance-sr-only">Usage by capability and unit</caption>
          <thead>
            <tr>
              <th scope="col">Capability</th>
              <th scope="col">Unit</th>
              <th scope="col">Recorded</th>
              <th scope="col">Reserved, not yet settled</th>
              <th scope="col">Entries</th>
            </tr>
          </thead>
          <tbody>
            {breakdown.items.map((row) => (
              <tr key={`${row.group}-${row.unit}`}>
                <th scope="row">{row.group}</th>
                <td>{unitLabel(row.unit)}</td>
                <td>{formatUnitQuantity(row.unit, row.recorded_quantity)}</td>
                <td>{formatUnitQuantity(row.unit, row.reserved_quantity)}</td>
                <td>{row.entries}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <AlertThresholdsPanel canManage={canManage} />

      {editing !== null ? (
        <ConfirmChangeDialog
          open
          title={`Set the ${unitLabel(editing.unit)} limit`}
          description="A limit applies to this month only. Lowering it below current use stops new billable work until the month ends."
          confirmLabel="Save limit"
          submitting={submitting}
          error={formError}
          onConfirm={() => void save()}
          onCancel={() => setEditing(null)}
        >
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
          >
            <label htmlFor="budget-limit">Limit (whole number)</label>
            <input
              id="budget-limit"
              inputMode="numeric"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
          </form>
        </ConfirmChangeDialog>
      ) : null}
    </section>
  );
}

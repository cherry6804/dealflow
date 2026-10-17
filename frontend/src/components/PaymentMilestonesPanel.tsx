
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";

import { ApiError } from "../lib/api";
import {
  paymentMilestonesApi,
  type PaymentMilestone,
  type PaymentMilestoneCreateInput,
  type PaymentMilestoneUpdateInput,
} from "../services/dealApi";

import "./PaymentMilestonesPanel.css";

interface PaymentMilestonesPanelProps {
  dealId: string;
  dealTitle: string;
  onClose: () => void;
}

interface MilestoneForm {
  name: string;
  amount: string;
  currency: string;
  dueAt: string;
  notes: string;
}

const EMPTY_FORM: MilestoneForm = {
  name: "",
  amount: "",
  currency: "INR",
  dueAt: "",
  notes: "",
};

function getErrorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : error instanceof Error
      ? error.message
      : "Something went wrong. Please try again.";
}

function formatAmount(
  amount: number | string,
  currency: string,
): string {
  const value = Number(amount);

  if (!Number.isFinite(value)) {
    return `${currency} ${amount}`;
  }

  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toLocaleString("en-IN")}`;
  }
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

function toLocalDateTime(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "";

  const localDate = new Date(
    date.getTime() - date.getTimezoneOffset() * 60_000,
  );

  return localDate.toISOString().slice(0, 16);
}

function toUtcIso(value: string): string {
  return new Date(value).toISOString();
}

function statusLabel(milestone: PaymentMilestone): string {
  if (milestone.status === "PAID") return "Paid";
  if (milestone.status === "CANCELLED") return "Cancelled";
  return milestone.is_overdue ? "Overdue" : "Pending";
}

function statusClass(milestone: PaymentMilestone): string {
  if (milestone.status === "PAID") {
    return "payment-milestone-status payment-milestone-status-paid";
  }

  if (milestone.status === "CANCELLED") {
    return "payment-milestone-status payment-milestone-status-cancelled";
  }

  if (milestone.is_overdue) {
    return "payment-milestone-status payment-milestone-status-overdue";
  }

  return "payment-milestone-status payment-milestone-status-pending";
}

export default function PaymentMilestonesPanel({
  dealId,
  dealTitle,
  onClose,
}: PaymentMilestonesPanelProps) {
  const [milestones, setMilestones] = useState<PaymentMilestone[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [form, setForm] = useState<MilestoneForm>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [paymentReferences, setPaymentReferences] = useState<
    Record<string, string>
  >({});

  const loadMilestones = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const result = await paymentMilestonesApi.list(dealId);
      setMilestones(result.items);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [dealId]);

  useEffect(() => {
    void loadMilestones();
  }, [loadMilestones]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose, saving]);

  const summary = useMemo(() => {
    const pending = milestones.filter(
      (item) => item.status === "PENDING",
    );

    const paid = milestones.filter(
      (item) => item.status === "PAID",
    );

    const overdue = pending.filter((item) => item.is_overdue);

    return {
      total: milestones.length,
      pending: pending.length,
      paid: paid.length,
      overdue: overdue.length,
      pendingValue: pending.reduce(
        (sum, item) => sum + Number(item.amount || 0),
        0,
      ),
      paidValue: paid.reduce(
        (sum, item) => sum + Number(item.amount || 0),
        0,
      ),
    };
  }, [milestones]);

  function openCreateForm() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError("");
    setIsFormOpen(true);
  }

  function openEditForm(milestone: PaymentMilestone) {
    if (milestone.status !== "PENDING") return;

    setEditingId(milestone.id);
    setForm({
      name: milestone.name,
      amount: String(milestone.amount),
      currency: milestone.currency,
      dueAt: toLocalDateTime(milestone.due_at),
      notes: milestone.notes ?? "",
    });
    setFormError("");
    setIsFormOpen(true);
  }

  function updateForm<K extends keyof MilestoneForm>(
    key: K,
    value: MilestoneForm[K],
  ) {
    setForm((current) => ({
      ...current,
      [key]: value,
    }));
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (saving) return;

    setFormError("");
    setSuccess("");

    const name = form.name.trim();
    const amount = Number(form.amount);
    const currency = form.currency.trim().toUpperCase();

    if (!name) {
      setFormError("Enter a milestone name.");
      return;
    }

    if (!Number.isFinite(amount) || amount <= 0) {
      setFormError("Amount must be greater than zero.");
      return;
    }

    if (!/^[A-Z]{3}$/.test(currency)) {
      setFormError("Enter a valid three-letter currency code.");
      return;
    }

    if (
      !form.dueAt ||
      Number.isNaN(new Date(form.dueAt).getTime())
    ) {
      setFormError("Select a valid due date and time.");
      return;
    }

    setSaving(true);

    try {
      if (editingId) {
        const input: PaymentMilestoneUpdateInput = {
          name,
          amount,
          currency,
          due_at: toUtcIso(form.dueAt),
          notes: form.notes.trim() || null,
        };

        await paymentMilestonesApi.update(editingId, input);
        setSuccess("Payment milestone updated successfully.");
      } else {
        const input: PaymentMilestoneCreateInput = {
          name,
          amount,
          currency,
          due_at: toUtcIso(form.dueAt),
          notes: form.notes.trim() || null,
        };

        await paymentMilestonesApi.create(dealId, input);
        setSuccess("Payment milestone created successfully.");
      }

      setIsFormOpen(false);
      setEditingId(null);
      setForm(EMPTY_FORM);
      await loadMilestones();
    } catch (saveError) {
      setFormError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function handleMarkPaid(milestone: PaymentMilestone) {
    if (saving || milestone.status !== "PENDING") return;

    setError("");
    setSuccess("");
    setSaving(true);

    try {
      await paymentMilestonesApi.markPaid(milestone.id, {
        payment_reference:
          paymentReferences[milestone.id]?.trim() || null,
      });

      setSuccess(`"${milestone.name}" marked as paid.`);
      setPaymentReferences((current) => ({
        ...current,
        [milestone.id]: "",
      }));

      await loadMilestones();
    } catch (actionError) {
      setError(getErrorMessage(actionError));
    } finally {
      setSaving(false);
    }
  }

  async function handleCancel(milestone: PaymentMilestone) {
    if (saving || milestone.status !== "PENDING") return;

    const confirmed = window.confirm(
      `Cancel the "${milestone.name}" payment milestone?`,
    );

    if (!confirmed) return;

    setError("");
    setSuccess("");
    setSaving(true);

    try {
      await paymentMilestonesApi.cancel(milestone.id);
      setSuccess(`"${milestone.name}" cancelled.`);
      await loadMilestones();
    } catch (actionError) {
      setError(getErrorMessage(actionError));
    } finally {
      setSaving(false);
    }
  }

  return createPortal(
    <div
      className="payment-milestones-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (
          event.target === event.currentTarget &&
          !saving
        ) {
          onClose();
        }
      }}
    >
      <section
        className="payment-milestones-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="payment-milestones-title"
      >
        <header className="payment-milestones-header">
          <div>
            <span className="payment-milestones-eyebrow">
              DEAL WORKSPACE
            </span>
            <h2 id="payment-milestones-title">
              Payment milestones
            </h2>
            <p>{dealTitle}</p>
          </div>

          <button
            type="button"
            className="payment-milestones-close"
            aria-label="Close payment milestones"
            disabled={saving}
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="payment-milestones-body">
          {error && (
            <div className="payment-milestones-alert error" role="alert">
              <span>{error}</span>
              <button
                type="button"
                onClick={() => void loadMilestones()}
                disabled={loading}
              >
                Retry
              </button>
            </div>
          )}

          {success && (
            <div
              className="payment-milestones-alert success"
              role="status"
            >
              {success}
            </div>
          )}

          <div className="payment-milestones-summary">
            <article>
              <span>Total milestones</span>
              <strong>{summary.total}</strong>
            </article>
            <article>
              <span>Pending amount</span>
              <strong>
                {formatAmount(summary.pendingValue, "INR")}
              </strong>
            </article>
            <article>
              <span>Paid amount</span>
              <strong>
                {formatAmount(summary.paidValue, "INR")}
              </strong>
            </article>
            <article className={summary.overdue ? "has-overdue" : ""}>
              <span>Overdue</span>
              <strong>{summary.overdue}</strong>
            </article>
          </div>

          <div className="payment-milestones-toolbar">
            <div>
              <h3>Milestone schedule</h3>
              <p>
                Track expected payments and record completed payments.
              </p>
            </div>

            <button
              type="button"
              className="payment-milestones-primary"
              onClick={openCreateForm}
              disabled={saving}
            >
              + Add milestone
            </button>
          </div>

          {loading ? (
            <div className="payment-milestones-state" role="status">
              Loading payment milestones…
            </div>
          ) : milestones.length === 0 ? (
            <div className="payment-milestones-empty">
              <div aria-hidden="true">₹</div>
              <h3>No payment milestones yet</h3>
              <p>
                Add booking advances, installment payments, or final
                payment milestones for this deal.
              </p>
              <button
                type="button"
                className="payment-milestones-primary"
                onClick={openCreateForm}
              >
                Create first milestone
              </button>
            </div>
          ) : (
            <div className="payment-milestones-list">
              {milestones.map((milestone) => (
                <article
                  className="payment-milestone-card"
                  key={milestone.id}
                >
                  <div className="payment-milestone-card-heading">
                    <div>
                      <h4>{milestone.name}</h4>
                      <p className="payment-milestone-amount">
                        {formatAmount(
                          milestone.amount,
                          milestone.currency,
                        )}
                      </p>
                    </div>

                    <span className={statusClass(milestone)}>
                      {statusLabel(milestone)}
                    </span>
                  </div>

                  <div className="payment-milestone-meta">
                    <span>
                      <strong>Due date</strong>
                      {formatDate(milestone.due_at)}
                    </span>
                    {milestone.paid_at && (
                      <span>
                        <strong>Paid on</strong>
                        {formatDate(milestone.paid_at)}
                      </span>
                    )}
                    {milestone.payment_reference && (
                      <span>
                        <strong>Reference</strong>
                        {milestone.payment_reference}
                      </span>
                    )}
                  </div>

                  {milestone.notes && (
                    <p className="payment-milestone-notes">
                      {milestone.notes}
                    </p>
                  )}

                  {milestone.status === "PENDING" && (
                    <div className="payment-milestone-actions">
                      <label>
                        <span>Payment reference (optional)</span>
                        <input
                          type="text"
                          maxLength={200}
                          value={
                            paymentReferences[milestone.id] ?? ""
                          }
                          onChange={(event) =>
                            setPaymentReferences((current) => ({
                              ...current,
                              [milestone.id]: event.target.value,
                            }))
                          }
                          placeholder="Transaction ID or receipt number"
                          disabled={saving}
                        />
                      </label>

                      <div className="payment-milestone-buttons">
                        <button
                          type="button"
                          className="payment-milestones-secondary"
                          onClick={() => openEditForm(milestone)}
                          disabled={saving}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="payment-milestones-paid"
                          onClick={() => void handleMarkPaid(milestone)}
                          disabled={saving}
                        >
                          Mark paid
                        </button>
                        <button
                          type="button"
                          className="payment-milestones-cancel"
                          onClick={() => void handleCancel(milestone)}
                          disabled={saving}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}

          {isFormOpen &&
            createPortal(
              <div
                className="payment-milestone-form-backdrop"
                role="presentation"
                onMouseDown={(event) => {
                  if (event.target === event.currentTarget && !saving) {
                    setIsFormOpen(false);
                    setFormError("");
                  }
                }}
              >
                <section
                  className="payment-milestone-form-modal"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="payment-milestone-form-title"
                >
                  <header className="payment-milestone-form-modal-header">
                    <div>
                      <span className="payment-milestones-eyebrow">
                        PAYMENT SCHEDULE
                      </span>
                      <h2 id="payment-milestone-form-title">
                        {editingId ? "Edit milestone" : "New milestone"}
                      </h2>
                    </div>
                    <button
                      type="button"
                      className="payment-milestone-form-close"
                      aria-label="Close milestone form"
                      disabled={saving}
                      onClick={() => {
                        setIsFormOpen(false);
                        setFormError("");
                      }}
                    >
                      ×
                    </button>
                  </header>

                  <div className="payment-milestone-form-wrap">
                    <form className="payment-milestone-form" onSubmit={handleSave}>
                      <div className="payment-milestone-form-body">
                {formError && (
                  <div
                    className="payment-milestones-alert error"
                    role="alert"
                  >
                    {formError}
                  </div>
                )}

                <div className="payment-milestone-form-grid">
                  <label className="full">
                    <span>Milestone name *</span>
                    <input
                      type="text"
                      required
                      maxLength={150}
                      value={form.name}
                      onChange={(event) =>
                        updateForm("name", event.target.value)
                      }
                      placeholder="e.g. Booking advance"
                      disabled={saving}
                    />
                  </label>

                  <label>
                    <span>Amount *</span>
                    <input
                      type="number"
                      required
                      min="0.01"
                      step="0.01"
                      value={form.amount}
                      onChange={(event) =>
                        updateForm("amount", event.target.value)
                      }
                      placeholder="500000"
                      disabled={saving}
                    />
                  </label>

                  <label>
                    <span>Currency *</span>
                    <select
                      value={form.currency}
                      onChange={(event) =>
                        updateForm("currency", event.target.value)
                      }
                      disabled={saving}
                    >
                      <option value="INR">INR — Indian Rupee</option>
                      <option value="USD">USD — US Dollar</option>
                      <option value="AED">AED — UAE Dirham</option>
                      <option value="GBP">GBP — Pound Sterling</option>
                    </select>
                  </label>

                  <label className="full">
                    <span>Due date and time *</span>
                    <input
                      type="datetime-local"
                      required
                      value={form.dueAt}
                      onChange={(event) =>
                        updateForm("dueAt", event.target.value)
                      }
                      disabled={saving}
                    />
                  </label>

                  <label className="full">
                    <span>Notes</span>
                    <textarea
                      rows={3}
                      maxLength={2000}
                      value={form.notes}
                      onChange={(event) =>
                        updateForm("notes", event.target.value)
                      }
                      placeholder="Payment terms or additional details"
                      disabled={saving}
                    />
                  </label>
                </div>

                      </div>
                <footer className="payment-milestone-form-actions">
                  <button
                    type="button"
                    className="payment-milestones-secondary"
                    onClick={() => {
                      setIsFormOpen(false);
                      setFormError("");
                    }}
                    disabled={saving}
                  >
                    Back
                  </button>
                  <button
                    type="submit"
                    className="payment-milestones-primary"
                    disabled={saving}
                  >
                    {saving
                      ? "Saving…"
                      : editingId
                        ? "Save changes"
                        : "Create milestone"}
                  </button>
                </footer>
                    </form>
                  </div>
                </section>
              </div>,
              document.body,
            )}

        </div>

        <footer className="payment-milestones-footer">
          <button
            type="button"
            className="payment-milestones-secondary"
            onClick={onClose}
            disabled={saving}
          >
            Close
          </button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}

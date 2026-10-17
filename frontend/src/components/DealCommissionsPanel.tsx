
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
  dealCommissionsApi,
  type DealCommission,
  type DealCommissionCreateInput,
  type DealCommissionStatus,
  type DealCommissionType,
  type DealCommissionUpdateInput,
} from "../services/dealApi";

import "./DealCommissionsPanel.css";

interface DealCommissionsPanelProps {
  dealId: string;
  dealTitle: string;
  dealValue: number | string | null;
  currency: string;
  onClose: () => void;
}

interface CommissionForm {
  commissionType: DealCommissionType;
  amount: string;
  currency: string;
  terms: string;
}

const EMPTY_FORM: CommissionForm = {
  commissionType: "PERCENTAGE",
  amount: "",
  currency: "INR",
  terms: "",
};

function getErrorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : error instanceof Error
      ? error.message
      : "Something went wrong. Please try again.";
}

function formatAmount(
  amount: number | string | null | undefined,
  currency: string,
): string {
  if (amount === null || amount === undefined || amount === "") {
    return "Not available";
  }

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

function formatDate(value: string | null): string {
  if (!value) return "—";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function statusLabel(status: DealCommissionStatus): string {
  switch (status) {
    case "PROPOSED":
      return "Proposed";
    case "AGREED":
      return "Agreed";
    case "PAID":
      return "Paid";
    case "CANCELLED":
      return "Cancelled";
  }
}

function statusClass(status: DealCommissionStatus): string {
  return `deal-commission-status deal-commission-status-${status.toLowerCase()}`;
}

function commissionDescription(commission: DealCommission): string {
  if (commission.commission_type === "PERCENTAGE") {
    return `${Number(commission.rate_percent ?? 0).toLocaleString("en-IN", {
      maximumFractionDigits: 4,
    })}% commission`;
  }

  return "Fixed commission";
}

export default function DealCommissionsPanel({
  dealId,
  dealTitle,
  dealValue,
  currency,
  onClose,
}: DealCommissionsPanelProps) {
  const [commissions, setCommissions] = useState<DealCommission[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [form, setForm] = useState<CommissionForm>({
    ...EMPTY_FORM,
    currency: currency.trim().toUpperCase() || "INR",
  });
  const [formError, setFormError] = useState("");
  const [paymentReferences, setPaymentReferences] = useState<
    Record<string, string>
  >({});

  const loadCommissions = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const result = await dealCommissionsApi.list(dealId);
      setCommissions(result.items);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [dealId]);

  useEffect(() => {
    void loadCommissions();
  }, [loadCommissions]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving && !isFormOpen) {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isFormOpen, onClose, saving]);

  const summary = useMemo(() => {
    const proposed = commissions.filter(
      (item) => item.status === "PROPOSED",
    );
    const agreed = commissions.filter((item) => item.status === "AGREED");
    const paid = commissions.filter((item) => item.status === "PAID");

    return {
      total: commissions.length,
      proposed: proposed.length,
      agreed: agreed.length,
      paid: paid.length,
      agreedValue: agreed.reduce(
        (sum, item) => sum + Number(item.calculated_amount ?? 0),
        0,
      ),
      paidValue: paid.reduce(
        (sum, item) => sum + Number(item.calculated_amount ?? 0),
        0,
      ),
    };
  }, [commissions]);

  function updateForm<K extends keyof CommissionForm>(
    key: K,
    value: CommissionForm[K],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function openCreateForm() {
    setEditingId(null);
    setForm({
      ...EMPTY_FORM,
      currency: currency.trim().toUpperCase() || "INR",
    });
    setFormError("");
    setIsFormOpen(true);
  }

  function openEditForm(commission: DealCommission) {
    if (
      commission.status !== "PROPOSED" &&
      commission.status !== "AGREED"
    ) {
      return;
    }

    setEditingId(commission.id);
    setForm({
      commissionType: commission.commission_type,
      amount: String(
        commission.commission_type === "FIXED"
          ? commission.fixed_amount ?? ""
          : commission.rate_percent ?? "",
      ),
      currency: commission.currency,
      terms: commission.terms ?? "",
    });
    setFormError("");
    setIsFormOpen(true);
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (saving) return;

    setFormError("");
    setError("");
    setSuccess("");

    const amount = Number(form.amount);
    const normalizedCurrency = form.currency.trim().toUpperCase();
    const terms = form.terms.trim() || null;

    if (!Number.isFinite(amount) || amount <= 0) {
      setFormError(
        form.commissionType === "PERCENTAGE"
          ? "Commission percentage must be greater than zero."
          : "Commission amount must be greater than zero.",
      );
      return;
    }

    if (
      form.commissionType === "PERCENTAGE" &&
      amount > 100
    ) {
      setFormError("Commission percentage cannot exceed 100%.");
      return;
    }

    if (!/^[A-Z]{3}$/.test(normalizedCurrency)) {
      setFormError("Enter a valid three-letter currency code.");
      return;
    }

    setSaving(true);

    try {
      if (editingId) {
        const input: DealCommissionUpdateInput = {
          commission_type: form.commissionType,
          fixed_amount:
            form.commissionType === "FIXED" ? amount : null,
          rate_percent:
            form.commissionType === "PERCENTAGE" ? amount : null,
          currency: normalizedCurrency,
          terms,
        };

        await dealCommissionsApi.update(editingId, input);
        setSuccess(
          "Commission updated. Review the status if its terms changed.",
        );
      } else {
        const input: DealCommissionCreateInput =
          form.commissionType === "FIXED"
            ? {
                commission_type: "FIXED",
                fixed_amount: amount,
                currency: normalizedCurrency,
                terms,
              }
            : {
                commission_type: "PERCENTAGE",
                rate_percent: amount,
                currency: normalizedCurrency,
                terms,
              };

        await dealCommissionsApi.create(dealId, input);
        setSuccess("Commission proposal created successfully.");
      }

      setIsFormOpen(false);
      setEditingId(null);
      await loadCommissions();
    } catch (saveError) {
      setFormError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function handleAgree(commission: DealCommission) {
    if (saving || commission.status !== "PROPOSED") return;

    const confirmed = window.confirm(
      "Agree to these commission terms? This records the commission as agreed.",
    );

    if (!confirmed) return;

    setSaving(true);
    setError("");
    setSuccess("");

    try {
      await dealCommissionsApi.agree(commission.id);
      setSuccess("Commission terms agreed successfully.");
      await loadCommissions();
    } catch (actionError) {
      setError(getErrorMessage(actionError));
    } finally {
      setSaving(false);
    }
  }

  async function handleMarkPaid(commission: DealCommission) {
    if (saving || commission.status !== "AGREED") return;

    const confirmed = window.confirm(
      "Record this commission as paid? Confirm that payment has actually been received or made.",
    );

    if (!confirmed) return;

    setSaving(true);
    setError("");
    setSuccess("");

    try {
      await dealCommissionsApi.markPaid(commission.id, {
        payment_reference:
          paymentReferences[commission.id]?.trim() || null,
      });

      setPaymentReferences((current) => ({
        ...current,
        [commission.id]: "",
      }));
      setSuccess("Commission payment recorded successfully.");
      await loadCommissions();
    } catch (actionError) {
      setError(getErrorMessage(actionError));
    } finally {
      setSaving(false);
    }
  }

  async function handleCancel(commission: DealCommission) {
    if (
      saving ||
      (commission.status !== "PROPOSED" &&
        commission.status !== "AGREED")
    ) {
      return;
    }

    const confirmed = window.confirm(
      "Cancel this commission? This action cannot be undone from this panel.",
    );

    if (!confirmed) return;

    setSaving(true);
    setError("");
    setSuccess("");

    try {
      await dealCommissionsApi.cancel(commission.id);
      setSuccess("Commission cancelled.");
      await loadCommissions();
    } catch (actionError) {
      setError(getErrorMessage(actionError));
    } finally {
      setSaving(false);
    }
  }

  return createPortal(
    <div
      className="deal-commissions-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (
          event.target === event.currentTarget &&
          !saving &&
          !isFormOpen
        ) {
          onClose();
        }
      }}
    >
      <section
        className="deal-commissions-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="deal-commissions-title"
      >
        <header className="deal-commissions-header">
          <div>
            <span className="deal-commissions-eyebrow">
              DEAL WORKSPACE
            </span>
            <h2 id="deal-commissions-title">Commission tracking</h2>
            <p>{dealTitle}</p>
          </div>

          <button
            type="button"
            className="deal-commissions-close"
            aria-label="Close commission tracking"
            disabled={saving}
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="deal-commissions-body">
          {error && (
            <div className="deal-commissions-alert error" role="alert">
              <span>{error}</span>
              <button
                type="button"
                onClick={() => void loadCommissions()}
                disabled={loading || saving}
              >
                Retry
              </button>
            </div>
          )}

          {success && (
            <div
              className="deal-commissions-alert success"
              role="status"
            >
              {success}
            </div>
          )}

          <section className="deal-commissions-deal-value">
            <div>
              <span>Deal expected value</span>
              <strong>{formatAmount(dealValue, currency)}</strong>
            </div>
            <p>
              Percentage commissions are calculated using the deal's
              expected value. Update that value on the deal if it changes.
            </p>
          </section>

          <div className="deal-commissions-summary">
            <article>
              <span>Total commissions</span>
              <strong>{summary.total}</strong>
            </article>
            <article>
              <span>Proposed</span>
              <strong>{summary.proposed}</strong>
            </article>
            <article>
              <span>Agreed value</span>
              <strong>{formatAmount(summary.agreedValue, currency)}</strong>
            </article>
            <article>
              <span>Paid value</span>
              <strong>{formatAmount(summary.paidValue, currency)}</strong>
            </article>
          </div>

          <div className="deal-commissions-toolbar">
            <div>
              <h3>Commission agreements</h3>
              <p>
                Define terms, record agreement, and track commission
                payments.
              </p>
            </div>

            <button
              type="button"
              className="deal-commissions-primary"
              onClick={openCreateForm}
              disabled={saving}
            >
              + Add commission
            </button>
          </div>

          {loading ? (
            <div className="deal-commissions-state" role="status">
              Loading commissions…
            </div>
          ) : commissions.length === 0 ? (
            <div className="deal-commissions-empty">
              <div aria-hidden="true">%</div>
              <h3>No commissions recorded</h3>
              <p>
                Add a fixed-fee or percentage-based commission to start
                tracking the agreement and payment.
              </p>
              <button
                type="button"
                className="deal-commissions-primary"
                onClick={openCreateForm}
                disabled={saving}
              >
                Create first commission
              </button>
            </div>
          ) : (
            <div className="deal-commissions-list">
              {commissions.map((commission) => (
                <article
                  className="deal-commission-card"
                  key={commission.id}
                >
                  <div className="deal-commission-card-heading">
                    <div>
                      <span className="deal-commission-type">
                        {commissionDescription(commission)}
                      </span>
                      <h4>
                        {formatAmount(
                          commission.calculated_amount,
                          commission.currency,
                        )}
                      </h4>
                      {commission.commission_type === "PERCENTAGE" && (
                        <p className="deal-commission-calculation">
                          Based on deal value of{" "}
                          {formatAmount(dealValue, currency)}
                        </p>
                      )}
                    </div>

                    <span className={statusClass(commission.status)}>
                      {statusLabel(commission.status)}
                    </span>
                  </div>

                  <div className="deal-commission-meta">
                    <span>
                      <strong>Currency</strong>
                      {commission.currency}
                    </span>
                    <span>
                      <strong>Created</strong>
                      {formatDate(commission.created_at)}
                    </span>
                    {commission.agreed_at && (
                      <span>
                        <strong>Agreed on</strong>
                        {formatDate(commission.agreed_at)}
                      </span>
                    )}
                    {commission.paid_at && (
                      <span>
                        <strong>Paid on</strong>
                        {formatDate(commission.paid_at)}
                      </span>
                    )}
                    {commission.payment_reference && (
                      <span>
                        <strong>Payment reference</strong>
                        {commission.payment_reference}
                      </span>
                    )}
                  </div>

                  {commission.terms && (
                    <p className="deal-commission-terms">
                      {commission.terms}
                    </p>
                  )}

                  {(commission.status === "PROPOSED" ||
                    commission.status === "AGREED") && (
                    <div className="deal-commission-actions">
                      {commission.status === "AGREED" && (
                        <label>
                          <span>Payment reference (optional)</span>
                          <input
                            type="text"
                            maxLength={200}
                            value={paymentReferences[commission.id] ?? ""}
                            onChange={(event) =>
                              setPaymentReferences((current) => ({
                                ...current,
                                [commission.id]: event.target.value,
                              }))
                            }
                            placeholder="Transaction ID or receipt number"
                            disabled={saving}
                          />
                        </label>
                      )}

                      <div className="deal-commission-buttons">
                        <button
                          type="button"
                          className="deal-commissions-secondary"
                          onClick={() => openEditForm(commission)}
                          disabled={saving}
                        >
                          Edit terms
                        </button>

                        {commission.status === "PROPOSED" && (
                          <button
                            type="button"
                            className="deal-commissions-primary"
                            onClick={() => void handleAgree(commission)}
                            disabled={saving}
                          >
                            Agree terms
                          </button>
                        )}

                        {commission.status === "AGREED" && (
                          <button
                            type="button"
                            className="deal-commissions-paid"
                            onClick={() => void handleMarkPaid(commission)}
                            disabled={saving}
                          >
                            Mark paid
                          </button>
                        )}

                        <button
                          type="button"
                          className="deal-commissions-cancel"
                          onClick={() => void handleCancel(commission)}
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

          {isFormOpen && createPortal(
            <div
              className="deal-commission-form-backdrop"
              role="presentation"
              onMouseDown={(event) => {
                if (event.target === event.currentTarget && !saving) {
                  setIsFormOpen(false);
                  setFormError("");
                }
              }}
            >
              <section
                className="deal-commission-form-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="deal-commission-form-title"
              >
                <header className="deal-commission-form-header">
                  <div>
                    <span className="deal-commissions-eyebrow">
                      COMMISSION TERMS
                    </span>
                    <h2 id="deal-commission-form-title">
                      {editingId ? "Edit commission" : "New commission"}
                    </h2>
                  </div>
                  <button
                    type="button"
                    className="deal-commission-form-close"
                    aria-label="Close commission form"
                    disabled={saving}
                    onClick={() => {
                      setIsFormOpen(false);
                      setFormError("");
                    }}
                  >
                    ×
                  </button>
                </header>

                <form
                  className="deal-commission-form"
                  onSubmit={handleSave}
                >
                  <div className="deal-commission-form-body">
                    {formError && (
                      <div
                        className="deal-commissions-alert error"
                        role="alert"
                      >
                        {formError}
                      </div>
                    )}

                    {editingId && (
                      <p className="deal-commission-edit-notice">
                        Editing agreed terms returns the commission to
                        Proposed status.
                      </p>
                    )}

                    <div className="deal-commission-form-grid">
                      <label className="full">
                        <span>Commission type *</span>
                        <select
                          value={form.commissionType}
                          onChange={(event) =>
                            updateForm(
                              "commissionType",
                              event.target.value as DealCommissionType,
                            )
                          }
                          disabled={saving}
                        >
                          <option value="PERCENTAGE">
                            Percentage of deal value
                          </option>
                          <option value="FIXED">Fixed amount</option>
                        </select>
                      </label>

                      <label>
                        <span>
                          {form.commissionType === "PERCENTAGE"
                            ? "Commission rate (%) *"
                            : "Commission amount *"}
                        </span>
                        <input
                          type="number"
                          required
                          min="0.01"
                          max={
                            form.commissionType === "PERCENTAGE"
                              ? "100"
                              : undefined
                          }
                          step={
                            form.commissionType === "PERCENTAGE"
                              ? "0.0001"
                              : "0.01"
                          }
                          value={form.amount}
                          onChange={(event) =>
                            updateForm("amount", event.target.value)
                          }
                          placeholder={
                            form.commissionType === "PERCENTAGE"
                              ? "e.g. 2"
                              : "e.g. 50000"
                          }
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

                      {form.commissionType === "PERCENTAGE" && (
                        <div className="deal-commission-preview full">
                          <span>Estimated commission</span>
                          <strong>
                            {dealValue === null ||
                            dealValue === "" ||
                            !Number.isFinite(Number(dealValue))
                              ? "Deal value unavailable"
                              : formatAmount(
                                  (Number(dealValue) * Number(form.amount || 0)) /
                                    100,
                                  form.currency,
                                )}
                          </strong>
                          <p>
                            This is an estimate. The backend calculation
                            based on the deal's expected value is authoritative.
                          </p>
                        </div>
                      )}

                      <label className="full">
                        <span>Terms and conditions (optional)</span>
                        <textarea
                          rows={4}
                          maxLength={10000}
                          value={form.terms}
                          onChange={(event) =>
                            updateForm("terms", event.target.value)
                          }
                          placeholder="Payment conditions, split details, or other agreed terms"
                          disabled={saving}
                        />
                      </label>
                    </div>
                  </div>

                  <footer className="deal-commission-form-actions">
                    <button
                      type="button"
                      className="deal-commissions-secondary"
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
                      className="deal-commissions-primary"
                      disabled={saving}
                    >
                      {saving
                        ? "Saving…"
                        : editingId
                          ? "Save changes"
                          : "Create commission"}
                    </button>
                  </footer>
                </form>
              </section>
            </div>,
            document.body,
          )}
        </div>

        <footer className="deal-commissions-footer">
          <button
            type="button"
            className="deal-commissions-secondary"
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

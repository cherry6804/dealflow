import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";

import { ApiError } from "../lib/api";
import { dealCommissionsApi, type DealCommission, type DealCommissionType } from "../services/dealApi";
import {
  commissionDescription,
  commissionRateLabel,
  commissionStatus,
  commissionToForm,
  currencyOptions,
  emptyCommissionForm,
  isSameCommissionForm,
  toCommissionCreateInput,
  toCommissionUpdateInput,
  validateCommissionForm,
  type CommissionFormErrors,
  type CommissionFormValues,
} from "./deal-nested/deal-commission-form";
import { NestedRecordCard, NestedSummary } from "./record/NestedRecordParts";
import { formatDateTime, formatMoney, totalsByCurrency } from "./record/nested-records";
import { Button, Dialog, SelectField, TextField, TextareaField, useConfirmation } from "./ui";

interface DealCommissionsPanelProps {
  dealId: string;
  dealTitle: string;
  dealValue: number | string | null;
  currency: string;
  onClose: () => void;
  /** Called after a successful change so the parent deal can refresh. */
  onChanged: (message: string) => void;
}

type FormTarget = { mode: "create" } | { mode: "edit"; commission: DealCommission };

function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

/**
 * Totals of the server-calculated amounts, grouped by currency. A commission whose amount the server could not calculate (a
 * percentage without a deal value) is counted and reported, never added as zero.
 */
function CommissionTotals({ rows, empty }: { rows: readonly DealCommission[]; empty: string }): ReactNode {
  const totals = totalsByCurrency(rows.map((row) => ({ amount: row.calculated_amount, currency: row.currency })));
  if (totals.length === 0) return empty;
  return (
    <span className="df-nested-total-lines">
      {totals.map((total) => (
        <span key={total.currency}>
          {formatMoney(total.total, total.currency)}
          {total.unavailable > 0 ? (
            <span className="df-sales-muted"> · {total.unavailable} without a calculated amount</span>
          ) : null}
        </span>
      ))}
    </span>
  );
}

/**
 * Commission terms for a deal, shown in a nested dialog over the deal record. Amounts are calculated by the server; the panel
 * displays them and never computes its own. Agreeing, recording payment and cancelling each confirm first.
 */
export default function DealCommissionsPanel({ dealId, dealTitle, dealValue, currency, onClose, onChanged }: DealCommissionsPanelProps) {
  const [commissions, setCommissions] = useState<DealCommission[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [formTarget, setFormTarget] = useState<FormTarget | null>(null);
  const [formError, setFormError] = useState("");
  const [payTarget, setPayTarget] = useState<DealCommission | null>(null);
  const [payError, setPayError] = useState("");
  const [confirm, confirmDialog] = useConfirmation();

  const loadCommissions = useCallback(async () => {
    try {
      const result = await dealCommissionsApi.list(dealId);
      setCommissions(result.items);
      setLoadError("");
      setStatus("ready");
    } catch (error) {
      setLoadError(messageOf(error));
      setStatus("error");
    }
  }, [dealId]);

  // Initial load. State is set only inside the request callbacks, never synchronously in the effect body.
  useEffect(() => {
    let cancelled = false;
    dealCommissionsApi
      .list(dealId)
      .then((result) => {
        if (cancelled) return;
        setCommissions(result.items);
        setLoadError("");
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(messageOf(error));
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [dealId]);

  async function refresh(message: string) {
    setNotice(message);
    onChanged(message);
    await loadCommissions();
  }

  const proposed = commissions.filter((item) => item.status === "PROPOSED");
  const agreed = commissions.filter((item) => item.status === "AGREED");
  const paid = commissions.filter((item) => item.status === "PAID");

  async function handleSave(values: CommissionFormValues, target: FormTarget) {
    setBusy(true);
    setFormError("");
    try {
      if (target.mode === "edit") {
        await dealCommissionsApi.update(target.commission.id, toCommissionUpdateInput(values));
        setFormTarget(null);
        await refresh("Commission updated. Review its status if the terms changed.");
      } else {
        await dealCommissionsApi.create(dealId, toCommissionCreateInput(values));
        setFormTarget(null);
        await refresh("Commission proposal created.");
      }
    } catch (error) {
      setFormError(messageOf(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleAgree(commission: DealCommission) {
    if (busy || commission.status !== "PROPOSED") return;

    const confirmed = await confirm("This records that the commission terms have been agreed. You can still cancel the commission afterwards.", {
      title: "Agree to commission terms?",
      confirmLabel: "Agree terms",
    });
    if (!confirmed) return;

    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      await dealCommissionsApi.agree(commission.id);
      await refresh("Commission terms agreed.");
    } catch (error) {
      setActionError(messageOf(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleRecordPayment(reference: string | null) {
    if (!payTarget || busy) return;
    const target = payTarget;
    setBusy(true);
    setPayError("");
    try {
      await dealCommissionsApi.markPaid(target.id, { payment_reference: reference });
      setPayTarget(null);
      await refresh("Commission payment recorded.");
    } catch (error) {
      setPayError(messageOf(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel(commission: DealCommission) {
    if (busy || (commission.status !== "PROPOSED" && commission.status !== "AGREED")) return;

    const confirmed = await confirm("The commission will be cancelled. A cancelled commission cannot be edited, agreed or paid.", {
      title: "Cancel commission?",
      confirmLabel: "Cancel commission",
      tone: "danger",
    });
    if (!confirmed) return;

    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      await dealCommissionsApi.cancel(commission.id);
      await refresh("Commission cancelled.");
    } catch (error) {
      setActionError(messageOf(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Commissions"
      eyebrow="Deal workspace"
      description={dealTitle}
      closeLabel="Close commissions"
      size="lg"
      busy={busy}
      footer={
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Close
        </Button>
      }
    >
      <p className="df-sales-muted">
        Deal expected value: <strong>{formatMoney(dealValue, currency)}</strong>. Percentage commissions are calculated from this value by the server.
      </p>

      {loadError ? (
        <div className="df-sales-form-message df-sales-form-message--error" role="alert">
          <span>{loadError}</span>{" "}
          <Button variant="tertiary" size="sm" onClick={() => void loadCommissions()}>
            Retry
          </Button>
        </div>
      ) : null}
      {actionError ? (
        <p className="df-sales-form-message df-sales-form-message--error" role="alert">
          {actionError}
        </p>
      ) : null}
      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      {status === "loading" ? (
        <p className="df-sales-muted" role="status">
          Loading commissions…
        </p>
      ) : null}

      {status === "ready" ? (
        <>
          <NestedSummary
            label="Commission totals"
            items={[
              { label: "Total commissions", value: commissions.length },
              { label: "Proposed", value: proposed.length },
              { label: "Agreed", value: <CommissionTotals rows={agreed} empty="—" /> },
              { label: "Paid", value: <CommissionTotals rows={paid} empty="—" /> },
            ]}
          />

          <div className="df-nested-toolbar">
            <div>
              <h3>Commission agreements</h3>
              <p>Define terms, record agreement, and track payment.</p>
            </div>
            <Button variant="primary" size="sm" onClick={() => setFormTarget({ mode: "create" })} disabled={busy}>
              Add commission
            </Button>
          </div>

          {commissions.length === 0 ? (
            <div className="df-nested-empty">
              <h3>No commissions recorded</h3>
              <p>Add a fixed or percentage commission to track its agreement and payment.</p>
              <Button variant="primary" size="sm" onClick={() => setFormTarget({ mode: "create" })} disabled={busy}>
                Add first commission
              </Button>
            </div>
          ) : (
            <ul className="df-nested-list" aria-label="Commissions">
              {commissions.map((commission) => {
                const editable = commission.status === "PROPOSED" || commission.status === "AGREED";
                const meta = [
                  commission.commission_type === "PERCENTAGE"
                    ? { label: "Rate", value: commissionRateLabel(commission) }
                    : { label: "Basis", value: "Fixed amount" },
                  { label: "Currency", value: commission.currency },
                  ...(commission.agreed_at ? [{ label: "Agreed on", value: formatDateTime(commission.agreed_at) }] : []),
                  ...(commission.paid_at ? [{ label: "Paid on", value: formatDateTime(commission.paid_at) }] : []),
                  ...(commission.payment_reference ? [{ label: "Payment reference", value: commission.payment_reference }] : []),
                ];
                return (
                  <li key={commission.id}>
                    <NestedRecordCard
                      title={commissionDescription(commission)}
                      amount={
                        commission.calculated_amount === null && commission.commission_type === "PERCENTAGE"
                          ? "Not available until the deal has an expected value"
                          : formatMoney(commission.calculated_amount, commission.currency)
                      }
                      status={commissionStatus(commission)}
                      meta={meta}
                      notes={commission.terms}
                      actions={
                        editable ? (
                          <>
                            <Button variant="secondary" size="sm" onClick={() => setFormTarget({ mode: "edit", commission })} disabled={busy}>
                              Edit terms
                            </Button>
                            {commission.status === "PROPOSED" ? (
                              <Button variant="primary" size="sm" onClick={() => void handleAgree(commission)} disabled={busy}>
                                Agree terms
                              </Button>
                            ) : (
                              <Button variant="primary" size="sm" onClick={() => setPayTarget(commission)} disabled={busy}>
                                Record payment
                              </Button>
                            )}
                            <Button variant="danger" size="sm" onClick={() => void handleCancel(commission)} disabled={busy}>
                              Cancel commission
                            </Button>
                          </>
                        ) : undefined
                      }
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </>
      ) : null}

      {formTarget ? (
        <CommissionFormDialog
          target={formTarget}
          dealValue={dealValue}
          currency={currency}
          busy={busy}
          serverError={formError}
          onSubmit={(values) => void handleSave(values, formTarget)}
          onClose={() => {
            if (busy) return;
            setFormTarget(null);
            setFormError("");
          }}
        />
      ) : null}

      {payTarget ? (
        <RecordCommissionPaymentDialog
          commission={payTarget}
          busy={busy}
          serverError={payError}
          onConfirm={(reference) => void handleRecordPayment(reference)}
          onClose={() => {
            if (busy) return;
            setPayTarget(null);
            setPayError("");
          }}
        />
      ) : null}

      {confirmDialog}
    </Dialog>
  );
}

interface CommissionFormDialogProps {
  target: FormTarget;
  dealValue: number | string | null;
  currency: string;
  busy: boolean;
  serverError: string;
  onSubmit: (values: CommissionFormValues) => void;
  onClose: () => void;
}

function CommissionFormDialog({ target, dealValue, currency, busy, serverError, onSubmit, onClose }: CommissionFormDialogProps) {
  const [initial] = useState<CommissionFormValues>(() =>
    target.mode === "edit" ? commissionToForm(target.commission) : emptyCommissionForm(currency),
  );
  const [values, setValues] = useState<CommissionFormValues>(initial);
  const [errors, setErrors] = useState<CommissionFormErrors>({});
  const dirty = !isSameCommissionForm(values, initial);
  const editing = target.mode === "edit";
  const isPercentage = values.commissionType === "PERCENTAGE";

  function update<K extends keyof CommissionFormValues>(key: K, value: CommissionFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found = validateCommissionForm(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    onSubmit(values);
  }

  const currencyChoices = currencyOptions(values.currency).map((code) => ({ value: code, label: code }));
  const typeChoices: { value: DealCommissionType; label: string }[] = [
    { value: "PERCENTAGE", label: "Percentage of deal value" },
    { value: "FIXED", label: "Fixed amount" },
  ];

  return (
    <Dialog
      open
      onClose={onClose}
      title={editing ? "Edit commission" : "New commission"}
      eyebrow="Commission terms"
      closeLabel="Close commission form"
      size="md"
      busy={busy}
      dirty={dirty}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Back
          </Button>
          <Button type="submit" form="deal-commission-form" variant="primary" loading={busy} disabled={busy}>
            {editing ? "Save changes" : "Create commission"}
          </Button>
        </>
      }
    >
      <form id="deal-commission-form" className="df-nested-form" onSubmit={handleSubmit} noValidate>
        {editing && target.commission.status === "AGREED" ? (
          <p className="df-sales-notice" role="note">
            Editing agreed terms returns the commission to Proposed. It must be agreed again.
          </p>
        ) : null}
        {serverError ? (
          <p className="df-sales-form-message df-sales-form-message--error" role="alert">
            {serverError}
          </p>
        ) : null}

        <SelectField
          label="Commission basis"
          required
          value={values.commissionType}
          options={typeChoices}
          onChange={(event) => update("commissionType", event.target.value as DealCommissionType)}
          disabled={busy}
        />
        <TextField
          label={isPercentage ? "Commission rate (%)" : "Commission amount"}
          required
          inputMode="decimal"
          value={values.amount}
          onChange={(event) => update("amount", event.target.value)}
          placeholder={isPercentage ? "e.g. 2" : "e.g. 50000"}
          helper={
            isPercentage
              ? dealValue === null || dealValue === ""
                ? "The deal has no expected value yet, so the amount cannot be calculated until it does."
                : `Calculated by the server from the deal's expected value of ${formatMoney(dealValue, currency)} when saved.`
              : "Up to two decimal places."
          }
          disabled={busy}
          error={errors.amount}
        />
        <SelectField
          label="Currency"
          required
          value={values.currency}
          options={currencyChoices}
          onChange={(event) => update("currency", event.target.value)}
          disabled={busy}
          error={errors.currency}
        />
        <TextareaField
          label="Terms and conditions"
          rows={4}
          maxLength={10000}
          value={values.terms}
          onChange={(event) => update("terms", event.target.value)}
          placeholder="Payment conditions, split details or other agreed terms"
          disabled={busy}
          error={errors.terms}
        />
      </form>
    </Dialog>
  );
}

interface RecordCommissionPaymentDialogProps {
  commission: DealCommission;
  busy: boolean;
  serverError: string;
  onConfirm: (reference: string | null) => void;
  onClose: () => void;
}

function RecordCommissionPaymentDialog({ commission, busy, serverError, onConfirm, onClose }: RecordCommissionPaymentDialogProps) {
  const [reference, setReference] = useState("");

  return (
    <Dialog
      open
      onClose={onClose}
      title="Record commission payment"
      eyebrow={commissionDescription(commission)}
      closeLabel="Close record payment"
      size="sm"
      busy={busy}
      dirty={reference.trim().length > 0}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={busy} onClick={() => onConfirm(reference.trim() || null)}>
            Record payment
          </Button>
        </>
      }
    >
      <dl className="df-nested-card-meta">
        <div>
          <dt>Commission</dt>
          <dd>{formatMoney(commission.calculated_amount, commission.currency)}</dd>
        </div>
      </dl>
      <p className="df-sales-muted">Confirm that the commission has actually been paid. A paid commission cannot be edited or cancelled.</p>
      <TextField
        label="Payment reference (optional)"
        maxLength={200}
        value={reference}
        onChange={(event) => setReference(event.target.value)}
        helper="Transaction ID or receipt number."
        disabled={busy}
      />
      {serverError ? (
        <p className="df-sales-form-message df-sales-form-message--error" role="alert">
          {serverError}
        </p>
      ) : null}
    </Dialog>
  );
}

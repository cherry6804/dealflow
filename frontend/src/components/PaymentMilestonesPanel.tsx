import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { ApiError } from "../lib/api";
import { paymentMilestonesApi, type PaymentMilestone } from "../services/dealApi";
import { milestoneStatus, currencyOptions, emptyMilestoneForm, isSameMilestoneForm, milestoneToForm, toMilestoneCreateInput, toMilestoneUpdateInput, validateMilestoneForm, type MilestoneFormErrors, type MilestoneFormValues } from "./deal-nested/payment-milestone-form";
import { NestedRecordCard, NestedSummary } from "./record/NestedRecordParts";
import { formatDateTime, formatMoney, totalsByCurrency } from "./record/nested-records";
import { Button, Dialog, SelectField, TextField, TextareaField, useConfirmation } from "./ui";

interface PaymentMilestonesPanelProps {
  dealId: string;
  dealTitle: string;
  /** Currency preselected for new milestones (the deal's currency). */
  currency: string;
  onClose: () => void;
  /** Called after a successful change so the parent deal can refresh. */
  onChanged: (message: string) => void;
}

type FormTarget = { mode: "create" } | { mode: "edit"; milestone: PaymentMilestone };

function messageOf(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

function TotalLines({ rows, empty }: { rows: readonly PaymentMilestone[]; empty: string }): ReactNode {
  const totals = totalsByCurrency(rows);
  if (totals.length === 0) return empty;
  return (
    <span className="df-nested-total-lines">
      {totals.map((total) => (
        <span key={total.currency}>{formatMoney(total.total, total.currency)}</span>
      ))}
    </span>
  );
}

/**
 * Payment milestones for a deal, shown in a nested dialog over the deal record. Creating and editing use a nested form dialog;
 * recording a payment asks for the optional reference in its own step. Every change reloads the list and tells the parent deal.
 */
export default function PaymentMilestonesPanel({ dealId, dealTitle, currency, onClose, onChanged }: PaymentMilestonesPanelProps) {
  const [milestones, setMilestones] = useState<PaymentMilestone[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  // A ref, not state: a second click in the same frame must not start a second request.
  const inFlight = useRef(false);
  const [formTarget, setFormTarget] = useState<FormTarget | null>(null);
  const [formError, setFormError] = useState("");
  const [payTarget, setPayTarget] = useState<PaymentMilestone | null>(null);
  const [payError, setPayError] = useState("");
  const [confirm, confirmDialog] = useConfirmation();

  const loadMilestones = useCallback(async () => {
    try {
      const result = await paymentMilestonesApi.list(dealId);
      setMilestones(result.items);
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
    paymentMilestonesApi
      .list(dealId)
      .then((result) => {
        if (cancelled) return;
        setMilestones(result.items);
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
    await loadMilestones();
  }

  const pending = milestones.filter((item) => item.status === "PENDING");
  const paid = milestones.filter((item) => item.status === "PAID");
  const overdueCount = pending.filter((item) => item.is_overdue).length;

  async function handleSave(values: MilestoneFormValues, target: FormTarget) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setFormError("");
    try {
      if (target.mode === "edit") {
        await paymentMilestonesApi.update(target.milestone.id, toMilestoneUpdateInput(values));
        setFormTarget(null);
        await refresh("Payment milestone updated.");
      } else {
        await paymentMilestonesApi.create(dealId, toMilestoneCreateInput(values));
        setFormTarget(null);
        await refresh("Payment milestone created.");
      }
    } catch (error) {
      setFormError(messageOf(error));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function handleRecordPayment(reference: string | null) {
    if (!payTarget || busy) return;
    const target = payTarget;
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setPayError("");
    try {
      await paymentMilestonesApi.markPaid(target.id, { payment_reference: reference });
      setPayTarget(null);
      await refresh(`"${target.name}" marked as paid.`);
    } catch (error) {
      setPayError(messageOf(error));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  async function handleCancel(milestone: PaymentMilestone) {
    if (busy || milestone.status !== "PENDING") return;

    const confirmed = await confirm(`"${milestone.name}" will be cancelled. A cancelled milestone cannot be edited or paid.`, {
      title: "Cancel payment milestone?",
      confirmLabel: "Cancel milestone",
      tone: "danger",
    });
    if (!confirmed) return;

    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      await paymentMilestonesApi.cancel(milestone.id);
      await refresh(`"${milestone.name}" cancelled.`);
    } catch (error) {
      setActionError(messageOf(error));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Payment milestones"
      eyebrow="Deal workspace"
      description={dealTitle}
      closeLabel="Close payment milestones"
      size="lg"
      busy={busy}
      footer={
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Close
        </Button>
      }
    >
      {loadError ? (
        <div className="df-sales-form-message df-sales-form-message--error" role="alert">
          <span>{loadError}</span>{" "}
          <Button variant="tertiary" size="sm" onClick={() => void loadMilestones()}>
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
          Loading payment milestones…
        </p>
      ) : null}

      {status === "ready" ? (
        <>
          <NestedSummary
            label="Milestone totals"
            items={[
              { label: "Total milestones", value: milestones.length },
              { label: "Pending", value: <TotalLines rows={pending} empty="—" /> },
              { label: "Paid", value: <TotalLines rows={paid} empty="—" /> },
              { label: "Overdue", value: overdueCount, attention: overdueCount > 0 },
            ]}
          />

          <div className="df-nested-toolbar">
            <div>
              <h3>Milestone schedule</h3>
              <p>Track expected payments and record completed ones.</p>
            </div>
            <Button variant="primary" size="sm" onClick={() => setFormTarget({ mode: "create" })} disabled={busy}>
              Add milestone
            </Button>
          </div>

          {milestones.length === 0 ? (
            <div className="df-nested-empty">
              <h3>No payment milestones yet</h3>
              <p>Add booking advances, instalments or final payments for this deal.</p>
              <Button variant="primary" size="sm" onClick={() => setFormTarget({ mode: "create" })} disabled={busy}>
                Add first milestone
              </Button>
            </div>
          ) : (
            <ul className="df-nested-list" aria-label="Payment milestones">
              {milestones.map((milestone) => {
                const info = milestoneStatus(milestone);
                const meta = [
                  { label: "Due", value: formatDateTime(milestone.due_at) },
                  ...(milestone.paid_at ? [{ label: "Paid on", value: formatDateTime(milestone.paid_at) }] : []),
                  ...(milestone.payment_reference ? [{ label: "Payment reference", value: milestone.payment_reference }] : []),
                ];
                return (
                  <li key={milestone.id}>
                    <NestedRecordCard
                      title={milestone.name}
                      amount={formatMoney(milestone.amount, milestone.currency)}
                      status={info}
                      meta={meta}
                      notes={milestone.notes}
                      actions={
                        milestone.status === "PENDING" ? (
                          <>
                            <Button variant="secondary" size="sm" onClick={() => setFormTarget({ mode: "edit", milestone })} disabled={busy}>
                              Edit milestone
                            </Button>
                            <Button variant="primary" size="sm" onClick={() => setPayTarget(milestone)} disabled={busy}>
                              Record payment
                            </Button>
                            <Button variant="danger" size="sm" onClick={() => void handleCancel(milestone)} disabled={busy}>
                              Cancel milestone
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
        <MilestoneFormDialog
          target={formTarget}
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
        <RecordPaymentDialog
          milestone={payTarget}
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

interface MilestoneFormDialogProps {
  target: FormTarget;
  currency: string;
  busy: boolean;
  serverError: string;
  onSubmit: (values: MilestoneFormValues) => void;
  onClose: () => void;
}

function MilestoneFormDialog({ target, currency, busy, serverError, onSubmit, onClose }: MilestoneFormDialogProps) {
  const [initial] = useState<MilestoneFormValues>(() => (target.mode === "edit" ? milestoneToForm(target.milestone) : emptyMilestoneForm(currency)));
  const [values, setValues] = useState<MilestoneFormValues>(initial);
  const [errors, setErrors] = useState<MilestoneFormErrors>({});
  const dirty = !isSameMilestoneForm(values, initial);
  const editing = target.mode === "edit";

  function update<K extends keyof MilestoneFormValues>(key: K, value: MilestoneFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const found = validateMilestoneForm(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    onSubmit(values);
  }

  const currencyChoices = currencyOptions(values.currency).map((code) => ({ value: code, label: code }));

  return (
    <Dialog
      open
      onClose={onClose}
      title={editing ? "Edit payment milestone" : "New payment milestone"}
      eyebrow="Payment schedule"
      closeLabel="Close milestone form"
      size="md"
      busy={busy}
      dirty={dirty}
      footer={(close) => (
        <>
          <Button variant="secondary" onClick={close} disabled={busy}>
            Back
          </Button>
          <Button type="submit" form="payment-milestone-form" variant="primary" loading={busy} disabled={busy}>
            {editing ? "Save changes" : "Create milestone"}
          </Button>
        </>
      )}
    >
      <form id="payment-milestone-form" onSubmit={handleSubmit} noValidate>
        {serverError ? (
          <p className="df-sales-form-message df-sales-form-message--error" role="alert">
            {serverError}
          </p>
        ) : null}
        <div className="df-nested-form">
          <TextField
            label="Milestone name"
            required
            maxLength={150}
            value={values.name}
            onChange={(event) => update("name", event.target.value)}
            placeholder="e.g. Booking advance"
            disabled={busy}
            error={errors.name}
          />
          <div className="df-nested-form-row">
            <TextField
              label="Amount"
              required
              inputMode="decimal"
              value={values.amount}
              onChange={(event) => update("amount", event.target.value)}
              placeholder="e.g. 500000"
              helper="Up to two decimal places."
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
          </div>
          <TextField
            label="Due date and time"
            required
            type="datetime-local"
            value={values.dueAt}
            onChange={(event) => update("dueAt", event.target.value)}
            disabled={busy}
            error={errors.dueAt}
          />
          <TextareaField
            label="Notes"
            rows={3}
            maxLength={2000}
            value={values.notes}
            onChange={(event) => update("notes", event.target.value)}
            placeholder="Payment terms or other details"
            disabled={busy}
            error={errors.notes}
          />
        </div>
      </form>
    </Dialog>
  );
}

interface RecordPaymentDialogProps {
  milestone: PaymentMilestone;
  busy: boolean;
  serverError: string;
  onConfirm: (reference: string | null) => void;
  onClose: () => void;
}

function RecordPaymentDialog({ milestone, busy, serverError, onConfirm, onClose }: RecordPaymentDialogProps) {
  const [reference, setReference] = useState("");

  return (
    <Dialog
      open
      onClose={onClose}
      title="Record payment"
      eyebrow={milestone.name}
      closeLabel="Close record payment"
      size="sm"
      busy={busy}
      dirty={reference.trim().length > 0}
      footer={(close) => (
        <>
          <Button variant="secondary" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={busy} onClick={() => onConfirm(reference.trim() || null)}>
            Record payment
          </Button>
        </>
      )}
    >
      <dl className="df-nested-card-meta">
        <div>
          <dt>Amount due</dt>
          <dd>{formatMoney(milestone.amount, milestone.currency)}</dd>
        </div>
        <div>
          <dt>Due</dt>
          <dd>{formatDateTime(milestone.due_at)}</dd>
        </div>
      </dl>
      <p className="df-sales-muted">Confirm that the payment has been received before recording it. A paid milestone cannot be edited or cancelled.</p>
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

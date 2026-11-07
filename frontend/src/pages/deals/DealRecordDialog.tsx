import { useEffect, useState, type FormEvent } from "react";

import DealCommissionsPanel from "../../components/DealCommissionsPanel";
import PaymentMilestonesPanel from "../../components/PaymentMilestonesPanel";
import { RecordDialog, RecordProperty } from "../../components/record/RecordDialog";
import { Badge, Button, SelectField, TextField, TextareaField } from "../../components/ui";
import { ApiError } from "../../lib/api";
import type { Contact } from "../../services/contactApi";
import type { CustomerProfile } from "../../services/customerProfileApi";
import {
  dealNegotiationsApi,
  dealsApi,
  type Deal,
  type DealNegotiation,
  type DealStage,
  type NegotiationHistoryItem,
  type NegotiationState,
} from "../../services/dealApi";
import type { Lead } from "../../services/leadApi";
import type { Property } from "../../services/propertyApi";
import { formatShortDate } from "../sales/sales-shared";
import {
  NEGOTIATION_NOTES,
  NEGOTIATION_TRANSITIONS,
  NEXT_DEAL_STAGE,
  dealFieldsError,
  dealStageLabel,
  dealStageTone,
  expectedValueOrNull,
  formatDealAmount,
  dealCustomerName,
  dealPropertyTitle,
  leadOptionLabel,
  negotiationNeedsReason,
} from "./deal-workflow";

export interface DealLookups {
  customers: readonly CustomerProfile[];
  properties: readonly Property[];
  leads: readonly Lead[];
  contacts: readonly Contact[];
}

function describe(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

interface DealRecordDialogProps {
  deal: Deal;
  lookups: DealLookups;
  onClose: () => void;
  /** Called after a change so the grid refreshes. */
  onChanged: (message: string) => void;
}

/**
 * A deal record. The fields, stage, closing and negotiation sections keep the legacy page's endpoints and rules. Payment
 * milestones and commissions open the existing panels, unchanged.
 */
export default function DealRecordDialog({ deal, lookups, onClose, onChanged }: DealRecordDialogProps) {
  const customer = lookups.customers.find((item) => item.id === deal.customer_profile_id);
  const property = lookups.properties.find((item) => item.id === deal.property_id);
  const customerLabel = dealCustomerName(customer);
  const propertyLabel = dealPropertyTitle(property);
  const title = `${customerLabel} · ${propertyLabel}`;

  const [leadId, setLeadId] = useState(deal.lead_id ?? "");
  const [expectedValue, setExpectedValue] = useState(deal.expected_value == null ? "" : String(deal.expected_value));
  const [currency, setCurrency] = useState(deal.currency || "INR");
  const [notes, setNotes] = useState(deal.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const [transitionReason, setTransitionReason] = useState("");
  const [closing, setClosing] = useState(false);
  const [closureOutcome, setClosureOutcome] = useState<"CLOSED_WON" | "CLOSED_LOST">("CLOSED_WON");
  const [closureReason, setClosureReason] = useState("");

  const [negotiation, setNegotiation] = useState<DealNegotiation | null>(null);
  const [history, setHistory] = useState<NegotiationHistoryItem[]>([]);
  const [negotiationLoaded, setNegotiationLoaded] = useState(false);
  const [nextState, setNextState] = useState<NegotiationState>("IN_PROGRESS");
  const [notePreset, setNotePreset] = useState("");
  const [customNote, setCustomNote] = useState("");
  const [negotiationError, setNegotiationError] = useState("");

  const [milestonesOpen, setMilestonesOpen] = useState(false);
  const [commissionsOpen, setCommissionsOpen] = useState(false);

  const fieldsDirty =
    leadId !== (deal.lead_id ?? "") ||
    expectedValue !== (deal.expected_value == null ? "" : String(deal.expected_value)) ||
    currency.trim().toUpperCase() !== (deal.currency || "INR") ||
    notes !== (deal.notes ?? "");

  // Load the negotiation and its history once. A missing negotiation (404) simply means none has been started yet.
  useEffect(() => {
    let cancelled = false;
    dealNegotiationsApi
      .get(deal.id)
      .then(async (current) => {
        if (cancelled) return;
        setNegotiation(current);
        setNextState(current.state);
        try {
          const result = await dealNegotiationsApi.history(deal.id);
          if (!cancelled) setHistory(result.items);
        } catch {
          if (!cancelled) setNegotiationError("Negotiation loaded, but history could not be loaded.");
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (!(error instanceof ApiError && error.status === 404)) setNegotiationError(describe(error));
      })
      .finally(() => {
        if (!cancelled) setNegotiationLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [deal.id]);

  async function saveFields(event: FormEvent) {
    event.preventDefault();
    const rule = dealFieldsError(expectedValue, currency);
    if (rule) return setMessage(rule);
    setSaving(true);
    setMessage("");
    try {
      await dealsApi.update(deal.id, {
        lead_id: leadId || null,
        expected_value: expectedValueOrNull(expectedValue),
        currency: currency.trim().toUpperCase(),
        notes: notes.trim() || null,
      });
      onChanged("Deal updated successfully.");
    } catch (error) {
      setMessage(describe(error));
    } finally {
      setSaving(false);
    }
  }

  async function advanceStage(nextStage: DealStage) {
    setSaving(true);
    setMessage("");
    try {
      await dealsApi.transitionStage(deal.id, { stage: nextStage, reason: transitionReason.trim() || undefined });
      setTransitionReason("");
      onChanged(`Deal moved to ${dealStageLabel(nextStage)}.`);
    } catch (error) {
      setMessage(describe(error));
    } finally {
      setSaving(false);
    }
  }

  async function closeDeal(event: FormEvent) {
    event.preventDefault();
    const reason = closureReason.trim();
    if (!reason) return setMessage("Enter a reason for closing this deal.");
    if (reason.length > 2000) return setMessage("The closure reason must be 2,000 characters or fewer.");
    setSaving(true);
    setMessage("");
    try {
      await dealsApi.transitionStage(deal.id, { stage: closureOutcome, reason });
      setClosing(false);
      setClosureReason("");
      onChanged(`Deal closed as ${dealStageLabel(closureOutcome)}. The closure reason was recorded in deal history.`);
    } catch (error) {
      setMessage(describe(error));
    } finally {
      setSaving(false);
    }
  }

  function chosenNote(): string {
    return (notePreset === "CUSTOM" ? customNote : notePreset).trim();
  }

  async function refreshNegotiation(updated: DealNegotiation) {
    setNegotiation(updated);
    setNextState(updated.state);
    setNotePreset("");
    setCustomNote("");
    try {
      setHistory((await dealNegotiationsApi.history(deal.id)).items);
    } catch {
      setNegotiationError("The change was saved, but history could not be refreshed. Reopen the record to retry.");
    }
  }

  async function startNegotiation() {
    setSaving(true);
    setNegotiationError("");
    try {
      const created = await dealNegotiationsApi.create(deal.id, { state: "IN_PROGRESS", note: chosenNote() || undefined });
      await refreshNegotiation(created);
      onChanged("Negotiation started successfully.");
    } catch (error) {
      setNegotiationError(describe(error));
    } finally {
      setSaving(false);
    }
  }

  async function updateNegotiation() {
    if (!negotiation) return;
    if (nextState === negotiation.state) return setNegotiationError("Select a different negotiation state.");
    const note = chosenNote();
    if (negotiationNeedsReason(negotiation.state, nextState) && !note) {
      return setNegotiationError("Enter a reason for cancelling or reopening the negotiation.");
    }
    setSaving(true);
    setNegotiationError("");
    try {
      const updated = await dealNegotiationsApi.update(deal.id, { state: nextState, note: note || undefined });
      await refreshNegotiation(updated);
      onChanged("Negotiation updated successfully.");
    } catch (error) {
      setNegotiationError(describe(error));
    } finally {
      setSaving(false);
    }
  }

  const stage = deal.stage as keyof typeof NEXT_DEAL_STAGE;
  const nextStage = NEXT_DEAL_STAGE[stage];
  const canClose = deal.stage === "BOOKING";
  const allowedStates = negotiation ? NEGOTIATION_TRANSITIONS[negotiation.state] : [];
  const notePresets = negotiation ? NEGOTIATION_NOTES[nextState] ?? [] : [];

  return (
    <>
      <RecordDialog
        open
        onClose={onClose}
        eyebrow="Deal"
        title={title}
        closeLabel="Close deal"
        status={<Badge tone={dealStageTone(deal.stage)}>{dealStageLabel(deal.stage)}</Badge>}
        busy={saving}
        dirty={fieldsDirty}
        footer={
          <>
            <Button variant="secondary" onClick={onClose} disabled={saving}>
              Close
            </Button>
            <Button type="submit" form="deal-fields-form" variant="primary" disabled={!fieldsDirty} loading={saving}>
              Save changes
            </Button>
          </>
        }
        main={
          <div className="df-sales-form">
            {message ? (
              <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                {message}
              </p>
            ) : null}

            <form id="deal-fields-form" className="df-sales-section" onSubmit={saveFields} noValidate aria-label="Deal details">
              <h3 className="df-sales-section-title">Deal details</h3>
              <div className="df-sales-form-grid">
                <TextField label="Customer" value={customerLabel} readOnly />
                <TextField label="Property" value={propertyLabel} readOnly />
                <SelectField
                  label="Lead"
                  value={leadId}
                  disabled={saving}
                  options={[{ value: "", label: "Not linked" }, ...lookups.leads.map((lead) => ({ value: lead.id, label: leadOptionLabel(lead, lookups.contacts) }))]}
                  onChange={(event) => setLeadId(event.target.value)}
                />
                <TextField label="Expected value" type="number" min="0" value={expectedValue} disabled={saving} onChange={(event) => setExpectedValue(event.target.value)} />
                <TextField label="Currency" value={currency} maxLength={3} disabled={saving} onChange={(event) => setCurrency(event.target.value)} />
              </div>
              <TextareaField label="Notes" rows={3} value={notes} disabled={saving} onChange={(event) => setNotes(event.target.value)} />
            </form>

            <section className="df-sales-section" aria-label="Stage">
              <h3 className="df-sales-section-title">Stage</h3>
              {nextStage ? (
                <div className="df-sales-form-grid">
                  <TextField label="Reason (optional)" value={transitionReason} disabled={saving} onChange={(event) => setTransitionReason(event.target.value)} />
                  <div className="df-sales-form-actions">
                    <Button variant="secondary" size="sm" disabled={saving} onClick={() => void advanceStage(nextStage)}>
                      Move to {dealStageLabel(nextStage)}
                    </Button>
                  </div>
                </div>
              ) : null}
              {canClose && !closing ? (
                <div className="df-sales-form-actions">
                  <Button variant="primary" size="sm" disabled={saving} onClick={() => setClosing(true)}>
                    Close deal
                  </Button>
                </div>
              ) : null}
              {closing ? (
                <form className="df-sales-form-grid" onSubmit={closeDeal} noValidate aria-label="Close deal">
                  <SelectField
                    label="Outcome"
                    value={closureOutcome}
                    disabled={saving}
                    options={[
                      { value: "CLOSED_WON", label: "Closed won" },
                      { value: "CLOSED_LOST", label: "Closed lost" },
                    ]}
                    onChange={(event) => setClosureOutcome(event.target.value as "CLOSED_WON" | "CLOSED_LOST")}
                  />
                  <TextareaField label="Reason for closing" required rows={3} value={closureReason} disabled={saving} onChange={(event) => setClosureReason(event.target.value)} />
                  <div className="df-sales-form-actions">
                    <Button variant="secondary" size="sm" disabled={saving} onClick={() => setClosing(false)}>
                      Cancel
                    </Button>
                    <Button type="submit" variant="primary" size="sm" loading={saving}>
                      Save closure
                    </Button>
                  </div>
                </form>
              ) : null}
            </section>

            <section className="df-sales-section" aria-label="Negotiation">
              <h3 className="df-sales-section-title">Negotiation</h3>
              {!negotiationLoaded ? <p className="df-sales-muted">Loading negotiation…</p> : null}
              {negotiationLoaded && !negotiation ? (
                <div className="df-sales-form-actions">
                  <Button variant="secondary" size="sm" disabled={saving} onClick={() => void startNegotiation()}>
                    Start negotiation
                  </Button>
                </div>
              ) : null}
              {negotiation ? (
                <div className="df-sales-form-grid">
                  <SelectField
                    label="State"
                    value={nextState}
                    disabled={saving}
                    options={[negotiation.state, ...allowedStates].map((state) => ({ value: state, label: dealStageLabel(state) }))}
                    onChange={(event) => setNextState(event.target.value as NegotiationState)}
                  />
                  <SelectField
                    label="Note"
                    value={notePreset}
                    disabled={saving}
                    options={[{ value: "", label: "No note" }, ...notePresets.map((note) => ({ value: note, label: note })), { value: "CUSTOM", label: "Custom note" }]}
                    onChange={(event) => setNotePreset(event.target.value)}
                  />
                  {notePreset === "CUSTOM" ? <TextField label="Custom note" value={customNote} disabled={saving} onChange={(event) => setCustomNote(event.target.value)} /> : null}
                  <div className="df-sales-form-actions">
                    <Button variant="primary" size="sm" disabled={saving || nextState === negotiation.state} onClick={() => void updateNegotiation()}>
                      Update negotiation
                    </Button>
                  </div>
                </div>
              ) : null}
              {negotiationError ? (
                <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                  {negotiationError}
                </p>
              ) : null}
              {history.length > 0 ? (
                <ul className="df-sales-followup-list" aria-label="Negotiation history">
                  {history.slice(0, 8).map((item) => (
                    <li key={item.id} className="df-sales-followup">
                      <strong>{item.from_state ? `${dealStageLabel(item.from_state)} → ` : ""}{dealStageLabel(item.to_state)}</strong>
                      <span className="df-sales-muted">
                        {formatShortDate(item.created_at)}
                        {item.note ? ` · ${item.note}` : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>

            <section className="df-sales-section" aria-label="Payments and commissions">
              <h3 className="df-sales-section-title">Payments and commissions</h3>
              <div className="df-sales-form-actions">
                <Button variant="secondary" size="sm" onClick={() => setMilestonesOpen(true)}>
                  Payment milestones
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setCommissionsOpen(true)}>
                  Commissions
                </Button>
              </div>
            </section>
          </div>
        }
        aside={
          <dl className="df-sales-properties">
            <RecordProperty label="Stage">
              <Badge tone={dealStageTone(deal.stage)}>{dealStageLabel(deal.stage)}</Badge>
            </RecordProperty>
            <RecordProperty label="Owner">{deal.owner_name ?? "Unassigned"}</RecordProperty>
            <RecordProperty label="Expected value">{formatDealAmount(deal.expected_value, deal.currency)}</RecordProperty>
            <RecordProperty label="Created">{formatShortDate(deal.created_at)}</RecordProperty>
            <RecordProperty label="Last updated">{formatShortDate(deal.updated_at)}</RecordProperty>
          </dl>
        }
      />

      {milestonesOpen ? <PaymentMilestonesPanel dealId={deal.id} dealTitle={title} onClose={() => setMilestonesOpen(false)} /> : null}
      {commissionsOpen ? (
        <DealCommissionsPanel dealId={deal.id} dealTitle={title} dealValue={deal.expected_value} currency={deal.currency || "INR"} onClose={() => setCommissionsOpen(false)} />
      ) : null}
    </>
  );
}

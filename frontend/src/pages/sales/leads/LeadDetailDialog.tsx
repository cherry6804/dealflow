import { useState, type FormEvent } from "react";

import LeadTimeline from "../../../components/LeadTimeline";
import { RecordDetailDialog, RecordProperty } from "../../../components/record/RecordDetailDialog";
import { Badge, Button, SelectField, TextField } from "../../../components/ui";
import { toIsoDateTime, toLocalDateTimeInput } from "../../../lib/dateTimeInput";
import type { Contact } from "../../../services/contactApi";
import { leadsApi, type Lead, type LeadInterest, type LeadStatus } from "../../../services/leadApi";
import { contactDisplayName, formatDateTime, formatShortDate, messageFrom } from "../sales-shared";
import LeadFollowUpsDialog from "./LeadFollowUpsDialog";
import { ALLOWED_STATUS_TRANSITIONS, LEAD_INTERESTS, availableStatuses, formatStageLabel, needsNextActionPrompt, outcomeForStatusChange, stageTone } from "./lead-workflow";

interface LeadDetailDialogProps {
  lead: Lead;
  contact: Contact | undefined;
  /** Display name of the owner, or null when the owner is not assigned. */
  ownerName: string | null;
  onClose: () => void;
  /** Called with the saved lead after each change, so the parent list stays current. */
  onLeadChanged: (lead: Lead) => void;
  /** Called with a short confirmation after a successful change. */
  onNotice: (message: string) => void;
  /** Called after follow-up changes, so the list can refresh next-follow-up values. */
  onFollowUpsChanged: () => void;
  /** Stage the user asked for before opening the record, such as a board drop. The next-action prompt opens for it when needed. */
  initialStage?: LeadStatus;
}

/**
 * The lead record: contact details, stage, interest, next follow-up, activation, follow-ups and timeline. Stage moves follow
 * the existing allowed transitions, and a key stage asks for a next action first when the lead has none. Every change uses the
 * existing leads endpoints. Used by the Leads grid and by the Pipeline board cards.
 */
export default function LeadDetailDialog({
  lead,
  contact,
  ownerName,
  onClose,
  onLeadChanged,
  onNotice,
  onFollowUpsChanged,
  initialStage,
}: LeadDetailDialogProps) {
  const name = contactDisplayName(contact);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [pendingStage, setPendingStage] = useState<LeadStatus | null>(() =>
    initialStage && initialStage !== lead.status && needsNextActionPrompt(lead, initialStage) ? initialStage : null,
  );
  const [promptAction, setPromptAction] = useState("");
  const [promptDate, setPromptDate] = useState("");
  const [promptError, setPromptError] = useState("");
  const [nextAction, setNextAction] = useState(lead.next_action ?? "");
  const [nextActionDate, setNextActionDate] = useState(toLocalDateTimeInput(lead.next_action_at));
  const [nextActionError, setNextActionError] = useState("");
  const [followUpsOpen, setFollowUpsOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);

  async function applyUpdate(payload: Parameters<typeof leadsApi.update>[1], confirmation: string): Promise<Lead | null> {
    setSaving(true);
    setMessage("");
    try {
      const updated = await leadsApi.update(lead.id, payload);
      onLeadChanged(updated);
      setNextAction(updated.next_action ?? "");
      setNextActionDate(toLocalDateTimeInput(updated.next_action_at));
      onNotice(confirmation);
      return updated;
    } catch (error) {
      setMessage(messageFrom(error, "The lead could not be updated. Try again."));
      return null;
    } finally {
      setSaving(false);
    }
  }

  function chooseStage(next: LeadStatus) {
    if (next === lead.status || !ALLOWED_STATUS_TRANSITIONS[lead.status].includes(next)) return;
    if (needsNextActionPrompt(lead, next)) {
      // Ask for the next action before moving the lead into a key stage, as the Leads page always has.
      setPendingStage(next);
      setPromptAction("");
      setPromptDate("");
      setPromptError("");
      return;
    }
    const outcome = outcomeForStatusChange(lead.status, next);
    void applyUpdate(outcome === undefined ? { status: next } : { status: next, outcome }, `Stage updated to ${formatStageLabel(next)}.`);
  }

  async function submitStagePrompt(event: FormEvent) {
    event.preventDefault();
    if (!pendingStage) return;
    const action = promptAction.trim();
    if (!action) {
      setPromptError("Enter the next action before continuing.");
      return;
    }
    if (promptDate && !toIsoDateTime(promptDate)) {
      setPromptError("Enter a valid next-action date and time.");
      return;
    }
    const outcome = outcomeForStatusChange(lead.status, pendingStage);
    setSaving(true);
    setPromptError("");
    try {
      const updated = await leadsApi.update(lead.id, {
        status: pendingStage,
        next_action: action,
        next_action_at: toIsoDateTime(promptDate),
        ...(outcome === undefined ? {} : { outcome }),
      });
      onLeadChanged(updated);
      setNextAction(updated.next_action ?? "");
      setNextActionDate(toLocalDateTimeInput(updated.next_action_at));
      setPendingStage(null);
      onNotice(`Stage updated to ${formatStageLabel(pendingStage)} and next action saved.`);
    } catch (error) {
      setPromptError(messageFrom(error, "The lead could not be updated. Try again."));
    } finally {
      setSaving(false);
    }
  }

  async function saveNextAction(event: FormEvent) {
    event.preventDefault();
    const action = nextAction.trim();
    if (nextActionDate && !action) {
      setNextActionError("Enter a next action when scheduling a date.");
      return;
    }
    setNextActionError("");
    await applyUpdate(
      { next_action: action || null, next_action_at: toIsoDateTime(nextActionDate) },
      "Next action and follow-up updated successfully.",
    );
  }

  async function changeInterest(value: string) {
    const interest = value ? (value as LeadInterest) : null;
    if (interest === lead.interest) return;
    await applyUpdate({ interest }, "Lead interest updated successfully.");
  }

  async function toggleActive() {
    await applyUpdate({ is_active: !lead.is_active }, lead.is_active ? "Lead marked inactive." : "Lead reactivated successfully.");
  }

  const nextActionDirty = nextAction.trim() !== (lead.next_action ?? "").trim() || nextActionDate !== toLocalDateTimeInput(lead.next_action_at);

  return (
    <>
      <RecordDetailDialog
        open
        onClose={onClose}
        eyebrow="Lead"
        title={name}
        closeLabel="Close lead"
        main={
          <div className="df-sales-form">
            <div className="df-sales-form-grid">
              <TextField label="Name" value={name} readOnly helper="Edit the name on the contact record." />
              <TextField label="Email address" value={contact?.email ?? ""} readOnly />
              <TextField label="Phone" value={contact?.phone ?? ""} readOnly />
              <SelectField
                label="Stage"
                value={lead.status}
                disabled={saving || !lead.is_active}
                options={availableStatuses(lead.status).map((stage) => ({ value: stage, label: formatStageLabel(stage) }))}
                onChange={(event) => chooseStage(event.target.value as LeadStatus)}
              />
              <SelectField
                label="Interest"
                value={lead.interest ?? ""}
                disabled={saving || !lead.is_active}
                options={[{ value: "", label: "Not set" }, ...LEAD_INTERESTS.map((level) => ({ value: level, label: formatStageLabel(level) }))]}
                onChange={(event) => void changeInterest(event.target.value)}
              />
            </div>

            {pendingStage ? (
              <form className="df-sales-section" onSubmit={submitStagePrompt} noValidate aria-label="Next action required">
                <h3 className="df-sales-section-title">Add a next action to move to {formatStageLabel(pendingStage)}</h3>
                <div className="df-sales-form-grid">
                  <TextField label="Next action" required value={promptAction} onChange={(event) => setPromptAction(event.target.value)} />
                  <TextField label="Next action date" type="datetime-local" value={promptDate} onChange={(event) => setPromptDate(event.target.value)} />
                </div>
                {promptError ? (
                  <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                    {promptError}
                  </p>
                ) : null}
                <div className="df-sales-form-actions">
                  <Button variant="secondary" onClick={() => setPendingStage(null)} disabled={saving}>
                    Cancel
                  </Button>
                  <Button type="submit" variant="primary" loading={saving}>
                    Save and move stage
                  </Button>
                </div>
              </form>
            ) : null}

            <form className="df-sales-section" onSubmit={saveNextAction} noValidate>
              <h3 className="df-sales-section-title">Next follow-up</h3>
              <div className="df-sales-form-grid">
                <TextField
                  label="Next action"
                  value={nextAction}
                  disabled={!lead.is_active}
                  error={nextActionError || undefined}
                  onChange={(event) => setNextAction(event.target.value)}
                />
                <TextField
                  label="Next action date"
                  type="datetime-local"
                  value={nextActionDate}
                  disabled={!lead.is_active}
                  onChange={(event) => setNextActionDate(event.target.value)}
                />
              </div>
              <div className="df-sales-form-actions">
                {message ? (
                  <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                    {message}
                  </p>
                ) : null}
                <Button type="submit" variant="primary" disabled={!lead.is_active || !nextActionDirty} loading={saving}>
                  Save next action
                </Button>
              </div>
            </form>
          </div>
        }
        aside={
          <>
            <dl className="df-sales-properties">
              <RecordProperty label="Stage">
                <Badge tone={stageTone(lead.status)}>{formatStageLabel(lead.status)}</Badge>
              </RecordProperty>
              <RecordProperty label="Active">{lead.is_active ? "Yes" : "No"}</RecordProperty>
              <RecordProperty label="Owner">{ownerName ?? (lead.owner_user_id ? "Unnamed owner" : "Unassigned")}</RecordProperty>
              <RecordProperty label="Next follow-up">{lead.next_action_at ? formatDateTime(lead.next_action_at) : "Not scheduled"}</RecordProperty>
              <RecordProperty label="Created">{formatShortDate(lead.created_at)}</RecordProperty>
              <RecordProperty label="Last updated">{formatShortDate(lead.updated_at)}</RecordProperty>
            </dl>
            <div className="df-sales-aside-actions">
              <Button variant="secondary" size="sm" onClick={() => setFollowUpsOpen(true)} disabled={!lead.is_active}>
                Manage follow-ups
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setTimelineOpen(true)}>
                View timeline
              </Button>
              <Button variant="secondary" size="sm" onClick={() => void toggleActive()} disabled={saving}>
                {lead.is_active ? "Mark lead inactive" : "Reactivate lead"}
              </Button>
            </div>
          </>
        }
      />

      {followUpsOpen ? (
        <LeadFollowUpsDialog
          open
          leadId={lead.id}
          leadName={name}
          onClose={() => setFollowUpsOpen(false)}
          onChanged={onFollowUpsChanged}
        />
      ) : null}

      {timelineOpen ? <LeadTimeline leadId={lead.id} contactName={name} onClose={() => setTimelineOpen(false)} /> : null}
    </>
  );
}

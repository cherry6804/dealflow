import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Badge, Button, Dialog, SelectField, TextField, TextareaField } from "../../../components/ui";
import { toIsoDateTime, toLocalDateTimeInput } from "../../../lib/dateTimeInput";
import { followUpsApi, type FollowUp, type FollowUpType } from "../../../services/followUpApi";
import { formatDateTime, messageFrom } from "../sales-shared";

const FOLLOW_UP_TYPES: readonly { value: FollowUpType; label: string }[] = [
  { value: "CALL", label: "Call" },
  { value: "EMAIL", label: "Email" },
  { value: "MEETING", label: "Meeting" },
  { value: "VISIT", label: "Visit" },
  { value: "TASK", label: "Task" },
  { value: "OTHER", label: "Other" },
];

interface LeadFollowUpsDialogProps {
  open: boolean;
  leadId: string;
  leadName: string;
  onClose: () => void;
  /** Called after a change, so the grid can show the new next follow-up. */
  onChanged: () => void;
}

/**
 * Follow-ups for one lead: create, complete and reschedule one at a time, and complete or reschedule several pending items at
 * once. Uses the existing follow-up endpoints and the same validation as the legacy Leads page.
 */
export default function LeadFollowUpsDialog({ open, leadId, leadName, onClose, onChanged }: LeadFollowUpsDialogProps) {
  const [followUps, setFollowUps] = useState<FollowUp[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkDue, setBulkDue] = useState("");
  const [rescheduleId, setRescheduleId] = useState<string | null>(null);
  const [rescheduleDue, setRescheduleDue] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [type, setType] = useState<FollowUpType>("CALL");
  const [dueAt, setDueAt] = useState(() => toLocalDateTimeInput(new Date().toISOString()));

  const loadFollowUps = useCallback(async () => {
    setLoading(true);
    try {
      const all = await followUpsApi.list();
      setFollowUps(all.filter((item) => item.lead_id === leadId));
      setError("");
    } catch (loadError) {
      setError(messageFrom(loadError, "Follow-ups could not be loaded. Try again."));
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  // Load when the dialog opens for a lead. Results arrive asynchronously, so no state is set synchronously in the effect body.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    followUpsApi
      .list()
      .then((all) => {
        if (cancelled) return;
        setFollowUps(all.filter((item) => item.lead_id === leadId));
        setError("");
      })
      .catch((loadError: unknown) => {
        if (!cancelled) setError(messageFrom(loadError, "Follow-ups could not be loaded. Try again."));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, leadId]);

  const pending = followUps.filter((item) => item.status === "PENDING");
  const selectedPending = pending.filter((item) => selectedIds.includes(item.id)).map((item) => item.id);

  function toggleSelected(id: string) {
    setSelectedIds((current) => (current.includes(id) ? current.filter((value) => value !== id) : [...current, id]));
  }

  function showBulkResult(result: { succeeded: number; failed: number; results: { success: boolean; message: string; follow_up_id: string }[] }, action: string) {
    setSuccess(`${result.succeeded} follow-up(s) ${action} successfully; ${result.failed} failed.`);
    if (result.failed > 0) {
      setError(result.results.filter((item) => !item.success).map((item) => item.message).join(" "));
    }
    setSelectedIds((current) => current.filter((id) => !result.results.some((item) => item.follow_up_id === id && item.success)));
  }

  async function createFollowUp(event: FormEvent) {
    event.preventDefault();
    const trimmedTitle = title.trim();
    const due = toIsoDateTime(dueAt);
    if (!trimmedTitle) {
      setError("Enter a title for the follow-up.");
      return;
    }
    if (!due) {
      setError("Enter a valid follow-up date and time.");
      return;
    }
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      await followUpsApi.create(leadId, {
        follow_up_type: type,
        title: trimmedTitle,
        description: description.trim() || null,
        due_at: due,
      });
      setTitle("");
      setDescription("");
      setType("CALL");
      setSuccess("Follow-up created successfully.");
      await loadFollowUps();
      onChanged();
    } catch (createError) {
      setError(messageFrom(createError, "The follow-up could not be created. Try again."));
    } finally {
      setSaving(false);
    }
  }

  async function completeFollowUp(item: FollowUp) {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      await followUpsApi.complete(item.id);
      setSuccess("Follow-up marked as completed.");
      await loadFollowUps();
      onChanged();
    } catch (completeError) {
      setError(messageFrom(completeError, "The follow-up could not be completed. Try again."));
    } finally {
      setSaving(false);
    }
  }

  async function rescheduleFollowUp(item: FollowUp) {
    const due = toIsoDateTime(rescheduleDue);
    if (!due) {
      setError("Enter a valid new date and time.");
      return;
    }
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      await followUpsApi.reschedule(item.id, { due_at: due });
      setRescheduleId(null);
      setRescheduleDue("");
      setSuccess("Follow-up rescheduled successfully.");
      await loadFollowUps();
      onChanged();
    } catch (rescheduleError) {
      setError(messageFrom(rescheduleError, "The follow-up could not be rescheduled. Try again."));
    } finally {
      setSaving(false);
    }
  }

  async function completeSelected() {
    if (selectedPending.length === 0) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const result = await followUpsApi.bulkComplete({ follow_up_ids: selectedPending });
      showBulkResult(result, "completed");
      await loadFollowUps();
      onChanged();
    } catch (bulkError) {
      setError(messageFrom(bulkError, "The follow-ups could not be completed. Try again."));
    } finally {
      setSaving(false);
    }
  }

  async function rescheduleSelected() {
    const due = toIsoDateTime(bulkDue);
    if (!due) {
      setError("Enter a valid bulk reschedule date and time.");
      return;
    }
    if (selectedPending.length === 0) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const result = await followUpsApi.bulkReschedule({ follow_up_ids: selectedPending, due_at: due });
      showBulkResult(result, "rescheduled");
      setBulkDue("");
      await loadFollowUps();
      onChanged();
    } catch (bulkError) {
      setError(messageFrom(bulkError, "The follow-ups could not be rescheduled. Try again."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Follow-ups" closeLabel="Close follow-ups" description={leadName} size="lg">
      <div className="df-sales-form">
        {error ? (
          <p className="df-sales-form-message df-sales-form-message--error" role="alert">
            {error}
          </p>
        ) : null}
        {success ? (
          <p className="df-sales-form-message" role="status">
            {success}
          </p>
        ) : null}

        <section aria-labelledby="lead-followups-list-title" className="df-sales-section">
          <h3 id="lead-followups-list-title" className="df-sales-section-title">
            Scheduled follow-ups
          </h3>
          {loading ? (
            <p className="df-sales-form-message" role="status">
              Loading follow-ups…
            </p>
          ) : followUps.length === 0 ? (
            <p className="df-sales-form-message">No follow-ups yet for this lead.</p>
          ) : (
            <ul className="df-sales-followup-list">
              {followUps.map((item) => (
                <li key={item.id} className="df-sales-followup">
                  <div className="df-sales-followup-main">
                    {item.status === "PENDING" ? (
                      <input
                        type="checkbox"
                        aria-label={`Select follow-up ${item.title}`}
                        checked={selectedIds.includes(item.id)}
                        onChange={() => toggleSelected(item.id)}
                        disabled={saving}
                      />
                    ) : null}
                    <div>
                      <strong>{item.title}</strong>
                      <span className="df-sales-muted">
                        {FOLLOW_UP_TYPES.find((option) => option.value === item.follow_up_type)?.label ?? item.follow_up_type} · due{" "}
                        {formatDateTime(item.due_at)}
                      </span>
                      {item.description ? <p className="df-sales-muted">{item.description}</p> : null}
                    </div>
                    <Badge tone={item.status === "PENDING" ? "pending" : item.status === "COMPLETED" ? "success" : "neutral"}>
                      {item.status === "PENDING" ? "Pending" : item.status === "COMPLETED" ? "Completed" : "Cancelled"}
                    </Badge>
                  </div>
                  {item.status === "PENDING" ? (
                    <div className="df-sales-followup-actions">
                      {rescheduleId === item.id ? (
                        <>
                          <TextField
                            label="New date and time"
                            type="datetime-local"
                            value={rescheduleDue}
                            onChange={(event) => setRescheduleDue(event.target.value)}
                          />
                          <Button size="sm" variant="secondary" onClick={() => setRescheduleId(null)} disabled={saving}>
                            Cancel
                          </Button>
                          <Button size="sm" variant="primary" onClick={() => void rescheduleFollowUp(item)} loading={saving}>
                            Save new time
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => {
                              setRescheduleId(item.id);
                              setRescheduleDue(toLocalDateTimeInput(item.due_at));
                            }}
                            disabled={saving}
                          >
                            Reschedule
                          </Button>
                          <Button size="sm" variant="primary" onClick={() => void completeFollowUp(item)} disabled={saving}>
                            Mark complete
                          </Button>
                        </>
                      )}
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          )}

          {selectedPending.length > 0 ? (
            <div className="df-sales-bulk">
              <p className="df-sales-muted">{selectedPending.length} selected</p>
              <div className="df-sales-followup-actions">
                <Button size="sm" variant="primary" onClick={() => void completeSelected()} disabled={saving}>
                  Complete selected
                </Button>
                <TextField label="Reschedule selected to" type="datetime-local" value={bulkDue} onChange={(event) => setBulkDue(event.target.value)} />
                <Button size="sm" variant="secondary" onClick={() => void rescheduleSelected()} disabled={saving}>
                  Reschedule selected
                </Button>
              </div>
            </div>
          ) : null}
        </section>

        <form className="df-sales-section" onSubmit={createFollowUp} noValidate>
          <h3 className="df-sales-section-title">Add a follow-up</h3>
          <div className="df-sales-form-grid">
            <TextField label="Title" required value={title} onChange={(event) => setTitle(event.target.value)} />
            <SelectField
              label="Type"
              value={type}
              options={FOLLOW_UP_TYPES.map((option) => ({ value: option.value, label: option.label }))}
              onChange={(event) => setType(event.target.value as FollowUpType)}
            />
            <TextField label="Due" required type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} />
            <TextareaField label="Notes" rows={2} value={description} onChange={(event) => setDescription(event.target.value)} />
          </div>
          <div className="df-sales-form-actions">
            <Button type="submit" variant="primary" loading={saving}>
              Add follow-up
            </Button>
          </div>
        </form>
      </div>
    </Dialog>
  );
}

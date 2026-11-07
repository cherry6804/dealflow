import { useState, type FormEvent } from "react";

import { Button, Dialog, SelectField, TextareaField, TextField } from "../../../components/ui";
import type { CustomerProfile } from "../../../services/customerProfileApi";
import { followUpsApi, type FollowUpType } from "../../../services/followUpApi";
import type { Lead } from "../../../services/leadApi";
import type { Property } from "../../../services/propertyApi";
import { siteVisitsApi, type SiteVisit, type SiteVisitOutcome, type SiteVisitStatus } from "../../../services/siteVisitApi";
import { messageFrom, personName } from "../sales-shared";
import { SITE_VISIT_OUTCOMES, propertyLabel, toLocalInput } from "./site-visit-labels";

type VisitPerson = "lead" | "customer";

const FOLLOW_UP_TYPES: readonly { value: FollowUpType; label: string }[] = [
  { value: "CALL", label: "Call" },
  { value: "EMAIL", label: "Email" },
  { value: "MEETING", label: "Meeting" },
  { value: "VISIT", label: "Visit" },
  { value: "TASK", label: "Task" },
  { value: "OTHER", label: "Other" },
];

export interface VisitOptions {
  properties: readonly Property[];
  leads: readonly Lead[];
  customers: readonly CustomerProfile[];
}

interface ScheduleProps extends VisitOptions {
  /** Name shown for a lead, typically its contact's name. */
  leadLabel: (lead: Lead) => string;
  onClose: () => void;
  onSaved: (message: string) => void;
}

/** Schedule a visit for a property, linked to a lead or a customer. Validation matches the Site Visits page. */
export function ScheduleVisitDialog({ properties, leads, customers, leadLabel, onClose, onSaved }: ScheduleProps) {
  const [propertyId, setPropertyId] = useState("");
  const [person, setPerson] = useState<VisitPerson>("lead");
  const [leadId, setLeadId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [scheduledAt, setScheduledAt] = useState(() => {
    const date = new Date();
    date.setDate(date.getDate() + 1);
    date.setHours(10, 0, 0, 0);
    return toLocalInput(date);
  });
  const [endsAt, setEndsAt] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!propertyId) return setError("Select a property before scheduling the visit.");
    if (person === "lead" && !leadId) return setError("Select a lead for this visit.");
    if (person === "customer" && !customerId) return setError("Select a customer for this visit.");
    const start = new Date(scheduledAt);
    const end = endsAt ? new Date(endsAt) : null;
    if (Number.isNaN(start.getTime())) return setError("Enter a valid visit date and time.");
    if (end && (Number.isNaN(end.getTime()) || end <= start)) return setError("The end time must be later than the start time.");

    setSaving(true);
    try {
      await siteVisitsApi.schedule({
        property_id: propertyId,
        lead_id: person === "lead" ? leadId : null,
        customer_profile_id: person === "customer" ? customerId : null,
        scheduled_at: start.toISOString(),
        ends_at: end?.toISOString() ?? null,
        notes: notes.trim() || null,
      });
      onSaved("Site visit scheduled successfully.");
    } catch (saveError) {
      setError(messageFrom(saveError, "The visit could not be scheduled. Try again."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Schedule a site visit"
      closeLabel="Close schedule visit"
      description="Choose the property, the person visiting, and the time."
      busy={saving}
      dirty={Boolean(propertyId || leadId || customerId || notes.trim())}
      footer={(close) => (
        <>
          <Button variant="secondary" onClick={close} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="schedule-visit-form" variant="primary" loading={saving}>
            Schedule visit
          </Button>
        </>
      )}
    >
      <form id="schedule-visit-form" className="df-sales-form" onSubmit={submit} noValidate>
        <div className="df-sales-form-grid">
          <SelectField
            label="Property"
            required
            value={propertyId}
            disabled={saving || properties.length === 0}
            helper={properties.length === 0 ? "No properties are available to visit." : undefined}
            options={[{ value: "", label: "Select a property" }, ...properties.map((property) => ({ value: property.id, label: propertyLabel(property, property.id) }))]}
            onChange={(event) => setPropertyId(event.target.value)}
          />
          <SelectField
            label="Visiting"
            value={person}
            disabled={saving}
            options={[
              { value: "lead", label: "A lead" },
              { value: "customer", label: "A customer" },
            ]}
            onChange={(event) => setPerson(event.target.value as VisitPerson)}
          />
          {person === "lead" ? (
            <SelectField
              label="Lead"
              required
              value={leadId}
              disabled={saving}
              options={[
                { value: "", label: "Select a lead" },
                ...leads.map((lead) => ({ value: lead.id, label: `${leadLabel(lead)} · ${lead.status.replace(/_/g, " ").toLowerCase()}` })),
              ]}
              onChange={(event) => setLeadId(event.target.value)}
            />
          ) : (
            <SelectField
              label="Customer"
              required
              value={customerId}
              disabled={saving}
              options={[
                { value: "", label: "Select a customer" },
                ...customers.map((customer) => ({
                  value: customer.id,
                  label: personName(customer.contact) || customer.contact.email || "Unnamed customer",
                })),
              ]}
              onChange={(event) => setCustomerId(event.target.value)}
            />
          )}
          <TextField label="Starts" type="datetime-local" required value={scheduledAt} disabled={saving} onChange={(event) => setScheduledAt(event.target.value)} />
          <TextField label="Ends (optional)" type="datetime-local" value={endsAt} disabled={saving} onChange={(event) => setEndsAt(event.target.value)} />
          <TextareaField label="Notes" rows={3} value={notes} disabled={saving} onChange={(event) => setNotes(event.target.value)} />
        </div>
          {error ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              {error}
            </p>
          ) : null}
      </form>
    </Dialog>
  );
}

interface AttendanceProps {
  visit: SiteVisit;
  onClose: () => void;
  onSaved: (message: string) => void;
}

/** Record how a visit went: completed, cancelled or no show, with an outcome and feedback when it was completed. */
export function AttendanceDialog({ visit, onClose, onSaved }: AttendanceProps) {
  const [status, setStatus] = useState<Exclude<SiteVisitStatus, "SCHEDULED">>("COMPLETED");
  const [outcome, setOutcome] = useState<SiteVisitOutcome | "">(visit.outcome ?? "");
  const [feedback, setFeedback] = useState(visit.feedback ?? "");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (status !== "COMPLETED" && outcome) return setError("An outcome can only be recorded when the visit is completed.");
    setSaving(true);
    try {
      await siteVisitsApi.recordAttendance(visit.id, {
        status,
        outcome: status === "COMPLETED" ? outcome || null : null,
        feedback: feedback.trim() || null,
      });
      onSaved("Site visit attendance recorded successfully.");
    } catch (saveError) {
      setError(messageFrom(saveError, "Attendance could not be recorded. Try again."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Record attendance"
      closeLabel="Close attendance"
      description={visitDescription(visit)}
      busy={saving}
      dirty={outcome !== (visit.outcome ?? "") || feedback !== (visit.feedback ?? "")}
      footer={(close) => (
        <>
          <Button variant="secondary" onClick={close} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="attendance-form" variant="primary" loading={saving}>
            Save attendance
          </Button>
        </>
      )}
    >
      <form id="attendance-form" className="df-sales-form" onSubmit={submit} noValidate>
        <div className="df-sales-form-grid">
          <SelectField
            label="Attendance"
            value={status}
            disabled={saving}
            options={[
              { value: "COMPLETED", label: "Completed" },
              { value: "CANCELLED", label: "Cancelled" },
              { value: "NO_SHOW", label: "No show" },
            ]}
            onChange={(event) => setStatus(event.target.value as Exclude<SiteVisitStatus, "SCHEDULED">)}
          />
          <SelectField
            label="Outcome"
            value={outcome}
            disabled={saving || status !== "COMPLETED"}
            helper={status === "COMPLETED" ? undefined : "Outcomes are recorded for completed visits only."}
            options={[{ value: "", label: "No outcome yet" }, ...SITE_VISIT_OUTCOMES.map((item) => ({ value: item.value, label: item.label }))]}
            onChange={(event) => setOutcome(event.target.value as SiteVisitOutcome | "")}
          />
          <TextareaField label="Feedback" rows={4} value={feedback} disabled={saving} onChange={(event) => setFeedback(event.target.value)} />
        </div>
          {error ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              {error}
            </p>
          ) : null}
      </form>
    </Dialog>
  );
}

interface FollowUpProps {
  visit: SiteVisit;
  onClose: () => void;
  onSaved: (message: string) => void;
}

/** A follow-up for a visit. The visit must be linked to a lead, and the due time must be in the future. */
export function VisitFollowUpDialog({ visit, onClose, onSaved }: FollowUpProps) {
  const [type, setType] = useState<FollowUpType>("CALL");
  const [title, setTitle] = useState("Follow up after site visit");
  const [description, setDescription] = useState("");
  const [dueAt, setDueAt] = useState(() => {
    const date = new Date();
    date.setDate(date.getDate() + 1);
    date.setHours(10, 0, 0, 0);
    return toLocalInput(date);
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (!visit.lead_id) return setError("A linked lead is required to create this follow-up.");
    const due = new Date(dueAt);
    if (Number.isNaN(due.getTime())) return setError("Enter a valid follow-up date and time.");
    if (due.getTime() <= Date.now()) return setError("The follow-up must be scheduled in the future.");
    if (!title.trim()) return setError("Enter a follow-up title.");
    setSaving(true);
    try {
      const created = await followUpsApi.createFromSiteVisit(visit.id, {
        follow_up_type: type,
        title: title.trim(),
        description: description.trim() || null,
        due_at: due.toISOString(),
      });
      onSaved(`Follow-up created: ${created.title}`);
    } catch (saveError) {
      setError(messageFrom(saveError, "The follow-up could not be created. Try again."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Create a follow-up"
      closeLabel="Close follow-up"
      description={visitDescription(visit)}
      busy={saving}
      dirty={description.trim() !== "" || title !== "Follow up after site visit"}
      footer={(close) => (
        <>
          <Button variant="secondary" onClick={close} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="follow-up-form" variant="primary" loading={saving} disabled={!visit.lead_id}>
            Create follow-up
          </Button>
        </>
      )}
    >
      <form id="follow-up-form" className="df-sales-form" onSubmit={submit} noValidate>
        <div className="df-sales-form-grid">
          <SelectField label="Type" value={type} disabled={saving} options={FOLLOW_UP_TYPES.map((item) => ({ value: item.value, label: item.label }))} onChange={(event) => setType(event.target.value as FollowUpType)} />
          <TextField label="Title" required value={title} disabled={saving} onChange={(event) => setTitle(event.target.value)} />
          <TextField label="Due" type="datetime-local" required value={dueAt} disabled={saving} onChange={(event) => setDueAt(event.target.value)} />
          <TextareaField label="Notes" rows={3} value={description} disabled={saving} onChange={(event) => setDescription(event.target.value)} />
        </div>
          {error ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              {error}
            </p>
          ) : null}
      </form>
    </Dialog>
  );
}

function visitDescription(visit: SiteVisit): string {
  return new Date(visit.scheduled_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
}

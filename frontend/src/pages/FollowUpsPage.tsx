import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { toIsoDateTime, toLocalDateTimeInput } from "../lib/dateTimeInput";
import { contactsApi, type Contact } from "../services/contactApi";
import { followUpsApi, type FollowUp } from "../services/followUpApi";
import { leadsApi, type Lead } from "../services/leadApi";
import "./FollowUpsPage.css";

type Filter = "all" | "overdue" | "upcoming";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All pending" },
  { key: "overdue", label: "Overdue" },
  { key: "upcoming", label: "Upcoming" },
];

const PAGE_SIZE = 100;
const MAX_PAGES = 50;

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
}

interface FollowUpsSnapshot {
  items: FollowUp[];
  leads: Lead[];
  contacts: Contact[];
}

function requestFollowUps(): Promise<FollowUpsSnapshot> {
  return Promise.all([
    followUpsApi.list(),
    fetchAllLeads(),
    fetchAllContacts(),
  ]).then(([items, leads, contacts]) => ({ items, leads, contacts }));
}

function formatLabel(value: string): string {
  return value.charAt(0) + value.slice(1).toLowerCase();
}

function formatDueAt(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function getContactName(contact: Contact | undefined): string {
  if (!contact) return "Lead record";

  return [contact.first_name, contact.last_name].filter(Boolean).join(" ");
}

async function fetchAllLeads(): Promise<Lead[]> {
  const items: Lead[] = [];

  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const result = await leadsApi.list({ page, page_size: PAGE_SIZE });
    items.push(...result.items);

    if (result.items.length < PAGE_SIZE) break;
  }

  return items;
}

async function fetchAllContacts(): Promise<Contact[]> {
  const items: Contact[] = [];

  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const result = await contactsApi.list({ page, page_size: PAGE_SIZE });
    items.push(...result.items);

    if (result.items.length < PAGE_SIZE) break;
  }

  return items;
}

export default function FollowUpsPage() {
  const [followUps, setFollowUps] = useState<FollowUp[]>([]);
  const [leadsById, setLeadsById] = useState<Map<string, Lead>>(new Map());
  const [contactsById, setContactsById] = useState<Map<string, Contact>>(new Map());
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const [rescheduleId, setRescheduleId] = useState<string | null>(null);
  const [rescheduleValue, setRescheduleValue] = useState("");
  const [rescheduleError, setRescheduleError] = useState("");
  const [now, setNow] = useState(() => Date.now());

  const runLoad = useCallback((isCurrent: () => boolean) => {
    requestFollowUps()
      .then(
        (snapshot) => {
          if (!isCurrent()) return;
          setFollowUps(snapshot.items);
          setLeadsById(new Map(snapshot.leads.map((lead) => [lead.id, lead])));
          setContactsById(
            new Map(snapshot.contacts.map((contact) => [contact.id, contact])),
          );
          setNow(Date.now());
          setLoadError("");
        },
        (error: unknown) => {
          if (isCurrent()) setLoadError(getErrorMessage(error));
        },
      )
      .finally(() => {
        if (isCurrent()) setLoading(false);
      });
  }, []);

  function retryLoad() {
    setLoading(true);
    setLoadError("");
    runLoad(() => true);
  }

  useEffect(() => {
    let current = true;
    runLoad(() => current);

    return () => {
      current = false;
    };
  }, [runLoad]);

  // Overdue status is derived from the clock, so refresh it once a minute.
  useEffect(() => {
    const intervalId = window.setInterval(() => setNow(Date.now()), 60_000);

    return () => window.clearInterval(intervalId);
  }, []);

  const overdueCount = followUps.filter(
    (followUp) => new Date(followUp.due_at).getTime() < now,
  ).length;
  const visibleFollowUps = followUps.filter((followUp) => {
    const isOverdue = new Date(followUp.due_at).getTime() < now;

    if (filter === "overdue") return isOverdue;
    if (filter === "upcoming") return !isOverdue;
    return true;
  });

  async function handleComplete(followUp: FollowUp) {
    setActionError("");
    setNotice("");
    setBusyId(followUp.id);

    try {
      await followUpsApi.complete(followUp.id);
      setFollowUps((current) =>
        current.filter((item) => item.id !== followUp.id),
      );
      setNotice(`Marked "${followUp.title}" as complete.`);
    } catch (error) {
      setActionError(getErrorMessage(error));
    } finally {
      setBusyId(null);
    }
  }

  function openReschedule(followUp: FollowUp) {
    setActionError("");
    setNotice("");
    setRescheduleError("");
    setRescheduleId(followUp.id);
    setRescheduleValue(toLocalDateTimeInput(followUp.due_at));
  }

  function closeReschedule() {
    setRescheduleId(null);
    setRescheduleValue("");
    setRescheduleError("");
  }

  async function handleReschedule(followUp: FollowUp) {
    if (!rescheduleValue) {
      setRescheduleError("Choose a new date and time.");
      return;
    }

    const dueAt = toIsoDateTime(rescheduleValue);
    if (!dueAt) {
      setRescheduleError("Enter a valid date and time.");
      return;
    }

    setRescheduleError("");
    setBusyId(followUp.id);

    try {
      const updated = await followUpsApi.reschedule(followUp.id, { due_at: dueAt });
      setFollowUps((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      closeReschedule();
      setNotice(`Rescheduled "${followUp.title}" to ${formatDueAt(updated.due_at)}.`);
    } catch (error) {
      setRescheduleError(getErrorMessage(error));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="followups-page" aria-labelledby="followups-title">
      <header className="followups-header">
        <div>
          <h1 id="followups-title">Follow-ups</h1>
          <p>Pending follow-ups for your workspace, with overdue items first.</p>
        </div>
      </header>

      {!loading && !loadError && followUps.length > 0 && (
        <div className="followups-filters" role="group" aria-label="Filter follow-ups">
          {FILTERS.map((option) => (
            <button
              key={option.key}
              type="button"
              className="followups-filter"
              aria-pressed={filter === option.key}
              onClick={() => setFilter(option.key)}
            >
              {option.label}
              {option.key === "overdue" && overdueCount > 0 && (
                <span className="followups-count"> ({overdueCount})</span>
              )}
            </button>
          ))}
        </div>
      )}

      {notice && (
        <p className="followups-notice" role="status">
          {notice}
        </p>
      )}

      {actionError && (
        <p className="followups-error" role="alert">
          {actionError}
        </p>
      )}

      {loading ? (
        <div className="followups-state" role="status" aria-live="polite">
          <span className="followups-spinner" aria-hidden="true" />
          <p>Loading follow-ups…</p>
        </div>
      ) : loadError ? (
        <div className="followups-state" role="alert">
          <p>{loadError}</p>
          <button
            className="followups-secondary-button"
            type="button"
            onClick={retryLoad}
          >
            Try again
          </button>
        </div>
      ) : followUps.length === 0 ? (
        <div className="followups-state">
          <h2>No pending follow-ups</h2>
          <p>Follow-ups you schedule for a lead will appear here.</p>
        </div>
      ) : visibleFollowUps.length === 0 ? (
        <div className="followups-state">
          <h2>No follow-ups in this view</h2>
          <p>Choose another filter to see the rest of your pending follow-ups.</p>
        </div>
      ) : (
        <ul className="followups-list">
          {visibleFollowUps.map((followUp) => {
            const isOverdue = new Date(followUp.due_at).getTime() < now;
            const lead = leadsById.get(followUp.lead_id);
            const contact = lead ? contactsById.get(lead.contact_id) : undefined;
            const isBusy = busyId === followUp.id;
            const isRescheduling = rescheduleId === followUp.id;

            return (
              <li className="followups-item" key={followUp.id}>
                <article className="followups-card">
                  <div className="followups-card-top">
                    <span
                      className={
                        isOverdue
                          ? "followups-status followups-status-overdue"
                          : "followups-status"
                      }
                    >
                      {isOverdue ? "Overdue" : "Upcoming"}
                    </span>
                    <span className="followups-type">
                      {formatLabel(followUp.follow_up_type)}
                    </span>
                  </div>

                  <h2 className="followups-title">{followUp.title}</h2>

                  <p className="followups-meta">
                    <span>{getContactName(contact)}</span>
                    <span aria-hidden="true"> · </span>
                    <time dateTime={followUp.due_at}>
                      Due {formatDueAt(followUp.due_at)}
                    </time>
                    <span aria-hidden="true"> · </span>
                    <span>Pending</span>
                  </p>

                  {isRescheduling ? (
                    <div className="followups-reschedule">
                      <label className="followups-field">
                        <span>New date and time</span>
                        <input
                          type="datetime-local"
                          value={rescheduleValue}
                          onChange={(event) => setRescheduleValue(event.target.value)}
                          disabled={isBusy}
                          aria-invalid={rescheduleError ? true : undefined}
                          autoFocus
                        />
                      </label>
                      {rescheduleError && (
                        <p className="followups-error" role="alert">
                          {rescheduleError}
                        </p>
                      )}
                      <div className="followups-actions">
                        <button
                          className="followups-primary-button"
                          type="button"
                          onClick={() => void handleReschedule(followUp)}
                          disabled={isBusy}
                        >
                          {isBusy ? "Saving…" : "Save new time"}
                        </button>
                        <button
                          className="followups-secondary-button"
                          type="button"
                          onClick={closeReschedule}
                          disabled={isBusy}
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="followups-actions">
                      <button
                        className="followups-primary-button"
                        type="button"
                        onClick={() => void handleComplete(followUp)}
                        disabled={isBusy}
                      >
                        {isBusy ? "Saving…" : "Mark complete"}
                      </button>
                      <button
                        className="followups-secondary-button"
                        type="button"
                        onClick={() => openReschedule(followUp)}
                        disabled={isBusy}
                      >
                        Reschedule
                      </button>
                    </div>
                  )}
                </article>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

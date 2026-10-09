
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";

import { ApiError } from "../lib/api";
import { contactsApi, type Contact } from "../services/contactApi";
import {
  leadsApi,
  type Lead,
  type LeadCreateInput,
  type LeadInterest,
  type LeadOutcome,
  type LeadStatus,
} from "../services/leadApi";

import "./LeadsPage.css";

const PAGE_SIZE = 10;

const STATUSES: LeadStatus[] = [
  "NEW",
  "CONTACTED",
  "QUALIFIED",
  "MATCHING",
  "VISIT",
  "NEGOTIATION",
  "WON",
  "LOST",
  "ON_HOLD",
];


const ALLOWED_STATUS_TRANSITIONS: Record<LeadStatus, LeadStatus[]> = {
  NEW: ["CONTACTED", "QUALIFIED", "ON_HOLD"],
  CONTACTED: ["QUALIFIED", "MATCHING", "ON_HOLD"],
  QUALIFIED: ["MATCHING", "VISIT", "ON_HOLD"],
  MATCHING: ["VISIT", "QUALIFIED", "ON_HOLD"],
  VISIT: ["MATCHING", "NEGOTIATION", "QUALIFIED", "ON_HOLD"],
  NEGOTIATION: ["WON", "LOST", "VISIT", "ON_HOLD"],
  WON: [],
  LOST: [],
  ON_HOLD: ["CONTACTED", "QUALIFIED", "MATCHING", "VISIT", "NEGOTIATION"],
};

function getAvailableStatuses(currentStatus: LeadStatus): LeadStatus[] {
  return [
    currentStatus,
    ...ALLOWED_STATUS_TRANSITIONS[currentStatus],
  ];
}


const INTERESTS: LeadInterest[] = ["LOW", "MEDIUM", "HIGH"];

interface LeadForm {
  contact_id: string;
  interest: "" | LeadInterest;
  next_action: string;
}

const EMPTY_FORM: LeadForm = {
  contact_id: "",
  interest: "",
  next_action: "",
};

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

function formatDate(value: string | null): string {
  if (!value) return "—";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatDateTime(value: string | null): string {
  if (!value) return "Not scheduled";

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

function getStatusClass(status: LeadStatus): string {
  if (status === "WON") return "leads-status leads-status-won";
  if (status === "LOST") return "leads-status leads-status-lost";

  if (status === "NEGOTIATION" || status === "VISIT") {
    return "leads-status leads-status-progress";
  }

  if (status === "ON_HOLD") {
    return "leads-status leads-status-hold";
  }

  return "leads-status leads-status-default";
}

function getContactName(contact: Contact | undefined): string {
  if (!contact) return "Contact unavailable";

  return [contact.first_name, contact.last_name]
    .filter(Boolean)
    .join(" ");
}

function toIsoDateTime(value: string): string | null {
  if (!value) return null;

  const date = new Date(value);

  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | LeadStatus>("");
  const [interestFilter, setInterestFilter] = useState<
    "" | LeadInterest
  >("");
  const [activeFilter, setActiveFilter] = useState("active");

  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [updatingLeadId, setUpdatingLeadId] = useState<string | null>(null);

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [formError, setFormError] = useState("");

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [form, setForm] = useState<LeadForm>(EMPTY_FORM);

  const [contactSearch, setContactSearch] = useState("");
  const [contactLoading, setContactLoading] = useState(false);
  const [contactError, setContactError] = useState("");
  const [formContacts, setFormContacts] = useState<Contact[]>([]);
  const [nextActionDate, setNextActionDate] = useState("");

  const requestSequence = useRef(0);
  const modalRef = useRef<HTMLElement>(null);

  const loadLeads = useCallback(async () => {
    const sequence = ++requestSequence.current;

    setLoading(true);
    setError("");

    try {
      const result = await leadsApi.list({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        status: statusFilter || undefined,
        interest: interestFilter || undefined,
        is_active:
          activeFilter === "all" ? undefined : activeFilter === "active",
      });

      if (sequence !== requestSequence.current) return;

      setLeads(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
    } catch (loadError) {
      if (sequence !== requestSequence.current) return;

      setError(getErrorMessage(loadError));
    } finally {
      if (sequence === requestSequence.current) {
        setLoading(false);
      }
    }
  }, [page, search, statusFilter, interestFilter, activeFilter]);

  useEffect(() => {
    let cancelled = false;

    async function fetchLeads() {
      try {
        const result = await leadsApi.list({
          page,
          page_size: PAGE_SIZE,
          search: search || undefined,
          status: statusFilter || undefined,
          interest: interestFilter || undefined,
          is_active:
            activeFilter === "all" ? undefined : activeFilter === "active",
        });

        if (cancelled) return;

        setLeads(result.items);
        setTotal(result.total);
        setTotalPages(result.total_pages);
        setError("");
      } catch (loadError) {
        if (cancelled) return;

        setError(getErrorMessage(loadError));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void fetchLeads();

    return () => {
      cancelled = true;
    };
  }, [page, search, statusFilter, interestFilter, activeFilter]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const nextSearch = searchInput.trim();

      if (nextSearch !== search) {
        setPage(1);
        setSearch(nextSearch);
      }
    }, 300);

    return () => window.clearTimeout(timer);
  }, [searchInput, search]);

  useEffect(() => {
    if (!isFormOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusTimer = window.setTimeout(() => {
      modalRef.current?.querySelector<HTMLSelectElement>("select")?.focus();
    }, 50);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) {
        setIsFormOpen(false);
        setFormError("");
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isFormOpen, saving]);

  useEffect(() => {
    if (!isFormOpen) return;

    let cancelled = false;

    async function fetchContacts() {
      setContactLoading(true);
      setContactError("");

      try {
        const result = await contactsApi.list({
          page: 1,
          page_size: 100,
          is_active: true,
          search: contactSearch.trim() || undefined,
        });

        if (!cancelled) {
          setFormContacts(result.items);
        }
      } catch (loadError) {
        if (!cancelled) {
          setContactError(getErrorMessage(loadError));
        }
      } finally {
        if (!cancelled) {
          setContactLoading(false);
        }
      }
    }

    const timer = window.setTimeout(() => {
      void fetchContacts();
    }, contactSearch ? 250 : 0);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [isFormOpen, contactSearch]);

  useEffect(() => {
    let cancelled = false;

    async function fetchContactsForTable() {
      try {
        const result = await contactsApi.list({
          page: 1,
          page_size: 100,
          is_active: undefined,
        });

        if (!cancelled) {
          setContacts(result.items);
        }
      } catch {
        // Lead records remain usable if the contact lookup fails.
      }
    }

    void fetchContactsForTable();

    return () => {
      cancelled = true;
    };
  }, []);

  function openCreateForm() {
    setForm(EMPTY_FORM);
    setFormError("");
    setContactError("");
    setContactSearch("");
    setFormContacts([]);
    setNextActionDate("");
    setIsFormOpen(true);
  }

  async function handleCreateLead(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setSuccess("");

    if (!form.contact_id) {
      setFormError("Select a contact before creating a lead.");
      return;
    }

    const nextAction = form.next_action.trim();

    if (nextActionDate && !nextAction) {
      setFormError("Enter a next action when scheduling a date.");
      return;
    }

    const payload: LeadCreateInput = {
      contact_id: form.contact_id,
      interest: form.interest || null,
      next_action: nextAction || null,
      next_action_at: toIsoDateTime(nextActionDate),
    };

    setSaving(true);

    try {
      await leadsApi.create(payload);

      setIsFormOpen(false);
      setForm(EMPTY_FORM);
      setContactSearch("");
      setPage(1);
      setSearch("");
      setSearchInput("");
      setStatusFilter("");
      setInterestFilter("");
      setActiveFilter("active");
      setSuccess("Lead created successfully.");
      setLoading(true);

      const result = await leadsApi.list({
        page: 1,
        page_size: PAGE_SIZE,
        is_active: true,
      });

      setLeads(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
      setError("");
    } catch (createError) {
      setFormError(getErrorMessage(createError));
    } finally {
      setSaving(false);
      setLoading(false);
    }
  }

  async function handleStatusChange(lead: Lead, value: string) {
    const newStatus = value as LeadStatus;

    if (newStatus === lead.status || updatingLeadId) return;

    const payload: {
      status: LeadStatus;
      outcome?: LeadOutcome | null;
    } = { status: newStatus };

    if (newStatus === "WON") {
      payload.outcome = "SUCCESSFUL";
    } else if (newStatus === "LOST") {
      payload.outcome = "UNSUCCESSFUL";
    } else if (lead.status === "WON" || lead.status === "LOST") {
      payload.outcome = null;
    }

    setUpdatingLeadId(lead.id);
    setError("");
    setSuccess("");

    try {
      await leadsApi.update(lead.id, payload);
      setSuccess(`Lead status updated to ${formatLabel(newStatus)}.`);
      await loadLeads();
    } catch (updateError) {
      setError(getErrorMessage(updateError));
    } finally {
      setUpdatingLeadId(null);
    }
  }

  async function handleInterestChange(lead: Lead, value: string) {
    const interest = value ? (value as LeadInterest) : null;

    if (interest === lead.interest || updatingLeadId) return;

    setUpdatingLeadId(lead.id);
    setError("");
    setSuccess("");

    try {
      await leadsApi.update(lead.id, { interest });
      setSuccess("Lead interest updated successfully.");
      await loadLeads();
    } catch (updateError) {
      setError(getErrorMessage(updateError));
    } finally {
      setUpdatingLeadId(null);
    }
  }

  async function handleActiveToggle(lead: Lead) {
    if (updatingLeadId) return;

    setUpdatingLeadId(lead.id);
    setError("");
    setSuccess("");

    try {
      await leadsApi.update(lead.id, { is_active: !lead.is_active });

      setSuccess(
        lead.is_active
          ? "Lead marked inactive."
          : "Lead reactivated successfully.",
      );

      await loadLeads();
    } catch (updateError) {
      setError(getErrorMessage(updateError));
    } finally {
      setUpdatingLeadId(null);
    }
  }

  const firstResult = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastResult = Math.min(page * PAGE_SIZE, total);

  const contactById = new Map(
    [...contacts, ...formContacts].map((contact) => [
      contact.id,
      contact,
    ]),
  );

  return (
    <section className="leads-page">
      <header className="leads-header">
        <div>
          <span className="leads-eyebrow">SALES WORKSPACE</span>
          <h1>Leads</h1>
          <p className="leads-subtitle">
            Track enquiries, manage opportunities, and move prospects toward
            successful deals.
          </p>
        </div>

        <button
          className="leads-primary-button"
          type="button"
          onClick={openCreateForm}
        >
          <span aria-hidden="true">+</span> Add lead
        </button>
      </header>

      <section className="leads-summary" aria-label="Lead overview">
        <div className="leads-summary-icon" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="10" cy="7" r="4" />
            <path d="M20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
        </div>
        <div>
          <p className="leads-summary-label">
            {activeFilter === "active"
              ? "Active leads"
              : activeFilter === "inactive"
                ? "Inactive leads"
                : "All leads"}
          </p>
          <p className="leads-summary-value">
            {loading && total === 0 ? "—" : total.toLocaleString("en-IN")}
          </p>
        </div>
      </section>

      {success && (
        <div className="leads-alert leads-alert-success" role="status">
          <span>{success}</span>
          <button
            type="button"
            className="leads-dismiss"
            onClick={() => setSuccess("")}
            aria-label="Dismiss success message"
          >
            ×
          </button>
        </div>
      )}

      <section className="leads-panel">
        <header className="leads-panel-heading">
          <div>
            <h2>All leads</h2>
            <p>Search and update your sales pipeline.</p>
          </div>
          <button
            className="leads-secondary-button"
            type="button"
            onClick={() => void loadLeads()}
            disabled={loading}
          >
            {loading ? "Refreshing..." : "↻ Refresh"}
          </button>
        </header>

        <div className="leads-toolbar">
          <label className="leads-search">
            <span className="leads-visually-hidden">Search leads</span>
            <span className="leads-search-icon" aria-hidden="true">⌕</span>
            <input
              type="search"
              value={searchInput}
              maxLength={320}
              placeholder="Search contact, email, phone or next action..."
              onChange={(event) => {
                setSearchInput(event.target.value);
                setPage(1);
              }}
            />
          </label>

          <label className="leads-filter">
            <span className="leads-visually-hidden">Filter by status</span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as "" | LeadStatus);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {STATUSES.map((status) => (
                <option value={status} key={status}>
                  {formatLabel(status)}
                </option>
              ))}
            </select>
          </label>

          <label className="leads-filter">
            <span className="leads-visually-hidden">Filter by interest</span>
            <select
              value={interestFilter}
              onChange={(event) => {
                setInterestFilter(event.target.value as "" | LeadInterest);
                setPage(1);
              }}
            >
              <option value="">All interest levels</option>
              {INTERESTS.map((interest) => (
                <option value={interest} key={interest}>
                  {formatLabel(interest)} interest
                </option>
              ))}
            </select>
          </label>

          <label className="leads-filter">
            <span className="leads-visually-hidden">Filter active leads</span>
            <select
              value={activeFilter}
              onChange={(event) => {
                setActiveFilter(event.target.value);
                setPage(1);
              }}
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="all">All leads</option>
            </select>
          </label>
        </div>

        {error && (
          <div className="leads-alert leads-alert-error" role="alert">
            <div>
              <strong>Couldn't load or update leads</strong>
              <p>{error}</p>
            </div>
            <button
              className="leads-secondary-button"
              type="button"
              onClick={() => void loadLeads()}
            >
              Retry
            </button>
          </div>
        )}

        {loading ? (
          <div className="leads-state" role="status" aria-live="polite">
            <span className="leads-spinner" aria-hidden="true" />
            <p>Loading leads...</p>
          </div>
        ) : !error && leads.length === 0 ? (
          <div className="leads-empty">
            <div className="leads-empty-icon" aria-hidden="true">↗</div>
            <h3>
              {search || statusFilter || interestFilter || activeFilter !== "active"
                ? "No matching leads"
                : "Your pipeline starts here"}
            </h3>
            <p>
              {search || statusFilter || interestFilter || activeFilter !== "active"
                ? "Try changing your search or filters."
                : "Create a lead from an existing contact to start tracking an opportunity."}
            </p>

            {search || statusFilter || interestFilter || activeFilter !== "active" ? (
              <button
                className="leads-secondary-button"
                type="button"
                onClick={() => {
                  setSearchInput("");
                  setSearch("");
                  setStatusFilter("");
                  setInterestFilter("");
                  setActiveFilter("active");
                  setPage(1);
                }}
              >
                Clear filters
              </button>
            ) : (
              <button
                className="leads-primary-button"
                type="button"
                onClick={openCreateForm}
              >
                + Add your first lead
              </button>
            )}
          </div>
        ) : !error ? (
          <>
            <div className="leads-table-wrapper">
              <table className="leads-table">
                <thead>
                  <tr>
                    <th scope="col">Contact</th>
                    <th scope="col">Status</th>
                    <th scope="col">Interest</th>
                    <th scope="col">Next action</th>
                    <th scope="col">Follow-up date</th>
                    <th scope="col">Added</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((lead) => {
                    const contact = contactById.get(lead.contact_id);
                    const busy = updatingLeadId === lead.id;

                    return (
                      <tr key={lead.id}>
                        <td>
                          <div className="leads-contact-name">
                            {getContactName(contact)}
                          </div>
                          <div className="leads-secondary-text">
                            {contact?.email ||
                              contact?.phone ||
                              "No contact details"}
                          </div>
                        </td>
                        <td>
                          <span className={getStatusClass(lead.status)}>
                            {formatLabel(lead.status)}
                          </span>
                          <select
                            className="leads-inline-select"
                            aria-label={`Change status for ${getContactName(contact)}`}
                            value={lead.status}
                            disabled={busy || !lead.is_active}
                            onChange={(event) =>
                              void handleStatusChange(lead, event.target.value)
                            }
                          >
                            {getAvailableStatuses(lead.status).map((status) => (
                              <option key={status} value={status}>
                                {formatLabel(status)}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <select
                            className="leads-inline-select"
                            aria-label={`Change interest for ${getContactName(contact)}`}
                            value={lead.interest ?? ""}
                            disabled={busy || !lead.is_active}
                            onChange={(event) =>
                              void handleInterestChange(lead, event.target.value)
                            }
                          >
                            <option value="">Not set</option>
                            {INTERESTS.map((interest) => (
                              <option key={interest} value={interest}>
                                {formatLabel(interest)}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <span className="leads-action-text">
                            {lead.next_action || "—"}
                          </span>
                        </td>
                        <td>{formatDateTime(lead.next_action_at)}</td>
                        <td>{formatDate(lead.created_at)}</td>
                        <td>
                          <button
                            className="leads-text-button"
                            type="button"
                            disabled={busy}
                            onClick={() => void handleActiveToggle(lead)}
                          >
                            {busy
                              ? "Saving..."
                              : lead.is_active
                                ? "Deactivate"
                                : "Reactivate"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <footer className="leads-pagination">
              <p>
                Showing <strong>{firstResult}–{lastResult}</strong> of{" "}
                <strong>{total}</strong> leads
              </p>
              <div className="leads-pagination-controls">
                <button
                  className="leads-page-button"
                  type="button"
                  disabled={page <= 1 || loading}
                  onClick={() => setPage((current) => current - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {page}{totalPages > 0 ? ` of ${totalPages}` : ""}
                </span>
                <button
                  className="leads-page-button"
                  type="button"
                  disabled={page >= totalPages || totalPages === 0 || loading}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </button>
              </div>
            </footer>
          </>
        ) : null}
      </section>

      {isFormOpen &&
  createPortal(
    <div
      className="leads-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) {
          setIsFormOpen(false);
          setFormError("");
        }
      }}
    >
      <section
        ref={modalRef}
        className="leads-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="leads-modal-title"
      >
        <header className="leads-modal-header">
          <div>
            <span className="leads-eyebrow">OPPORTUNITY DETAILS</span>
            <h2 id="leads-modal-title">Add a lead</h2>
            <p>Choose a contact and capture the next step.</p>
          </div>

          <button
            className="leads-modal-close"
            type="button"
            aria-label="Close form"
            disabled={saving}
            onClick={() => {
              setIsFormOpen(false);
              setFormError("");
            }}
          >
            ×
          </button>
        </header>

        <form className="leads-form" onSubmit={handleCreateLead}>
          <div className="leads-form-body">
            {formError && (
              <div
                className="leads-alert leads-alert-error"
                role="alert"
              >
                {formError}
              </div>
            )}

            <label className="leads-form-field">
              <span>Find contact</span>
              <input
                type="search"
                value={contactSearch}
                maxLength={320}
                onChange={(event) => setContactSearch(event.target.value)}
                placeholder="Search active contacts..."
                disabled={saving}
              />
            </label>

            <label className="leads-form-field">
              <span>
                Contact <span aria-hidden="true">*</span>
              </span>

              <select
                required
                value={form.contact_id}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    contact_id: event.target.value,
                  }))
                }
                disabled={saving || contactLoading}
              >
                <option value="">
                  {contactLoading ? "Loading contacts..." : "Select a contact"}
                </option>

                {formContacts.map((contact) => (
                  <option value={contact.id} key={contact.id}>
                    {getContactName(contact)}
                    {contact.phone ? ` · ${contact.phone}` : ""}
                  </option>
                ))}
              </select>

              {contactLoading && (
                <span className="leads-field-hint">
                  Loading contacts…
                </span>
              )}

              {contactError && (
                <span className="leads-field-error">
                  {contactError}
                </span>
              )}

              {!contactLoading &&
                !contactError &&
                formContacts.length === 0 && (
                  <span className="leads-field-hint">
                    No active contacts found. Add a contact first or change
                    your search.
                  </span>
                )}
            </label>

            <label className="leads-form-field">
              <span>Interest level</span>
              <select
                value={form.interest}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    interest: event.target.value as "" | LeadInterest,
                  }))
                }
                disabled={saving}
              >
                <option value="">Not set</option>
                {INTERESTS.map((interest) => (
                  <option key={interest} value={interest}>
                    {formatLabel(interest)}
                  </option>
                ))}
              </select>
            </label>

            <label className="leads-form-field">
              <span>Next action</span>
              <input
                type="text"
                maxLength={500}
                value={form.next_action}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    next_action: event.target.value,
                  }))
                }
                placeholder="e.g. Call about 2BHK apartment"
                disabled={saving}
              />
            </label>

            <label className="leads-form-field">
              <span>Next action date and time</span>
              <input
                type="datetime-local"
                value={nextActionDate}
                onChange={(event) => setNextActionDate(event.target.value)}
                disabled={saving}
              />
            </label>

            <p className="leads-field-hint">
              New leads are created with the status New. You can update the
              status as the opportunity progresses.
            </p>
          </div>

          <footer className="leads-form-actions">
            <button
              className="leads-secondary-button"
              type="button"
              onClick={() => {
                setIsFormOpen(false);
                setFormError("");
              }}
              disabled={saving}
            >
              Cancel
            </button>

            <button
              className="leads-primary-button"
              type="submit"
              disabled={
                saving || contactLoading || formContacts.length === 0
              }
            >
              {saving ? "Saving..." : "Create lead"}
            </button>
          </footer>
        </form>
      </section>
    </div>,
    document.body,
  )}
    </section>
  );
}

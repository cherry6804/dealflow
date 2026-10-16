import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";

import { ApiError } from "../lib/api";
import {
  customerProfilesApi,
  type CustomerProfile,
} from "../services/customerProfileApi";
import { leadsApi, type Lead } from "../services/leadApi";
import {
  propertiesApi,
  type Property,
} from "../services/propertyApi";
import {
  siteVisitsApi,
  type SiteVisit,
  type SiteVisitOutcome,
  type SiteVisitStatus,
} from "../services/siteVisitApi";

import "./SiteVisitsPage.css";

type CustomerType = "lead" | "customer";

const PAGE_SIZE = 10;

const STATUSES: Array<{
  value: SiteVisitStatus | "";
  label: string;
}> = [
  { value: "", label: "All statuses" },
  { value: "SCHEDULED", label: "Scheduled" },
  { value: "COMPLETED", label: "Completed" },
  { value: "CANCELLED", label: "Cancelled" },
  { value: "NO_SHOW", label: "No show" },
];

const OUTCOMES: Array<{
  value: SiteVisitOutcome;
  label: string;
}> = [
  { value: "INTERESTED", label: "Interested" },
  { value: "NOT_INTERESTED", label: "Not interested" },
  { value: "NEGOTIATION", label: "Negotiation" },
  { value: "FOLLOW_UP_REQUIRED", label: "Follow-up required" },
  { value: "OTHER", label: "Other" },
];

function localDateTimeValue(date: Date): string {
  const local = new Date(
    date.getTime() - date.getTimezoneOffset() * 60_000,
  );

  return local.toISOString().slice(0, 16);
}

function propertyLabel(property: Property): string {
  const address = [
    property.address_line_1,
    property.address_line_2,
    property.locality,
    property.city,
  ]
    .filter(Boolean)
    .join(", ");

  return address || `Property ${property.id.slice(0, 8)}`;
}

function customerLabel(customer: CustomerProfile): string {
  const contact = customer.contact;

  const name = [
    contact.first_name,
    contact.last_name,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    name ||
    contact.email ||
    contact.phone ||
    customer.id.slice(0, 8)
  );
}

function statusLabel(status: SiteVisitStatus): string {
  if (status === "NO_SHOW") {
    return "No show";
  }

  return status.charAt(0) + status.slice(1).toLowerCase();
}

function dateLabel(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Invalid date";
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

function timeLabel(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Invalid time";
  }

  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}

export default function SiteVisitsPage() {
  // Data used by the visits list and scheduling form.
  const [properties, setProperties] = useState<Property[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [customers, setCustomers] = useState<CustomerProfile[]>([]);
  const [visits, setVisits] = useState<SiteVisit[]>([]);

  // Pagination and filtering.
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] =
    useState<SiteVisitStatus | "">("");

  // Loading and submission state.
  const [loading, setLoading] = useState(true);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [isFormOpen, setIsFormOpen] = useState(false);

  // Feedback messages.
  const [loadError, setLoadError] = useState("");
  const [optionsError, setOptionsError] = useState("");
  const [message, setMessage] = useState("");
  const [formError, setFormError] = useState("");

  const modalRef = useRef<HTMLElement>(null);

  // Scheduling form state.
  const [propertyId, setPropertyId] = useState("");
  const [customerType, setCustomerType] =
    useState<CustomerType>("lead");
  const [leadId, setLeadId] = useState("");
  const [customerProfileId, setCustomerProfileId] =
    useState("");

  // Attendance form state.
const [attendanceVisit, setAttendanceVisit] =
  useState<SiteVisit | null>(null);
const [attendanceStatus, setAttendanceStatus] =
  useState<"COMPLETED" | "CANCELLED" | "NO_SHOW">("COMPLETED");
const [attendanceOutcome, setAttendanceOutcome] =
  useState<SiteVisitOutcome | "">("");
const [attendanceFeedback, setAttendanceFeedback] = useState("");
const [attendanceError, setAttendanceError] = useState("");
const [attendanceSubmitting, setAttendanceSubmitting] = useState(false);

  const [scheduledAt, setScheduledAt] = useState(() => {
    const date = new Date();

    date.setDate(date.getDate() + 1);
    date.setHours(10, 0, 0, 0);

    return localDateTimeValue(date);
  });

  const [endsAt, setEndsAt] = useState("");
  const [notes, setNotes] = useState("");

  // Load saved visits from the backend.
  const loadVisits = useCallback(async () => {
    setLoading(true);
    setLoadError("");

    try {
      const response = await siteVisitsApi.list({
        page,
        page_size: PAGE_SIZE,
        status: statusFilter,
      });

      setVisits(response.items);
      setTotal(response.total);
      setTotalPages(response.total_pages);
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  // Load properties, leads, and customer profiles for the form.
  const loadOptions = useCallback(async () => {
    setLoadingOptions(true);
    setOptionsError("");

    try {
      const [
        propertyResponse,
        leadResponse,
        customerResponse,
      ] = await Promise.all([
        propertiesApi.search({
          page: 1,
          page_size: 100,
        }),
        leadsApi.list({
          page: 1,
          page_size: 100,
          is_active: true,
        }),
        customerProfilesApi.list({
          page: 1,
          page_size: 100,
          is_active: true,
        }),
      ]);

      setProperties(propertyResponse.items);
      setLeads(leadResponse.items);
      setCustomers(customerResponse.items);
    } catch (error) {
      setOptionsError(errorMessage(error));
    } finally {
      setLoadingOptions(false);
    }
  }, []);

  useEffect(() => {
    void loadVisits();
  }, [loadVisits]);

  useEffect(() => {
    void loadOptions();
  }, [loadOptions]);

  // Match the Properties page modal behavior.
  useEffect(() => {
    if (!isFormOpen) {
      return;
    }

    const previousOverflow = document.body.style.overflow;

    document.body.style.overflow = "hidden";

    const timer = window.setTimeout(() => {
      modalRef.current
        ?.querySelector<HTMLInputElement | HTMLSelectElement>(
          "select, input",
        )
        ?.focus();
    }, 50);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !submitting) {
        setIsFormOpen(false);
        setFormError("");
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;

      window.clearTimeout(timer);

      document.removeEventListener(
        "keydown",
        handleKeyDown,
      );
    };
  }, [isFormOpen, submitting]);

  function openForm() {
    setFormError("");
    setMessage("");

    setPropertyId("");
    setCustomerType("lead");
    setLeadId("");
    setCustomerProfileId("");
    setEndsAt("");
    setNotes("");

    const date = new Date();

    date.setDate(date.getDate() + 1);
    date.setHours(10, 0, 0, 0);

    setScheduledAt(localDateTimeValue(date));
    setIsFormOpen(true);
  }

  function openAttendanceForm(visit: SiteVisit) {
  setAttendanceVisit(visit);
  setAttendanceStatus("COMPLETED");
  setAttendanceOutcome(visit.outcome ?? "");
  setAttendanceFeedback(visit.feedback ?? "");
  setAttendanceError("");
  setMessage("");
}

function closeAttendanceForm() {
  if (attendanceSubmitting) {
    return;
  }

  setAttendanceVisit(null);
  setAttendanceError("");
}

async function handleAttendanceSubmit(
  event: FormEvent<HTMLFormElement>,
) {
  event.preventDefault();
  setAttendanceError("");
  setMessage("");

  if (!attendanceVisit) {
    return;
  }

  if (attendanceStatus !== "COMPLETED" && attendanceOutcome) {
    setAttendanceError(
      "An outcome can only be recorded when the visit is completed.",
    );
    return;
  }

  setAttendanceSubmitting(true);

  try {
    await siteVisitsApi.recordAttendance(attendanceVisit.id, {
      status: attendanceStatus,
      outcome:
        attendanceStatus === "COMPLETED"
          ? attendanceOutcome || null
          : null,
      feedback: attendanceFeedback.trim() || null,
    });

    setAttendanceVisit(null);
    setMessage("Site visit attendance recorded successfully.");

    await loadVisits();
  } catch (error) {
    setAttendanceError(errorMessage(error));
  } finally {
    setAttendanceSubmitting(false);
  }
}

  async function handleSubmit(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    setFormError("");

    if (!propertyId) {
      setFormError(
        "Select a property before scheduling the visit.",
      );
      return;
    }

    if (customerType === "lead" && !leadId) {
      setFormError("Select a lead for this visit.");
      return;
    }

    if (
      customerType === "customer" &&
      !customerProfileId
    ) {
      setFormError("Select a customer for this visit.");
      return;
    }

    const start = new Date(scheduledAt);
    const end = endsAt ? new Date(endsAt) : null;

    if (Number.isNaN(start.getTime())) {
      setFormError("Enter a valid visit date and time.");
      return;
    }

    if (
      end &&
      (Number.isNaN(end.getTime()) || end <= start)
    ) {
      setFormError(
        "The end time must be later than the start time.",
      );
      return;
    }

    setSubmitting(true);

    try {
      await siteVisitsApi.schedule({
        property_id: propertyId,
        lead_id:
          customerType === "lead" ? leadId : null,
        customer_profile_id:
          customerType === "customer"
            ? customerProfileId
            : null,
        scheduled_at: start.toISOString(),
        ends_at: end?.toISOString() ?? null,
        notes: notes.trim() || null,
      });

      setIsFormOpen(false);
      setMessage("Site visit scheduled successfully.");

      // Refresh from page 1 so the new visit is visible.
      if (page !== 1) {
        setPage(1);
      } else {
        await loadVisits();
      }
    } catch (error) {
      setFormError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  // Resolve property/customer labels without extra API calls.
  const propertyById = new Map(
    properties.map((property) => [
      property.id,
      property,
    ]),
  );

  const customerById = new Map(
    customers.map((customer) => [
      customer.id,
      customer,
    ]),
  );

  const leadById = new Map(
    leads.map((lead) => [lead.id, lead]),
  );

  // These summary values describe the currently loaded page.
  const now = Date.now();

  const upcomingCount = visits.filter(
    (visit) =>
      visit.status === "SCHEDULED" &&
      new Date(visit.scheduled_at).getTime() >= now,
  ).length;

  const completedCount = visits.filter(
    (visit) => visit.status === "COMPLETED",
  ).length;

  return (
    <main className="site-visits-page">
      <header className="site-visits-header">
        <div>
          <span className="site-visits-eyebrow">
            PROPERTY OPERATIONS
          </span>

          <h1>Site visits</h1>

          <p className="site-visits-subtitle">
            Manage property appointments and keep every
            customer visit on track.
          </p>
        </div>

        <button
          type="button"
          className="site-visits-primary-button"
          onClick={openForm}
        >
          <span aria-hidden="true">＋</span>
          Schedule visit
        </button>
      </header>

      <section
        className="site-visits-summary-grid"
        aria-label="Site visit summary"
      >
        <article className="site-visits-summary-card">
          <span
            className="site-visits-summary-icon"
            aria-hidden="true"
          >
            ◷
          </span>

          <div>
            <p>All visits</p>
            <strong>{total}</strong>
          </div>
        </article>

        <article className="site-visits-summary-card">
          <span
            className="site-visits-summary-icon"
            aria-hidden="true"
          >
            ▣
          </span>

          <div>
            <p>Upcoming on this page</p>
            <strong>{upcomingCount}</strong>
          </div>
        </article>

        <article className="site-visits-summary-card">
          <span
            className="site-visits-summary-icon"
            aria-hidden="true"
          >
            ✓
          </span>

          <div>
            <p>Completed on this page</p>
            <strong>{completedCount}</strong>
          </div>
        </article>
      </section>

      {message && (
        <div
          className="site-visits-alert site-visits-alert-success"
          role="status"
        >
          <span>{message}</span>

          <button
            type="button"
            aria-label="Dismiss success message"
            onClick={() => setMessage("")}
          >
            ×
          </button>
        </div>
      )}

      {loadError && (
        <div
          className="site-visits-alert site-visits-alert-error"
          role="alert"
        >
          <span>{loadError}</span>

          <button
            type="button"
            onClick={() => void loadVisits()}
          >
            Retry
          </button>
        </div>
      )}

      {optionsError && (
        <div
          className="site-visits-alert site-visits-alert-error"
          role="alert"
        >
          <span>
            Form options could not be loaded: {optionsError}
          </span>

          <button
            type="button"
            onClick={() => void loadOptions()}
          >
            Retry
          </button>
        </div>
      )}

      <section className="site-visits-panel">
        <header className="site-visits-panel-heading">
          <div>
            <h2>Scheduled appointments</h2>
            <p>
              Review appointments saved in your workspace.
            </p>
          </div>

          <div className="site-visits-toolbar">
            <label>
              <span className="site-visits-visually-hidden">
                Filter by status
              </span>

              <select
                value={statusFilter}
                onChange={(event) => {
                  setStatusFilter(
                    event.target.value as
                      | SiteVisitStatus
                      | "",
                  );
                  setPage(1);
                }}
              >
                {STATUSES.map((item) => (
                  <option
                    key={item.value}
                    value={item.value}
                  >
                    {item.label}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              className="site-visits-secondary-button"
              onClick={() => void loadVisits()}
              disabled={loading}
            >
              {loading ? "Refreshing…" : "↻ Refresh"}
            </button>
          </div>
        </header>

        {loading ? (
          <div
            className="site-visits-state"
            role="status"
            aria-live="polite"
          >
            <span className="site-visits-spinner" />
            <p>Loading site visits…</p>
          </div>
        ) : !loadError && visits.length === 0 ? (
          <div className="site-visits-empty">
            <div
              className="site-visits-empty-icon"
              aria-hidden="true"
            >
              ▦
            </div>

            <h3>
              {statusFilter
                ? "No visits match this status"
                : "No site visits yet"}
            </h3>

            <p>
              {statusFilter
                ? "Try another status filter or view all appointments."
                : "Schedule your first property visit and it will appear here."}
            </p>

            <button
              type="button"
              className="site-visits-primary-button"
              onClick={
                statusFilter
                  ? () => setStatusFilter("")
                  : openForm
              }
            >
              {statusFilter
                ? "Clear filter"
                : "Schedule your first visit"}
            </button>
          </div>
        ) : !loadError ? (
          <>
            <div className="site-visits-table-wrap">
              <table className="site-visits-table">
                <thead>
                  <tr>
                    <th scope="col">Property</th>
                    <th scope="col">Lead / customer</th>
                    <th scope="col">Date &amp; time</th>
                    <th scope="col">Status</th>
                    <th scope="col">Notes</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>

                <tbody>
                  {visits.map((visit) => {
                    const property = propertyById.get(
                      visit.property_id,
                    );

                    const lead = visit.lead_id
                      ? leadById.get(visit.lead_id)
                      : undefined;

                    const customer =
                      visit.customer_profile_id
                        ? customerById.get(
                            visit.customer_profile_id,
                          )
                        : undefined;

                    const who = customer
                      ? customerLabel(customer)
                      : lead
                        ? `Lead · ${lead.id.slice(0, 8)}`
                        : visit.customer_profile_id
                          ? `Customer · ${visit.customer_profile_id.slice(0, 8)}`
                          : visit.lead_id
                            ? `Lead · ${visit.lead_id.slice(0, 8)}`
                            : "—";

                    return (
                      <tr key={visit.id}>
                        <td>
                          <strong>
                            {property
                              ? propertyLabel(property)
                              : `Property · ${visit.property_id.slice(0, 8)}`}
                          </strong>

                          <small>
                            {property?.property_type?.replaceAll(
                              "_",
                              " ",
                            ) ?? "Property visit"}
                          </small>
                        </td>

                        <td>{who}</td>

                        <td>
                          <strong>
                            {dateLabel(visit.scheduled_at)}
                          </strong>

                          <small>
                            {timeLabel(visit.scheduled_at)}
                            {visit.ends_at
                              ? ` – ${timeLabel(visit.ends_at)}`
                              : ""}
                          </small>
                        </td>

                        <td>
                          <span
                            className={`site-visits-status site-visits-status-${visit.status
                              .toLowerCase()
                              .replaceAll("_", "-")}`}
                          >
                            {statusLabel(visit.status)}
                          </span>
                        </td>

                        <td className="site-visits-notes">
                          {visit.notes || "—"}
                        </td>

                        <td>
                          {visit.status === "SCHEDULED" ? (
                            <button
                              type="button"
                              className="site-visits-secondary-button"
                              onClick={() => openAttendanceForm(visit)}
                              disabled={attendanceSubmitting}
                            >
                              Record attendance
                            </button>
                          ) : (
                            <span className="site-visits-visually-hidden">
                              Attendance already recorded
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <footer className="site-visits-pagination">
              <p>
                Showing{" "}
                <strong>
                  {total === 0
                    ? 0
                    : (page - 1) * PAGE_SIZE + 1}
                  –
                  {Math.min(page * PAGE_SIZE, total)}
                </strong>{" "}
                of <strong>{total}</strong> visits
              </p>

              <div>
                <button
                  type="button"
                  className="site-visits-secondary-button"
                  disabled={page <= 1 || loading}
                  onClick={() =>
                    setPage((current) => current - 1)
                  }
                >
                  Previous
                </button>

                <span>
                  Page {page}
                  {totalPages ? ` of ${totalPages}` : ""}
                </span>

                <button
                  type="button"
                  className="site-visits-secondary-button"
                  disabled={
                    page >= totalPages ||
                    loading ||
                    totalPages === 0
                  }
                  onClick={() =>
                    setPage((current) => current + 1)
                  }
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
            className="site-visits-modal-backdrop"
            onMouseDown={(event) => {
              if (
                event.target === event.currentTarget &&
                !submitting
              ) {
                setIsFormOpen(false);
              }
            }}
          >
            <section
              ref={modalRef}
              className="site-visits-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="site-visits-modal-title"
            >
              <header className="site-visits-modal-header">
                <div>
                  <span className="site-visits-eyebrow">
                    APPOINTMENT DETAILS
                  </span>

                  <h2 id="site-visits-modal-title">
                    Schedule a visit
                  </h2>

                  <p>
                    Choose a property, customer and
                    appointment time.
                  </p>
                </div>

                <button
                  className="site-visits-modal-close"
                  type="button"
                  aria-label="Close form"
                  disabled={submitting}
                  onClick={() => setIsFormOpen(false)}
                >
                  ×
                </button>
              </header>

              <form
                className="site-visits-modal-form"
                onSubmit={handleSubmit}
              >
                <div className="site-visits-modal-body">
                  {formError && (
                    <div
                      className="site-visits-alert site-visits-alert-error"
                      role="alert"
                    >
                      {formError}
                    </div>
                  )}

                  {loadingOptions ? (
                    <div
                      className="site-visits-state"
                      role="status"
                    >
                      <span className="site-visits-spinner" />
                      <p>
                        Loading properties and customers…
                      </p>
                    </div>
                  ) : (
                    <>
                      <h3 className="site-visits-form-section-title">
                        Property and customer
                      </h3>

                      <div className="site-visits-form-grid">
                        <label className="site-visits-field site-visits-field-full">
                          <span>
                            Property <b>*</b>
                          </span>

                          <select
                            value={propertyId}
                            onChange={(event) =>
                              setPropertyId(
                                event.target.value,
                              )
                            }
                            required
                            disabled={submitting}
                          >
                            <option value="">
                              Select a property
                            </option>

                            {properties.map((property) => (
                              <option
                                key={property.id}
                                value={property.id}
                              >
                                {propertyLabel(property)}
                                {property.property_type
                                  ? ` · ${property.property_type.replaceAll("_", " ")}`
                                  : ""}
                              </option>
                            ))}
                          </select>

                          {properties.length === 0 && (
                            <small>
                              No properties available. Add a
                              property before scheduling.
                            </small>
                          )}
                        </label>

                        <div className="site-visits-field site-visits-field-full">
                          <span>
                            Visit for <b>*</b>
                          </span>

                          <div className="site-visits-choice-group">
                            <button
                              type="button"
                              className={
                                customerType === "lead"
                                  ? "selected"
                                  : ""
                              }
                              onClick={() =>
                                setCustomerType("lead")
                              }
                              aria-pressed={
                                customerType === "lead"
                              }
                              disabled={submitting}
                            >
                              Lead
                            </button>

                            <button
                              type="button"
                              className={
                                customerType === "customer"
                                  ? "selected"
                                  : ""
                              }
                              onClick={() =>
                                setCustomerType("customer")
                              }
                              aria-pressed={
                                customerType === "customer"
                              }
                              disabled={submitting}
                            >
                              Existing customer
                            </button>
                          </div>
                        </div>

                        {customerType === "lead" ? (
                          <label className="site-visits-field site-visits-field-full">
                            <span>
                              Lead <b>*</b>
                            </span>

                            <select
                              value={leadId}
                              onChange={(event) =>
                                setLeadId(event.target.value)
                              }
                              required
                              disabled={submitting}
                            >
                              <option value="">
                                Select a lead
                              </option>

                              {leads.map((lead) => (
                                <option
                                  key={lead.id}
                                  value={lead.id}
                                >
                                  Lead · {lead.id.slice(0, 8)} ·{" "}
                                  {lead.status.replaceAll(
                                    "_",
                                    " ",
                                  )}
                                </option>
                              ))}
                            </select>

                            {leads.length === 0 && (
                              <small>
                                No active leads available in
                                this workspace.
                              </small>
                            )}
                          </label>
                        ) : (
                          <label className="site-visits-field site-visits-field-full">
                            <span>
                              Customer <b>*</b>
                            </span>

                            <select
                              value={customerProfileId}
                              onChange={(event) =>
                                setCustomerProfileId(
                                  event.target.value,
                                )
                              }
                              required
                              disabled={submitting}
                            >
                              <option value="">
                                Select a customer
                              </option>

                              {customers.map((customer) => (
                                <option
                                  key={customer.id}
                                  value={customer.id}
                                >
                                  {customerLabel(customer)}
                                </option>
                              ))}
                            </select>

                            {customers.length === 0 && (
                              <small>
                                No active customer profiles
                                available.
                              </small>
                            )}
                          </label>
                        )}
                      </div>

                      <h3 className="site-visits-form-section-title">
                        Date and time
                      </h3>

                      <div className="site-visits-form-grid">
                        <label className="site-visits-field">
                          <span>
                            Start date and time <b>*</b>
                          </span>

                          <input
                            type="datetime-local"
                            value={scheduledAt}
                            onChange={(event) =>
                              setScheduledAt(
                                event.target.value,
                              )
                            }
                            required
                            disabled={submitting}
                          />

                          <small>
                            Uses your device’s local timezone.
                          </small>
                        </label>

                        <label className="site-visits-field">
                          <span>End date and time</span>

                          <input
                            type="datetime-local"
                            value={endsAt}
                            min={scheduledAt}
                            onChange={(event) =>
                              setEndsAt(event.target.value)
                            }
                            disabled={submitting}
                          />

                          <small>
                            Optional; must be later than the
                            start.
                          </small>
                        </label>
                      </div>

                      <h3 className="site-visits-form-section-title">
                        Additional information
                      </h3>

                      <label className="site-visits-field">
                        <span>Visit notes</span>

                        <textarea
                          rows={4}
                          maxLength={10000}
                          value={notes}
                          onChange={(event) =>
                            setNotes(event.target.value)
                          }
                          placeholder="Meeting instructions, customer preferences, or preparation notes…"
                          disabled={submitting}
                        />

                        <small>
                          {notes.length}/10000 characters
                        </small>
                      </label>
                    </>
                  )}
                </div>

                <footer className="site-visits-modal-footer">
                  <p>
                    The visit is assigned to your current
                    account by default.
                  </p>

                  <div>
                    <button
                      type="button"
                      className="site-visits-secondary-button"
                      disabled={submitting}
                      onClick={() => setIsFormOpen(false)}
                    >
                      Cancel
                    </button>

                    <button
                      type="submit"
                      className="site-visits-primary-button"
                      disabled={
                        submitting ||
                        loadingOptions ||
                        !propertyId
                      }
                    >
                      {submitting ? (
                        <>
                          <span className="site-visits-button-spinner" />
                          Scheduling…
                        </>
                      ) : (
                        "+ Schedule visit"
                      )}
                    </button>
                  </div>
                </footer>
              </form>
            </section>
          </div>,
          document.body,
        )}
        {attendanceVisit &&
          createPortal(
            <div
              className="site-visits-modal-backdrop"
              onMouseDown={(event) => {
                if (
                  event.target === event.currentTarget &&
                  !attendanceSubmitting
                ) {
                  closeAttendanceForm();
                }
              }}
            >
              <section
                className="site-visits-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="attendance-modal-title"
              >
                <header className="site-visits-modal-header">
                  <div>
                    <span className="site-visits-eyebrow">
                      VISIT OUTCOME
                    </span>
                    <h2 id="attendance-modal-title">
                      Record attendance
                    </h2>
                    <p>
                      Record whether the appointment occurred and
                      capture the customer&apos;s feedback.
                    </p>
                  </div>

                  <button
                    type="button"
                    className="site-visits-modal-close"
                    aria-label="Close attendance form"
                    disabled={attendanceSubmitting}
                    onClick={closeAttendanceForm}
                  >
                    ×
                  </button>
                </header>

                <form
                  className="site-visits-modal-form"
                  onSubmit={handleAttendanceSubmit}
                >
                  <div className="site-visits-modal-body">
                    {attendanceError && (
                      <div
                        className="site-visits-alert site-visits-alert-error"
                        role="alert"
                      >
                        {attendanceError}
                      </div>
                    )}

                    <h3 className="site-visits-form-section-title">
                      Attendance
                    </h3>

                    <label className="site-visits-field">
                      <span>Visit status <b>*</b></span>
                      <select
                        value={attendanceStatus}
                        onChange={(event) => {
                          const nextStatus = event.target.value as
                            | "COMPLETED"
                            | "CANCELLED"
                            | "NO_SHOW";

                          setAttendanceStatus(nextStatus);

                          if (nextStatus !== "COMPLETED") {
                            setAttendanceOutcome("");
                          }
                        }}
                        required
                        disabled={attendanceSubmitting}
                      >
                        <option value="COMPLETED">Completed</option>
                        <option value="CANCELLED">Cancelled</option>
                        <option value="NO_SHOW">No show</option>
                      </select>
                    </label>

                    {attendanceStatus === "COMPLETED" && (
                      <label className="site-visits-field">
                        <span>Customer outcome</span>
                        <select
                          value={attendanceOutcome}
                          onChange={(event) =>
                            setAttendanceOutcome(
                              event.target.value as SiteVisitOutcome | "",
                            )
                          }
                          disabled={attendanceSubmitting}
                        >
                          <option value="">Select an outcome</option>
                          {OUTCOMES.map((item) => (
                            <option key={item.value} value={item.value}>
                              {item.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}

                    <h3 className="site-visits-form-section-title">
                      Customer feedback
                    </h3>

                    <label className="site-visits-field">
                      <span>Feedback and observations</span>
                      <textarea
                        rows={5}
                        maxLength={10000}
                        value={attendanceFeedback}
                        onChange={(event) =>
                          setAttendanceFeedback(event.target.value)
                        }
                        placeholder="Record customer comments, interest, concerns, or reasons for cancellation…"
                        disabled={attendanceSubmitting}
                      />
                      <small>
                        {attendanceFeedback.length}/10000 characters
                      </small>
                    </label>

                    <p>
                      Existing scheduling notes will be preserved.
                    </p>
                  </div>

                  <footer className="site-visits-modal-footer">
                    <p>Review the details before saving.</p>
                    <div>
                      <button
                        type="button"
                        className="site-visits-secondary-button"
                        onClick={closeAttendanceForm}
                        disabled={attendanceSubmitting}
                      >
                        Cancel
                      </button>

                      <button
                        type="submit"
                        className="site-visits-primary-button"
                        disabled={attendanceSubmitting}
                      >
                        {attendanceSubmitting
                          ? "Saving…"
                          : "Save attendance"}
                      </button>
                    </div>
                  </footer>
                </form>
              </section>
            </div>,
            document.body,
          )}

    </main>
  );
}
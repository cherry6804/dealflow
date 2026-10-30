import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";
import { DataGrid, type Column, type SortColumn } from "react-data-grid";
import "react-data-grid/lib/styles.css";

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
import {
  followUpsApi,
  type FollowUpCreateInput,
  type FollowUpType,
} from "../services/followUpApi";
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
  const [searchInput, setSearchInput] = useState("");
  const [visibleColumnKeys, setVisibleColumnKeys] = useState<string[]>([
    "property", "customer", "scheduledAt", "status", "notes",
  ]);
  const [columnMenuPosition, setColumnMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [sortColumns, setSortColumns] = useState<SortColumn[]>([]);
  const [compactGrid, setCompactGrid] = useState(() => typeof window !== "undefined" && window.innerWidth >= 1600);

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

const [followUpVisit, setFollowUpVisit] =
  useState<SiteVisit | null>(null);
const [followUpType, setFollowUpType] =
  useState<FollowUpType>("CALL");
const [followUpTitle, setFollowUpTitle] =
  useState("Follow up after site visit");
const [followUpDescription, setFollowUpDescription] =
  useState("");
const [followUpDueAt, setFollowUpDueAt] = useState(() => {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(10, 0, 0, 0);
  return localDateTimeValue(date);
});
const [followUpError, setFollowUpError] = useState("");
const [followUpSubmitting, setFollowUpSubmitting] = useState(false);

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

  useEffect(() => {
    const updateDensity = () => setCompactGrid(window.innerWidth >= 1600);
    updateDensity();
    window.addEventListener("resize", updateDensity, { passive: true });
    return () => window.removeEventListener("resize", updateDensity);
  }, []);

  useEffect(() => {
    if (!columnMenuPosition) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setColumnMenuPosition(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [columnMenuPosition]);

  const openColumnMenu = useCallback((event: { currentTarget: HTMLButtonElement }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 240;
    setColumnMenuPosition((current) => current ? null : {
      top: Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - 300)),
      left: Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12)),
    });
  }, []);

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

function openFollowUpForm(visit: SiteVisit) {
  setFollowUpVisit(visit);
  setFollowUpType("CALL");
  setFollowUpTitle("Follow up after site visit");
  setFollowUpDescription("");

  const date = new Date();
  date.setDate(date.getDate() + 1);
  date.setHours(10, 0, 0, 0);

  setFollowUpDueAt(localDateTimeValue(date));
  setFollowUpError("");
  setMessage("");
}

function closeFollowUpForm() {
  if (followUpSubmitting) return;
  setFollowUpVisit(null);
  setFollowUpError("");
}

async function handleFollowUpSubmit(
  event: FormEvent<HTMLFormElement>,
) {
  event.preventDefault();
  setFollowUpError("");
  setMessage("");

  if (!followUpVisit?.lead_id) {
    setFollowUpError(
      "A linked lead is required to create this follow-up.",
    );
    return;
  }

  const dueAt = new Date(followUpDueAt);

  if (Number.isNaN(dueAt.getTime())) {
    setFollowUpError("Enter a valid follow-up date and time.");
    return;
  }

  if (dueAt.getTime() <= Date.now()) {
    setFollowUpError("The follow-up must be scheduled in the future.");
    return;
  }

  const payload: FollowUpCreateInput = {
    follow_up_type: followUpType,
    title: followUpTitle.trim(),
    description: followUpDescription.trim() || null,
    due_at: dueAt.toISOString(),
  };

  if (!payload.title) {
    setFollowUpError("Enter a follow-up title.");
    return;
  }

  setFollowUpSubmitting(true);

  try {
    const created = await followUpsApi.createFromSiteVisit(
      followUpVisit.id,
      payload,
    );

    setFollowUpVisit(null);
    setMessage(`Follow-up created: ${created.title}`);
    await loadVisits();
  } catch (error) {
    setFollowUpError(errorMessage(error));
  } finally {
    setFollowUpSubmitting(false);
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

  const filteredVisits = useMemo(() => {
    const query = searchInput.trim().toLowerCase();
    if (!query) return visits;
    return visits.filter((visit) => {
      const property = propertyById.get(visit.property_id);
      const lead = visit.lead_id ? leadById.get(visit.lead_id) : undefined;
      const customer = visit.customer_profile_id ? customerById.get(visit.customer_profile_id) : undefined;
      const person = customer ? customerLabel(customer) : lead ? `Lead ${lead.id.slice(0, 8)}` : "";
      return [property ? propertyLabel(property) : visit.property_id, person,
        dateLabel(visit.scheduled_at), timeLabel(visit.scheduled_at),
        statusLabel(visit.status), visit.notes ?? ""]
        .join(" ").toLowerCase().includes(query);
    });
  }, [visits, searchInput, propertyById, leadById, customerById]);

  const sortedVisits = useMemo(() => {
    if (!sortColumns.length) return filteredVisits;
    return [...filteredVisits].sort((left, right) => {
      for (const sort of sortColumns) {
        const value = (visit: SiteVisit): string | number => {
          const property = propertyById.get(visit.property_id);
          const lead = visit.lead_id ? leadById.get(visit.lead_id) : undefined;
          const customer = visit.customer_profile_id ? customerById.get(visit.customer_profile_id) : undefined;
          switch (sort.columnKey) {
            case "property": return property ? propertyLabel(property) : visit.property_id;
            case "customer": return customer ? customerLabel(customer) : lead ? `Lead ${lead.id}` : "";
            case "scheduledAt": return new Date(visit.scheduled_at).getTime() || 0;
            case "status": return statusLabel(visit.status);
            case "notes": return visit.notes ?? "";
            default: return "";
          }
        };
        const a = value(left); const b = value(right);
        const comparison = typeof a === "number" && typeof b === "number"
          ? a - b
          : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
        if (comparison) return sort.direction === "DESC" ? -comparison : comparison;
      }
      return 0;
    });
  }, [filteredVisits, sortColumns, propertyById, leadById, customerById]);

  const columns = useMemo<readonly Column<SiteVisit>[]>(() => [
    {
      key: "property",
      name: "Property / Location",
      minWidth: 210,
      width: 300,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => {
        const property = propertyById.get(row.property_id);

        return (
          <div className="visits-grid-primary-cell">
            <strong>{property ? propertyLabel(property) : `Property · ${row.property_id.slice(0, 8)}`}</strong>
            <small>{property?.property_type?.replaceAll("_", " ") ?? "Property visit"}</small>
          </div>
        );
      },
    },
    {
      key: "customer",
      name: "Lead / Customer",
      minWidth: 150,
      width: 190,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => {
        const customer = row.customer_profile_id ? customerById.get(row.customer_profile_id) : undefined;
        const lead = row.lead_id ? leadById.get(row.lead_id) : undefined;

        return customer ? customerLabel(customer) : lead ? `Lead · ${lead.id.slice(0, 8)}` : "—";
      },
    },
    {
      key: "scheduledAt",
      name: "Date & Time",
      minWidth: 140,
      width: 165,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => (
        <div className="visits-grid-primary-cell">
          <strong>{dateLabel(row.scheduled_at)}</strong>
          <small>{timeLabel(row.scheduled_at)}{row.ends_at ? ` – ${timeLabel(row.ends_at)}` : ""}</small>
        </div>
      ),
    },
    {
      key: "status",
      name: "Status",
      minWidth: 125,
      width: 130,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => (
        <span className={`visits-grid-status visits-grid-status-${row.status.toLowerCase().replaceAll("_", "-")}`}>
          {statusLabel(row.status)}
        </span>
      ),
    },
    {
      key: "notes",
      name: "Notes",
      minWidth: 160,
      width: 240,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => (
        <span className="visits-grid-notes" title={row.notes || "No notes"}>
          {row.notes || "—"}
        </span>
      ),
    },
    {
      key: "actions",
      name: "Actions",
      width: 160,
      minWidth: 145,
      sortable: false,
      resizable: false,
      renderCell: ({ row }) => (
        <div className="visits-grid-actions">
          {row.status === "SCHEDULED" && (
            <button
              type="button"
              className="visits-grid-action-button"
              onClick={() => openAttendanceForm(row)}
              disabled={attendanceSubmitting}
            >
              Record attendance
            </button>
          )}
          {row.status === "COMPLETED" && row.outcome === "FOLLOW_UP_REQUIRED" && row.lead_id && !row.has_follow_up && (
            <button
              type="button"
              className="visits-grid-action-button visits-grid-action-primary"
              onClick={() => openFollowUpForm(row)}
              disabled={followUpSubmitting}
            >
              Create follow-up
            </button>
          )}
          {row.status !== "SCHEDULED" && !(row.status === "COMPLETED" && row.outcome === "FOLLOW_UP_REQUIRED" && row.lead_id && !row.has_follow_up) && (
            <span className="visits-grid-muted">—</span>
          )}
        </div>
      ),
    },
    {
      key: "configure",
      name: "",
      width: "1fr",
      minWidth: 44,
      sortable: false,
      resizable: false,
      renderHeaderCell: () => (
        <button
          className="visits-configure-columns-button"
          type="button"
          onClick={openColumnMenu}
          aria-label="Configure table columns"
          title="Configure columns"
          aria-expanded={columnMenuPosition !== null}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="4" y="4" width="16" height="16" rx="2" />
            <path d="M9 4v16M15 4v16" />
          </svg>
        </button>
      ),
      renderCell: () => null,
    },
  ], [propertyById, customerById, leadById, attendanceSubmitting, followUpSubmitting, openColumnMenu, columnMenuPosition]);

  const visibleColumns = useMemo(() => columns.filter((column) => column.key === "configure" || column.key === "actions" || visibleColumnKeys.includes(column.key)), [columns, visibleColumnKeys]);

  return (
    <main className="site-visits-page">
      <header className="site-visits-header">
        <div className="site-visits-heading-copy">
          <h1>Site visits</h1>
          <p>Manage property appointments and keep every customer visit on track.</p>
        </div>
        <button type="button" className="site-visits-primary-button" onClick={openForm}>
          <span aria-hidden="true">＋</span> Schedule visit
        </button>
      </header>

      {message && <div className="site-visits-alert site-visits-alert-success" role="status"><span>{message}</span><button type="button" aria-label="Dismiss success message" onClick={() => setMessage("")}>×</button></div>}
      {loadError && <div className="site-visits-alert site-visits-alert-error" role="alert"><span>{loadError}</span><button type="button" onClick={() => void loadVisits()}>Retry</button></div>}
      {optionsError && <div className="site-visits-alert site-visits-alert-error" role="alert"><span>Form options could not be loaded: {optionsError}</span><button type="button" onClick={() => void loadOptions()}>Retry</button></div>}

      <div className="visits-filterbar">
        <label className="visits-search-field">
          <span className="site-visits-visually-hidden">Search site visits</span>
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
          <input type="search" value={searchInput} maxLength={320} placeholder="Search property, customer, date, status or notes" onChange={(event) => setSearchInput(event.target.value)} />
          {searchInput && <button type="button" aria-label="Clear search" onClick={() => setSearchInput("")}>×</button>}
        </label>
        <label className="visits-filter-field"><span>Status</span><select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value as SiteVisitStatus | ""); setPage(1); }}>
          {STATUSES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select></label>
        <button type="button" className="site-visits-secondary-button" onClick={() => void loadVisits()} disabled={loading}>{loading ? "Refreshing…" : "↻ Refresh"}</button>
      </div>

      <section className="visits-grid-shell" aria-label="Site visits">
        {loading && visits.length === 0 ? <div className="visits-grid-state" role="status"><span className="site-visits-spinner"/>Loading site visits…</div> : loadError && visits.length === 0 ? <div className="visits-grid-state">Unable to load site visits. Use Retry above.</div> : <DataGrid
          className="visits-react-data-grid"
          aria-label="Site visits directory"
          columns={visibleColumns}
          rows={sortedVisits}
          rowKeyGetter={(row) => row.id}
          rowHeight={compactGrid ? 48 : 62}
          headerRowHeight={52}
          defaultColumnOptions={{ resizable: true, sortable: true }}
          sortColumns={sortColumns}
          onSortColumnsChange={setSortColumns}
          style={{ height: Math.min(52 + sortedVisits.length * (compactGrid ? 48 : 62), Math.max(260, (typeof window !== "undefined" ? window.innerHeight : 900) * 0.68)), minHeight: 52 + Math.min(sortedVisits.length, 1) * (compactGrid ? 48 : 62) }}
          renderers={{ noRowsFallback: <div className="visits-grid-no-rows">{searchInput || statusFilter ? "No site visits match these filters." : "No site visits yet. Schedule your first visit to get started."}</div> }}
        />}
        <footer className="visits-grid-footer" aria-live="polite">
          <div className="visits-grid-footer-count"><strong>{total.toLocaleString("en-IN")}</strong> {total === 1 ? "visit" : "visits"} in your workspace <span>Showing {total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)}</span></div>
          <div className="visits-grid-footer-right">
            {totalPages > 1 && <div className="visits-pagination-controls"><button type="button" disabled={page <= 1 || loading} onClick={() => setPage((current) => current - 1)}>Previous</button><span>Page {page} of {totalPages}</span><button type="button" disabled={page >= totalPages || loading} onClick={() => setPage((current) => current + 1)}>Next</button></div>}
            <span className="visits-grid-footer-status"><span className="visits-grid-footer-status-dot" aria-hidden="true"/>{loading ? "Updating records" : "You're all caught up"}</span>
          </div>
        </footer>
      </section>

      {columnMenuPosition && createPortal(<div className="visits-column-menu-layer" onPointerDown={() => setColumnMenuPosition(null)} role="presentation"><div className="visits-column-menu" style={{ top: columnMenuPosition.top, left: columnMenuPosition.left }} role="dialog" aria-label="Configure table columns" onPointerDown={(event) => event.stopPropagation()}><div className="visits-column-menu-heading"><div><strong>Configure columns</strong><span>Choose which fields are visible.</span></div><button type="button" aria-label="Close column configuration" onClick={() => setColumnMenuPosition(null)}>×</button></div>{[{key:"property",label:"Property / Location"},{key:"customer",label:"Lead / Customer"},{key:"scheduledAt",label:"Date & Time"},{key:"status",label:"Status"},{key:"notes",label:"Notes"}].map((column) => <label className="visits-column-option" key={column.key}><input type="checkbox" checked={visibleColumnKeys.includes(column.key)} onChange={(event) => setVisibleColumnKeys((current) => event.target.checked ? [...current, column.key] : current.filter((key) => key !== column.key))}/><span>{column.label}</span></label>)}<div className="visits-column-menu-footer"><button type="button" onClick={() => setVisibleColumnKeys(["property","customer","scheduledAt","status","notes"])}>Reset columns</button><button type="button" onClick={() => setColumnMenuPosition(null)}>Done</button></div></div></div>, document.body)}

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

          {followUpVisit &&
            createPortal(
              <div
                className="site-visits-modal-backdrop"
                onMouseDown={(event) => {
                  if (
                    event.target === event.currentTarget &&
                    !followUpSubmitting
                  ) {
                    closeFollowUpForm();
                  }
                }}
              >
                <section
                  className="site-visits-modal"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="follow-up-modal-title"
                >
                  <header className="site-visits-modal-header">
                    <div>
                      <span className="site-visits-eyebrow">
                        POST-VISIT ACTION
                      </span>
                      <h2 id="follow-up-modal-title">
                        Create follow-up
                      </h2>
                      <p>
                        Schedule the next action for this lead.
                      </p>
                    </div>

                    <button
                      type="button"
                      className="site-visits-modal-close"
                      aria-label="Close follow-up form"
                      disabled={followUpSubmitting}
                      onClick={closeFollowUpForm}
                    >
                      ×
                    </button>
                  </header>

                  <form
                    className="site-visits-modal-form"
                    onSubmit={handleFollowUpSubmit}
                  >
                    <div className="site-visits-modal-body">
                      {followUpError && (
                        <div
                          className="site-visits-alert site-visits-alert-error"
                          role="alert"
                        >
                          {followUpError}
                        </div>
                      )}

                      <label className="site-visits-field">
                        <span>Follow-up type *</span>
                        <select
                          value={followUpType}
                          onChange={(event) =>
                            setFollowUpType(event.target.value as FollowUpType)
                          }
                          required
                          disabled={followUpSubmitting}
                        >
                          <option value="CALL">Call</option>
                          <option value="EMAIL">Email</option>
                          <option value="MEETING">Meeting</option>
                          <option value="VISIT">Visit</option>
                          <option value="TASK">Task</option>
                          <option value="OTHER">Other</option>
                        </select>
                      </label>

                      <label className="site-visits-field">
                        <span>Title *</span>
                        <input
                          value={followUpTitle}
                          onChange={(event) =>
                            setFollowUpTitle(event.target.value)
                          }
                          maxLength={200}
                          required
                          disabled={followUpSubmitting}
                        />
                      </label>

                      <label className="site-visits-field">
                        <span>Description</span>
                        <textarea
                          rows={4}
                          maxLength={10000}
                          value={followUpDescription}
                          onChange={(event) =>
                            setFollowUpDescription(event.target.value)
                          }
                          placeholder="Next steps, customer questions, or commitments…"
                          disabled={followUpSubmitting}
                        />
                      </label>

                      <label className="site-visits-field">
                        <span>Due date and time *</span>
                        <input
                          type="datetime-local"
                          value={followUpDueAt}
                          onChange={(event) =>
                            setFollowUpDueAt(event.target.value)
                          }
                          required
                          disabled={followUpSubmitting}
                        />
                        <small>
                          Uses your device's local timezone. Assigned to your
                          current account by default.
                        </small>
                      </label>
                    </div>

                    <footer className="site-visits-modal-footer">
                      <p>The follow-up will be linked to this site visit.</p>
                      <div>
                        <button
                          type="button"
                          className="site-visits-secondary-button"
                          disabled={followUpSubmitting}
                          onClick={closeFollowUpForm}
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          className="site-visits-primary-button"
                          disabled={followUpSubmitting}
                        >
                          {followUpSubmitting
                            ? "Creating…"
                            : "Create follow-up"}
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
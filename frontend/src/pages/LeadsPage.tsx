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
import LeadTimeline from "../components/LeadTimeline";
import "./LeadsPage.css";

import {
  followUpsApi,
  type BulkFollowUpResponse,
  type FollowUp,
  type FollowUpType,
} from "../services/followUpApi";


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
  return [currentStatus, ...ALLOWED_STATUS_TRANSITIONS[currentStatus]];
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

function toLocalDateTimeInput(value: string | null): string {
  if (!value) return "";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "";

  const localDate = new Date(
    date.getTime() - date.getTimezoneOffset() * 60_000,
  );

  return localDate.toISOString().slice(0, 16);
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);

  const [timelineLead, setTimelineLead] = useState<{
    id: string;
    contactName: string;
  } | null>(null);

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
  const [statusPromptLead, setStatusPromptLead] = useState<Lead | null>(null);
const [pendingStatus, setPendingStatus] = useState<LeadStatus | null>(null);
const [statusPromptAction, setStatusPromptAction] = useState("");
const [statusPromptDate, setStatusPromptDate] = useState("");
const [statusPromptError, setStatusPromptError] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [formError, setFormError] = useState("");

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingLead, setEditingLead] = useState<Lead | null>(null);
  const [form, setForm] = useState<LeadForm>(EMPTY_FORM);

  const [contactSearch, setContactSearch] = useState("");
  const [contactLoading, setContactLoading] = useState(false);
  const [contactError, setContactError] = useState("");
  const [formContacts, setFormContacts] = useState<Contact[]>([]);
  const [nextActionDate, setNextActionDate] = useState("");

  const [followUps, setFollowUps] = useState<FollowUp[]>([]);

const [selectedFollowUpIds, setSelectedFollowUpIds] = useState<string[]>([]);
const [bulkRescheduleDueAt, setBulkRescheduleDueAt] = useState("");

const [selectedFollowUpLead, setSelectedFollowUpLead] =
  useState<Lead | null>(null);
const [followUpsLoading, setFollowUpsLoading] = useState(false);
const [followUpSaving, setFollowUpSaving] = useState(false);
const [followUpError, setFollowUpError] = useState("");
const [followUpSuccess, setFollowUpSuccess] = useState("");

const [followUpType, setFollowUpType] =
  useState<FollowUpType>("CALL");
const [followUpTitle, setFollowUpTitle] = useState("");
const [followUpDescription, setFollowUpDescription] = useState("");
const [followUpDueAt, setFollowUpDueAt] = useState("");
const [reschedulingFollowUpId, setReschedulingFollowUpId] =
  useState<string | null>(null);
const [rescheduleDueAt, setRescheduleDueAt] = useState("");
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
        setEditingLead(null);
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
    if (!isFormOpen || editingLead) return;

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
  }, [isFormOpen, editingLead, contactSearch]);

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
    setEditingLead(null);
    setForm(EMPTY_FORM);
    setFormError("");
    setContactError("");
    setContactSearch("");
    setFormContacts([]);
    setNextActionDate("");
    setIsFormOpen(true);
  }

  function openEditForm(lead: Lead) {
    setEditingLead(lead);
    setForm({
      contact_id: lead.contact_id,
      interest: lead.interest ?? "",
      next_action: lead.next_action ?? "",
    });
    setFormError("");
    setContactError("");
    setContactSearch("");
    setFormContacts([]);
    setNextActionDate(toLocalDateTimeInput(lead.next_action_at));
    setIsFormOpen(true);
  }

  async function handleCreateLead(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setSuccess("");

    const nextAction = form.next_action.trim();

    if (nextActionDate && !nextAction) {
      setFormError("Enter a next action when scheduling a date.");
      return;
    }

    if (editingLead) {
      setSaving(true);

      try {
        await leadsApi.update(editingLead.id, {
          next_action: nextAction || null,
          next_action_at: toIsoDateTime(nextActionDate),
        });

        setIsFormOpen(false);
        setEditingLead(null);
        setSuccess("Lead next action and follow-up updated successfully.");
        await loadLeads();
      } catch (updateError) {
        setFormError(getErrorMessage(updateError));
      } finally {
        setSaving(false);
      }

      return;
    }

    if (!form.contact_id) {
      setFormError("Select a contact before creating a lead.");
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
      setEditingLead(null);
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

  const requiredActionStatuses: LeadStatus[] = [
    "CONTACTED",
    "QUALIFIED",
    "MATCHING",
    "VISIT",
    "NEGOTIATION",
  ];

  // Ask for a next action before moving an active lead into a key stage.
  if (
    lead.is_active &&
    requiredActionStatuses.includes(newStatus) &&
    !lead.next_action?.trim()
  ) {
    setStatusPromptLead(lead);
    setPendingStatus(newStatus);
    setStatusPromptAction("");
    setStatusPromptDate("");
    setStatusPromptError("");
    return;
  }

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
    await loadLeads();
  } finally {
    setUpdatingLeadId(null);
  }
}

async function handleStatusPromptSubmit(
  event: FormEvent<HTMLFormElement>,
) {
  event.preventDefault();

  const lead = statusPromptLead;
  const newStatus = pendingStatus;
  const nextAction = statusPromptAction.trim();

  if (!lead || !newStatus) {
    setStatusPromptError("Unable to update the lead. Please try again.");
    return;
  }

  if (!nextAction) {
    setStatusPromptError("Enter the next action before continuing.");
    return;
  }

  if (statusPromptDate && !toIsoDateTime(statusPromptDate)) {
    setStatusPromptError("Enter a valid next-action date and time.");
    return;
  }

  setUpdatingLeadId(lead.id);
  setStatusPromptError("");
  setError("");
  setSuccess("");

  try {
    await leadsApi.update(lead.id, {
      status: newStatus,
      next_action: nextAction,
      next_action_at: toIsoDateTime(statusPromptDate),
    });

    setStatusPromptLead(null);
    setPendingStatus(null);
    setStatusPromptAction("");
    setStatusPromptDate("");
    setStatusPromptError("");

    setSuccess(
      `Lead status updated to ${formatLabel(newStatus)} and next action saved.`,
    );

    await loadLeads();
  } catch (updateError) {
    setStatusPromptError(getErrorMessage(updateError));
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

    async function loadFollowUpsForLead(lead: Lead) {
    setFollowUpsLoading(true);
    setFollowUpError("");

    try {
      const result = await followUpsApi.list();
      setFollowUps(result.filter((item) => item.lead_id === lead.id));
    } catch (loadError) {
      setFollowUpError(getErrorMessage(loadError));
    } finally {
      setFollowUpsLoading(false);
    }
  }

  function openFollowUps(lead: Lead) {
    setSelectedFollowUpLead(lead);
    setSelectedFollowUpIds([]);
setBulkRescheduleDueAt("");
    setFollowUps([]);
    setFollowUpError("");
    setFollowUpSuccess("");
    setFollowUpTitle("");
    setFollowUpDescription("");
    setFollowUpDueAt("");
    setFollowUpType("CALL");
    setReschedulingFollowUpId(null);
    setRescheduleDueAt("");
    void loadFollowUpsForLead(lead);
  }

  async function handleCreateFollowUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const lead = selectedFollowUpLead;
    const title = followUpTitle.trim();
    const dueAt = toIsoDateTime(followUpDueAt);

    if (!lead) {
      setFollowUpError("Select a lead before creating a follow-up.");
      return;
    }

    if (!title) {
      setFollowUpError("Enter a title for the follow-up.");
      return;
    }

    if (!dueAt) {
      setFollowUpError("Enter a valid follow-up date and time.");
      return;
    }

    setFollowUpSaving(true);
    setFollowUpError("");
    setFollowUpSuccess("");

    try {
      await followUpsApi.create(lead.id, {
        follow_up_type: followUpType,
        title,
        description: followUpDescription.trim() || null,
        due_at: dueAt,
      });

      setFollowUpTitle("");
      setFollowUpDescription("");
      setFollowUpDueAt("");
      setFollowUpType("CALL");
      setFollowUpSuccess("Follow-up created successfully.");
      await loadFollowUpsForLead(lead);
    } catch (createError) {
      setFollowUpError(getErrorMessage(createError));
    } finally {
      setFollowUpSaving(false);
    }
  }

  async function handleCompleteFollowUp(followUp: FollowUp) {
    const lead = selectedFollowUpLead;
    if (!lead || followUpSaving) return;

    setFollowUpSaving(true);
    setFollowUpError("");
    setFollowUpSuccess("");

    try {
      await followUpsApi.complete(followUp.id);
      setFollowUps((current) =>
        current.filter((item) => item.id !== followUp.id),
      );
      setFollowUpSuccess("Follow-up marked as completed.");
    } catch (completeError) {
      setFollowUpError(getErrorMessage(completeError));
    } finally {
      setFollowUpSaving(false);
    }
  }

  async function handleRescheduleFollowUp(followUp: FollowUp) {
    const lead = selectedFollowUpLead;
    const dueAt = toIsoDateTime(rescheduleDueAt);

    if (!lead || !dueAt || followUpSaving) {
      setFollowUpError("Enter a valid new date and time.");
      return;
    }

    setFollowUpSaving(true);
    setFollowUpError("");
    setFollowUpSuccess("");

    try {
      await followUpsApi.reschedule(followUp.id, { due_at: dueAt });
      setReschedulingFollowUpId(null);
      setRescheduleDueAt("");
      setFollowUpSuccess("Follow-up rescheduled successfully.");
      await loadFollowUpsForLead(lead);
    } catch (rescheduleError) {
      setFollowUpError(getErrorMessage(rescheduleError));
    } finally {
      setFollowUpSaving(false);
    }
  }


function toggleFollowUpSelection(followUpId: string) {
  setSelectedFollowUpIds((current) =>
    current.includes(followUpId)
      ? current.filter((id) => id !== followUpId)
      : [...current, followUpId],
  );
}

function toggleAllPendingFollowUps() {
  const pendingIds = followUps
    .filter((item) => item.status === "PENDING")
    .map((item) => item.id);

  const allSelected =
    pendingIds.length > 0 &&
    pendingIds.every((id) => selectedFollowUpIds.includes(id));

  setSelectedFollowUpIds((current) =>
    allSelected
      ? current.filter((id) => !pendingIds.includes(id))
      : [...new Set([...current, ...pendingIds])],
  );
}

function showBulkFollowUpResult(
  result: BulkFollowUpResponse,
  action: "completed" | "rescheduled",
) {
  setFollowUpSuccess(
    `${result.succeeded} follow-up(s) ${action} successfully; ${result.failed} failed.`,
  );

  if (result.failed > 0) {
    const failures = result.results
      .filter((item) => !item.success)
      .map((item) => `${item.follow_up_id}: ${item.message}`)
      .join(" ");

    setFollowUpError(failures);
  }
}

async function handleBulkCompleteFollowUps() {
  const ids = followUps
    .filter(
      (item) =>
        item.status === "PENDING" &&
        selectedFollowUpIds.includes(item.id),
    )
    .map((item) => item.id);

  if (ids.length === 0 || followUpSaving) return;

  setFollowUpSaving(true);
  setFollowUpError("");
  setFollowUpSuccess("");

  try {
    const result = await followUpsApi.bulkComplete({
      follow_up_ids: ids,
    });

    showBulkFollowUpResult(result, "completed");

    setSelectedFollowUpIds((current) =>
      current.filter(
        (id) => !result.results.some(
          (item) => item.follow_up_id === id && item.success,
        ),
      ),
    );

    if (selectedFollowUpLead) {
      await loadFollowUpsForLead(selectedFollowUpLead);
    }
  } catch (bulkError) {
    setFollowUpError(getErrorMessage(bulkError));
  } finally {
    setFollowUpSaving(false);
  }
}

async function handleBulkRescheduleFollowUps() {
  const dueAt = toIsoDateTime(bulkRescheduleDueAt);

  const ids = followUps
    .filter(
      (item) =>
        item.status === "PENDING" &&
        selectedFollowUpIds.includes(item.id),
    )
    .map((item) => item.id);

  if (!dueAt) {
    setFollowUpError("Enter a valid bulk reschedule date and time.");
    return;
  }

  if (ids.length === 0 || followUpSaving) return;

  setFollowUpSaving(true);
  setFollowUpError("");
  setFollowUpSuccess("");

  try {
    const result = await followUpsApi.bulkReschedule({
      follow_up_ids: ids,
      due_at: dueAt,
    });

    showBulkFollowUpResult(result, "rescheduled");

    setSelectedFollowUpIds((current) =>
      current.filter(
        (id) => !result.results.some(
          (item) => item.follow_up_id === id && item.success,
        ),
      ),
    );

    if (selectedFollowUpLead) {
      await loadFollowUpsForLead(selectedFollowUpLead);
    }
  } catch (bulkError) {
    setFollowUpError(getErrorMessage(bulkError));
  } finally {
    setFollowUpSaving(false);
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
            <span className="leads-search-icon" aria-hidden="true">
              ◷
            </span>
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
            <div className="leads-empty-icon" aria-hidden="true">
              ↗
            </div>
            <h3>
              {search ||
              statusFilter ||
              interestFilter ||
              activeFilter !== "active"
                ? "No matching leads"
                : "Your pipeline starts here"}
            </h3>
            <p>
              {search ||
              statusFilter ||
              interestFilter ||
              activeFilter !== "active"
                ? "Try changing your search or filters."
                : "Create a lead from an existing contact to start tracking an opportunity."}
            </p>

            {search ||
            statusFilter ||
            interestFilter ||
            activeFilter !== "active" ? (
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
                            disabled={busy || saving}
                            onClick={() => openEditForm(lead)}
                          >
                            Edit
                          </button>

                          <button
                            className="leads-text-button"
                            type="button"
                            onClick={() =>
                              setTimelineLead({
                                id: lead.id,
                                contactName: getContactName(contact),
                              })
                            }
                          >
                            View timeline
                          </button>
                          <button
                            className="leads-text-button"
                            type="button"
                            disabled={busy || !lead.is_active}
                            onClick={() => openFollowUps(lead)}
                          >
                            Follow-ups
                          </button>
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
                  Page {page}
                  {totalPages > 0 ? ` of ${totalPages}` : ""}
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

{statusPromptLead &&
  createPortal(
    <div
      className="leads-modal-backdrop"
      onMouseDown={(event) => {
        if (
          event.target === event.currentTarget &&
          !updatingLeadId
        ) {
          setStatusPromptLead(null);
          setPendingStatus(null);
          setStatusPromptAction("");
          setStatusPromptDate("");
          setStatusPromptError("");
        }
      }}
    >
      <section
        className="leads-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="status-prompt-title"
      >
        <header className="leads-modal-header">
          <div>
            <span className="leads-eyebrow">
              FOLLOW-UP INTELLIGENCE
            </span>
            <h2 id="status-prompt-title">
              Set the next action
            </h2>
            <p>
              Before moving this lead to{" "}
              <strong>
                {pendingStatus ? formatLabel(pendingStatus) : ""}
              </strong>
              , define what needs to happen next.
            </p>
          </div>

          <button
            className="leads-modal-close"
            type="button"
            aria-label="Cancel status change"
            disabled={updatingLeadId !== null}
            onClick={() => {
              setStatusPromptLead(null);
              setPendingStatus(null);
              setStatusPromptAction("");
              setStatusPromptDate("");
              setStatusPromptError("");
            }}
          >
            ×
          </button>
        </header>

        <form
          className="leads-form"
          onSubmit={handleStatusPromptSubmit}
        >
          <div className="leads-form-body">
            {statusPromptError && (
              <div
                className="leads-alert leads-alert-error"
                role="alert"
              >
                {statusPromptError}
              </div>
            )}

            <label className="leads-form-field">
              <span>
                Next action <span aria-hidden="true">*</span>
              </span>
              <input
                type="text"
                required
                maxLength={500}
                autoFocus
                value={statusPromptAction}
                onChange={(event) =>
                  setStatusPromptAction(event.target.value)
                }
                placeholder="e.g. Call the lead to discuss requirements"
                disabled={updatingLeadId !== null}
              />
              <span className="leads-field-hint">
                Specify a concrete action to keep this opportunity moving.
              </span>
            </label>

            <label className="leads-form-field">
              <span>Next action date and time (optional)</span>
              <input
                type="datetime-local"
                value={statusPromptDate}
                onChange={(event) =>
                  setStatusPromptDate(event.target.value)
                }
                disabled={updatingLeadId !== null}
              />
            </label>
          </div>

          <footer className="leads-form-actions">
            <button
              className="leads-secondary-button"
              type="button"
              disabled={updatingLeadId !== null}
              onClick={() => {
                setStatusPromptLead(null);
                setPendingStatus(null);
                setStatusPromptAction("");
                setStatusPromptDate("");
                setStatusPromptError("");
              }}
            >
              Cancel
            </button>

            <button
              className="leads-primary-button"
              type="submit"
              disabled={
                updatingLeadId !== null ||
                !statusPromptAction.trim()
              }
            >
              {updatingLeadId === statusPromptLead.id
                ? "Saving..."
                : "Save and update status"}
            </button>
          </footer>
        </form>
      </section>
    </div>,
    document.body,
  )}

        {timelineLead && (
          <LeadTimeline
            leadId={timelineLead.id}
            contactName={timelineLead.contactName}
            onClose={() => setTimelineLead(null)}
          />
        )}

{selectedFollowUpLead &&
  createPortal(
    <div
      className="leads-modal-backdrop"
      onMouseDown={(event) => {
        if (
          event.target === event.currentTarget &&
          !followUpSaving
        ) {
          setSelectedFollowUpLead(null);
        }
      }}
    >
      <section
        className="leads-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="follow-ups-title"
      >
        <header className="leads-modal-header">
          <div>
            <span className="leads-eyebrow">
              FOLLOW-UP MANAGEMENT
            </span>
            <h2 id="follow-ups-title">
              Follow-ups —{" "}
              {getContactName(
                contactById.get(selectedFollowUpLead.contact_id),
              )}
            </h2>
            <p>
              Schedule, complete, and reschedule activities for this lead.
            </p>
          </div>

          <button
            className="leads-modal-close"
            type="button"
            aria-label="Close follow-up manager"
            disabled={followUpSaving}
            onClick={() => setSelectedFollowUpLead(null)}
          >
            ×
          </button>
        </header>

        <div className="leads-form">
          <div className="leads-form-body">
            {followUpError && (
              <div
                className="leads-alert leads-alert-error"
                role="alert"
              >
                {followUpError}
              </div>
            )}

            {followUpSuccess && (
              <div
                className="leads-alert leads-alert-success"
                role="status"
              >
                {followUpSuccess}
              </div>
            )}

            <h3>Schedule a follow-up</h3>

            <form onSubmit={handleCreateFollowUp}>
              <label className="leads-form-field">
                <span>Activity type</span>
                <select
                  value={followUpType}
                  onChange={(event) =>
                    setFollowUpType(
                      event.target.value as FollowUpType,
                    )
                  }
                  disabled={followUpSaving}
                >
                  <option value="CALL">Call</option>
                  <option value="EMAIL">Email</option>
                  <option value="MEETING">Meeting</option>
                  <option value="VISIT">Visit</option>
                  <option value="TASK">Task</option>
                  <option value="OTHER">Other</option>
                </select>
              </label>

              <label className="leads-form-field">
                <span>Title *</span>
                <input
                  type="text"
                  required
                  maxLength={200}
                  value={followUpTitle}
                  onChange={(event) =>
                    setFollowUpTitle(event.target.value)
                  }
                  placeholder="e.g. Call to discuss property options"
                  disabled={followUpSaving}
                />
              </label>

              <label className="leads-form-field">
                <span>Description</span>
                <textarea
                  maxLength={10000}
                  rows={3}
                  value={followUpDescription}
                  onChange={(event) =>
                    setFollowUpDescription(event.target.value)
                  }
                  placeholder="Optional notes"
                  disabled={followUpSaving}
                />
              </label>

              <label className="leads-form-field">
                <span>Due date and time *</span>
                <input
                  type="datetime-local"
                  required
                  value={followUpDueAt}
                  onChange={(event) =>
                    setFollowUpDueAt(event.target.value)
                  }
                  disabled={followUpSaving}
                />
              </label>

              <button
                className="leads-primary-button"
                type="submit"
                disabled={followUpSaving}
              >
                {followUpSaving ? "Saving..." : "Create follow-up"}
              </button>
            </form>

            <hr />

            <h3>Pending follow-ups</h3>


{!followUpsLoading && followUps.some((item) => item.status === "PENDING") && (
  <div className="leads-form-body">
    <label className="leads-form-field">
      <span>
        <input
          type="checkbox"
          checked={
            followUps.filter((item) => item.status === "PENDING").length > 0 &&
            followUps
              .filter((item) => item.status === "PENDING")
              .every((item) => selectedFollowUpIds.includes(item.id))
          }
          onChange={toggleAllPendingFollowUps}
          disabled={followUpSaving}
        />
        {" "}Select all pending follow-ups
      </span>
    </label>

    <p>
      {selectedFollowUpIds.filter((id) =>
        followUps.some(
          (item) => item.id === id && item.status === "PENDING",
        ),
      ).length} selected
    </p>

    <div className="leads-form-actions">
      <button
        className="leads-primary-button"
        type="button"
        disabled={
          followUpSaving ||
          !followUps.some(
            (item) =>
              item.status === "PENDING" &&
              selectedFollowUpIds.includes(item.id),
          )
        }
        onClick={() => void handleBulkCompleteFollowUps()}
      >
        {followUpSaving ? "Processing..." : "Complete selected"}
      </button>
    </div>

    <label className="leads-form-field">
      <span>New date and time for selected follow-ups</span>
      <input
        type="datetime-local"
        value={bulkRescheduleDueAt}
        onChange={(event) => setBulkRescheduleDueAt(event.target.value)}
        disabled={followUpSaving}
      />
    </label>

    <button
      className="leads-secondary-button"
      type="button"
      disabled={
        followUpSaving ||
        !bulkRescheduleDueAt ||
        !followUps.some(
          (item) =>
            item.status === "PENDING" &&
            selectedFollowUpIds.includes(item.id),
        )
      }
      onClick={() => void handleBulkRescheduleFollowUps()}
    >
      Reschedule selected
    </button>
  </div>
)}


            {followUpsLoading ? (
              <p role="status">Loading follow-ups...</p>
            ) : followUps.length === 0 ? (
              <p>No pending follow-ups for this lead.</p>
            ) : (
              <div>
                {followUps.map((followUp) => (
                  <article
                    key={followUp.id}
                    className="follow-up-card"
                  >

{followUp.status === "PENDING" && (
  <label className="leads-form-field">
    <input
      type="checkbox"
      checked={selectedFollowUpIds.includes(followUp.id)}
      onChange={() => toggleFollowUpSelection(followUp.id)}
      disabled={followUpSaving}
    />
    {" "}Select this follow-up
  </label>
)}

                    <h4>{followUp.title}</h4>

                    <p>
                      {formatLabel(followUp.follow_up_type)}
                      {" Â· "}
                      {formatDateTime(followUp.due_at)}
                    </p>

                    {followUp.description && (
                      <p>{followUp.description}</p>
                    )}

                    {reschedulingFollowUpId === followUp.id ? (
                      <form
                        onSubmit={(event) => {
                          event.preventDefault();
                          void handleRescheduleFollowUp(followUp);
                        }}
                      >
                        <label className="leads-form-field">
                          <span>New date and time *</span>
                          <input
                            type="datetime-local"
                            required
                            value={rescheduleDueAt}
                            onChange={(event) =>
                              setRescheduleDueAt(event.target.value)
                            }
                            disabled={followUpSaving}
                          />
                        </label>

                        <div className="leads-form-actions">
                          <button
                            className="leads-primary-button"
                            type="submit"
                            disabled={followUpSaving}
                          >
                            Save new time
                          </button>

                          <button
                            className="leads-secondary-button"
                            type="button"
                            disabled={followUpSaving}
                            onClick={() => {
                              setReschedulingFollowUpId(null);
                              setRescheduleDueAt("");
                            }}
                          >
                            Cancel
                          </button>
                        </div>
                      </form>
                    ) : (
                      <div className="leads-form-actions">
                        <button
                          className="leads-primary-button"
                          type="button"
                          disabled={followUpSaving}
                          onClick={() =>
                            void handleCompleteFollowUp(followUp)
                          }
                        >
                          Complete
                        </button>

                        <button
                          className="leads-secondary-button"
                          type="button"
                          disabled={followUpSaving}
                          onClick={() => {
                            setReschedulingFollowUpId(followUp.id);
                            setRescheduleDueAt(
                              toLocalDateTimeInput(followUp.due_at),
                            );
                            setFollowUpError("");
                            setFollowUpSuccess("");
                          }}
                        >
                          Reschedule
                        </button>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </div>

          <footer className="leads-form-actions">
            <button
              className="leads-secondary-button"
              type="button"
              disabled={followUpSaving}
              onClick={() => setSelectedFollowUpLead(null)}
            >
              Close
            </button>
          </footer>
        </div>
      </section>
    </div>,
    document.body,
  )}

      </section>

      {isFormOpen &&
        createPortal(
          <div
            className="leads-modal-backdrop"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget && !saving) {
                setIsFormOpen(false);
                setEditingLead(null);
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
                  <h2 id="leads-modal-title">
                    {editingLead ? "Edit lead" : "Add a lead"}
                  </h2>
                  <p>
                    {editingLead
                      ? "Update the next action and follow-up schedule."
                      : "Choose a contact and capture the next step."}
                  </p>
                </div>

                <button
                  className="leads-modal-close"
                  type="button"
                  aria-label="Close form"
                  disabled={saving}
                  onClick={() => {
                    setIsFormOpen(false);
                    setEditingLead(null);
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

                  {!editingLead && (
                    <>
                      <label className="leads-form-field">
                        <span>Find contact</span>
                        <input
                          type="search"
                          value={contactSearch}
                          maxLength={320}
                          onChange={(event) =>
                            setContactSearch(event.target.value)
                          }
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
                            {contactLoading
                              ? "Loading contacts..."
                              : "Select a contact"}
                          </option>

                          {formContacts.map((contact) => (
                            <option value={contact.id} key={contact.id}>
                              {getContactName(contact)}
                              {contact.phone ? ` Â· ${contact.phone}` : ""}
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
                              No active contacts found. Add a contact first or
                              change your search.
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
                    </>
                  )}

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

                  {!editingLead && (
                    <p className="leads-field-hint">
                      New leads are created with the status New. You can update
                      the status as the opportunity progresses.
                    </p>
                  )}
                </div>

                <footer className="leads-form-actions">
                  <button
                    className="leads-secondary-button"
                    type="button"
                    onClick={() => {
                      setIsFormOpen(false);
                      setEditingLead(null);
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
                      saving ||
                      (!editingLead &&
                        (contactLoading || formContacts.length === 0))
                    }
                  >
                    {saving
                      ? "Saving..."
                      : editingLead
                        ? "Save changes"
                        : "Create lead"}
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

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type UIEvent,
} from "react";
import { createPortal } from "react-dom";
import { DataGrid, type Column, type SortColumn } from "react-data-grid";
import "react-data-grid/lib/styles.css";
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
import {
  followUpsApi,
  type BulkFollowUpResponse,
  type FollowUp,
  type FollowUpType,
} from "../services/followUpApi";
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

interface InlineChoiceOption {
  value: string;
  label: string;
  tone: string;
}

function InlineChoiceMenu({
  value,
  options,
  ariaLabel,
  disabled = false,
  onChange,
}: {
  value: string;
  options: InlineChoiceOption[];
  ariaLabel: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number; width: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value) ?? options[0];

  const updatePosition = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = Math.max(rect.width, 184);
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    const estimatedHeight = Math.min(options.length * 38 + 12, 300);
    const top = rect.bottom + estimatedHeight > window.innerHeight - 8 && rect.top > estimatedHeight
      ? rect.top - estimatedHeight - 4
      : rect.bottom + 4;
    setPosition({ top: Math.max(8, top), left, width });
  }, [options.length]);

  useEffect(() => {
    if (!open) return;
    updatePosition();
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, updatePosition]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`leads-choice-trigger ${selected?.tone ?? ""}`}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span>{selected?.label ?? "Select"}</span>
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m7 10 5 5 5-5" /></svg>
      </button>
      {open && position && createPortal(
        <div
          ref={menuRef}
          className="leads-choice-menu"
          role="listbox"
          aria-label={ariaLabel}
          style={{ top: position.top, left: position.left, width: position.width }}
        >
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={option.value === value}
              className={`leads-choice-option ${option.tone} ${option.value === value ? "is-selected" : ""}`}
              onClick={() => {
                setOpen(false);
                if (option.value !== value) onChange(option.value);
              }}
            >
              <span className="leads-choice-option-label">{option.label}</span>
              {option.value === value && <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12 4 4L19 6" /></svg>}
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
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
  const [visibleColumnKeys, setVisibleColumnKeys] = useState<string[]>(["lead", "status", "interest", "nextAction", "createdAt"]);
  const [columnMenuPosition, setColumnMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [compactGrid, setCompactGrid] = useState(() => typeof window !== "undefined" && window.innerWidth >= 1600);

  useEffect(() => {
    const updateGridDensity = () => setCompactGrid(window.innerWidth >= 1600);
    updateGridDensity();
    window.addEventListener("resize", updateGridDensity, { passive: true });
    return () => window.removeEventListener("resize", updateGridDensity);
  }, []);

  const [page, setPage] = useState(1);
  const [sortColumns, setSortColumns] = useState<SortColumn[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
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

  const openColumnMenu = useCallback((event: { currentTarget: HTMLButtonElement }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 240;
    setColumnMenuPosition((current) =>
      current
        ? null
        : {
            top: Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - 280)),
            left: Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12)),
          },
    );
  }, []);

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
  }, [page, search, statusFilter, interestFilter]);

  useEffect(() => {
    let cancelled = false;

    async function fetchLeads() {
      if (page === 1) {
        setLoading(true);
      } else {
        setLoadingMore(true);
      }
      setError("");

      try {
        const result = await leadsApi.list({
          page,
          page_size: PAGE_SIZE,
          search: search || undefined,
          status: statusFilter || undefined,
          interest: interestFilter || undefined,
        });

        if (cancelled) return;

        setLeads((current) => {
          if (page === 1) return result.items;
          const existingIds = new Set(current.map((lead) => lead.id));
          return [...current, ...result.items.filter((lead) => !existingIds.has(lead.id))];
        });
        setTotal(result.total);
        setTotalPages(result.total_pages);
        setError("");
      } catch (loadError) {
        if (cancelled) return;
        setError(getErrorMessage(loadError));
      } finally {
        if (!cancelled) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    }

    void fetchLeads();

    return () => {
      cancelled = true;
    };
  }, [page, search, statusFilter, interestFilter]);

  const handleGridScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      const element = event.currentTarget;
      const nearBottom =
        element.scrollTop + element.clientHeight >= element.scrollHeight - 180;

      if (nearBottom && !loading && !loadingMore && page < totalPages) {
        setPage((current) => (current < totalPages ? current + 1 : current));
      }
    },
    [loading, loadingMore, page, totalPages],
  );

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
      modalRef.current?.querySelector<HTMLInputElement>("input")?.focus();
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
    // Start new leads with the current local date and time selected.
    setNextActionDate(toLocalDateTimeInput(new Date().toISOString()));
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

    if (!editingLead && !form.contact_id) {
      setFormError("Choose a contact before creating the lead.");
      return;
    }

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
      setSuccess("Lead created successfully.");
      setLoading(true);

      const result = await leadsApi.list({
        page: 1,
        page_size: PAGE_SIZE,
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


  const contactById = new Map(
    [...contacts, ...formContacts].map((contact) => [contact.id, contact]),
  );

  const sortedLeads = useMemo(() => {
    if (sortColumns.length === 0) return leads;

    const sorted = [...leads];
    sorted.sort((left, right) => {
      for (const sort of sortColumns) {
        const leftContact = contactById.get(left.contact_id);
        const rightContact = contactById.get(right.contact_id);
        let leftValue: string | number = "";
        let rightValue: string | number = "";

        switch (sort.columnKey) {
          case "lead":
            leftValue = getContactName(leftContact).toLocaleLowerCase();
            rightValue = getContactName(rightContact).toLocaleLowerCase();
            break;
          case "status":
            leftValue = left.status;
            rightValue = right.status;
            break;
          case "interest":
            leftValue = left.interest ?? "";
            rightValue = right.interest ?? "";
            break;
          case "nextAction":
            leftValue = left.next_action ?? "";
            rightValue = right.next_action ?? "";
            break;
          case "createdAt":
            leftValue = left.created_at ?? "";
            rightValue = right.created_at ?? "";
            break;
          default:
            break;
        }

        const comparison = String(leftValue).localeCompare(String(rightValue), undefined, {
          numeric: true,
          sensitivity: "base",
        });
        if (comparison !== 0) {
          return sort.direction === "DESC" ? -comparison : comparison;
        }
      }
      return 0;
    });

    return sorted;
  }, [leads, sortColumns, contactById]);

  const columns = useMemo<readonly Column<Lead>[]>(() => [
    {
      key: "lead",
      name: "Lead / Contact",
      minWidth: 240,
      width: 300,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => {
        const contact = contactById.get(row.contact_id);
        const contactName = getContactName(contact);
        const initials = contactName
          .split(/\s+/)
          .filter(Boolean)
          .slice(0, 2)
          .map((part) => part.charAt(0).toUpperCase())
          .join("") || "L";

        return (
          <div className="leads-person-cell">
            <span className="leads-avatar" aria-hidden="true">{initials}</span>
            <span className="leads-person-copy">
              <strong>{contactName}</strong>
              <span>{contact?.email || contact?.phone || "No contact details added"}</span>
            </span>
          </div>
        );
      },
    },
    {
      key: "status",
      name: "Status",
      minWidth: 160,
      width: 190,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => {
        const contactName = getContactName(contactById.get(row.contact_id));
        const busy = updatingLeadId === row.id;

        return (
          <div className="leads-status-cell">
            <InlineChoiceMenu
              value={row.status}
              ariaLabel={`Change status for ${contactName}`}
              disabled={busy || !row.is_active}
              options={getAvailableStatuses(row.status).map((status) => ({
                value: status,
                label: formatLabel(status),
                tone: `leads-tone-status-${status.toLowerCase()}`,
              }))}
              onChange={(value) => void handleStatusChange(row, value as LeadStatus)}
            />
          </div>
        );
      },
    },
    {
      key: "interest",
      name: "Interest",
      minWidth: 125,
      width: 150,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => {
        const contactName = getContactName(contactById.get(row.contact_id));
        const busy = updatingLeadId === row.id;

        return (
          <InlineChoiceMenu
            value={row.interest ?? ""}
            ariaLabel={`Change interest for ${contactName}`}
            disabled={busy || !row.is_active}
            options={[
              { value: "", label: "Not set", tone: "leads-tone-interest-unset" },
              ...INTERESTS.map((interest) => ({
                value: interest,
                label: formatLabel(interest),
                tone: `leads-tone-interest-${interest.toLowerCase()}`,
              })),
            ]}
            onChange={(value) => void handleInterestChange(row, value)}
          />
        );
      },
    },
    {
      key: "nextAction",
      name: "Next follow-up",
      minWidth: 190,
      width: 260,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => (
        <div className="leads-next-step">
          <strong>{row.next_action || "No next action"}</strong>
          <span className={row.next_action_at ? "" : "is-empty"}>
            {row.next_action_at ? `Due ${formatDateTime(row.next_action_at)}` : "Add a follow-up date"}
          </span>
        </div>
      ),
    },
    {
      key: "createdAt",
      name: "Created",
      minWidth: 110,
      width: 140,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => (
        <span className="leads-created-date">{formatDate(row.created_at)}</span>
      ),
    },
    {
      key: "actions",
      name: "Actions",
      minWidth: 126,
      width: 126,
      resizable: false,
      sortable: false,
      renderCell: ({ row }) => {
        const contactName = getContactName(contactById.get(row.contact_id));
        const busy = updatingLeadId === row.id;

        return (
          <div
            className="leads-row-actions"
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
            role="group"
            aria-label={`Actions for ${contactName}`}
          >
            <button className="leads-icon-action" type="button" disabled={busy || saving} onClick={() => openEditForm(row)} aria-label={`Edit ${contactName}`} title="Edit lead">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m15 5 4 4M4 20l4.2-.8L19 8.4a2.1 2.1 0 0 0-3-3L5.2 16.2 4 20Z"/></svg>
            </button>
            <button className="leads-icon-action" type="button" onClick={() => setTimelineLead({ id: row.id, contactName })} aria-label={`View timeline for ${contactName}`} title="Timeline">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
            </button>
            <button className="leads-icon-action" type="button" disabled={busy || !row.is_active} onClick={() => openFollowUps(row)} aria-label={`Manage follow-ups for ${contactName}`} title="Follow-ups">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3h8M9 3v3m6-3v3M5 7h14v13H5z"/><path d="m8 13 2.5 2.5L16 10"/></svg>
            </button>
          </div>
        );
      },
    },
    {
      key: "configure",
      name: "",
      // Consume spare horizontal space like Jira; stay compact when the grid overflows.
      width: "1fr",
      minWidth: 44,
      resizable: false,
      sortable: false,
      renderHeaderCell: () => (
        <button
          className="leads-configure-columns-button"
          type="button"
          onClick={openColumnMenu}
          aria-label="Configure table columns"
          title="Configure columns"
          aria-expanded={columnMenuPosition !== null}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 4v16M15 4v16"/></svg>
        </button>
      ),
      renderCell: ({ row }) => {
        const contactName = getContactName(contactById.get(row.contact_id));
        const busy = updatingLeadId === row.id;

        return (
          <div className="leads-configure-row-action">
            <button
              className="leads-icon-action leads-icon-action-muted"
              type="button"
              disabled={busy}
              onClick={() => void handleActiveToggle(row)}
              aria-label={row.is_active ? `Deactivate ${contactName}` : `Reactivate ${contactName}`}
              title={row.is_active ? "Deactivate lead" : "Reactivate lead"}
            >
              {busy ? <span className="leads-action-spinner" aria-hidden="true" /> : row.is_active ? (
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6m0-6-6 6"/></svg>
              ) : (
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.6 9A7 7 0 0 1 18 6.5L20 12M4 12l2 5.5A7 7 0 0 0 18.4 15"/></svg>
              )}
            </button>
          </div>
        );
      },
    },
  ], [contactById, updatingLeadId, saving, handleStatusChange, handleInterestChange, openEditForm, openFollowUps, handleActiveToggle, openColumnMenu, columnMenuPosition]);

  const visibleColumns = useMemo(
    () => columns.filter((column) => column.key === "configure" || column.key === "actions" || visibleColumnKeys.includes(column.key)),
    [columns, visibleColumnKeys],
  );

  return (
    <main className="leads-page leads-workspace">
      <header className="leads-page-header">
        <div className="leads-heading-copy">
          <h1>Leads</h1>
          <p>Manage enquiries, understand intent, and keep every next step visible.</p>
        </div>
      </header>

      {success && (
        <div className="leads-alert leads-alert-success" role="status">
          <span>{success}</span>
          <button type="button" className="leads-dismiss" onClick={() => setSuccess("")} aria-label="Dismiss success message">×</button>
        </div>
      )}

      <div className="leads-filterbar">
          <label className="leads-search-field">
            <span className="leads-visually-hidden">Search leads</span>
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
            <input type="search" value={searchInput} maxLength={320} placeholder="Search name, email, phone or next action" onChange={(event) => { setSearchInput(event.target.value); setPage(1); }} />
            {searchInput && <button type="button" aria-label="Clear search" onClick={() => { setSearchInput(""); setSearch(""); setPage(1); }}>×</button>}
          </label>
          <label className="leads-filter-field"><span>Status</span><select aria-label="Filter by status" value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value as "" | LeadStatus); setPage(1); }}><option value="">All statuses</option>{STATUSES.map((status) => <option value={status} key={status}>{formatLabel(status)}</option>)}</select></label>
          <label className="leads-filter-field"><span>Interest</span><select aria-label="Filter by interest" value={interestFilter} onChange={(event) => { setInterestFilter(event.target.value as "" | LeadInterest); setPage(1); }}><option value="">All levels</option>{INTERESTS.map((interest) => <option value={interest} key={interest}>{formatLabel(interest)}</option>)}</select></label>
          {(searchInput || statusFilter || interestFilter) && <button className="leads-clear-filters" type="button" onClick={() => { setSearchInput(""); setSearch(""); setStatusFilter(""); setInterestFilter(""); setPage(1); }}>Clear filters</button>}
          <button className="leads-primary-button leads-add-button leads-toolbar-create" type="button" onClick={openCreateForm}>
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14" /></svg>
            Create lead
          </button>
        </div>

        {error && <div className="leads-alert leads-alert-error" role="alert"><div><strong>We couldn’t load the leads</strong><p>{error}</p></div><button className="leads-secondary-button" type="button" onClick={() => void loadLeads()}>Try again</button></div>}

        {loading ? (
          <div className="leads-state" role="status" aria-live="polite"><span className="leads-spinner" aria-hidden="true"/><p>Loading leads…</p></div>
        ) : !error && leads.length === 0 ? (
          <div className="leads-empty"><div className="leads-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="10" cy="7" r="4"/><path d="M19 8v6M16 11h6"/></svg></div><h3>{search || statusFilter || interestFilter ? "No leads match these filters" : "Start with your first lead"}</h3><p>{search || statusFilter || interestFilter ? "Try another search or clear one or more filters." : "Add a lead from an existing contact to begin tracking their journey."}</p>{search || statusFilter || interestFilter ? <button className="leads-secondary-button" type="button" onClick={() => { setSearchInput(""); setSearch(""); setStatusFilter(""); setInterestFilter(""); setPage(1); }}>Reset view</button> : <button className="leads-primary-button" type="button" onClick={openCreateForm}>Add your first lead</button>}</div>
        ) : !error ? (
          <>
            <div className="leads-grid-shell">
              <DataGrid
                className="leads-react-data-grid"
                aria-label="Leads directory"
                columns={visibleColumns}
                rows={sortedLeads}
                rowKeyGetter={(row) => row.id}
                rowHeight={compactGrid ? 42 : 58}
                headerRowHeight={52}
                defaultColumnOptions={{ resizable: true, sortable: true }}
                sortColumns={sortColumns}
                onSortColumnsChange={setSortColumns}
                onScroll={handleGridScroll}
                style={{
                  height: Math.min(
                    52 + sortedLeads.length * (compactGrid ? 42 : 58),
                    Math.max(220, (typeof window !== "undefined" ? window.innerHeight : 900) * 0.68),
                  ),
                  minHeight: 52 + Math.min(sortedLeads.length, 1) * (compactGrid ? 42 : 58),
                }}
                renderers={{
                  noRowsFallback: (
                    <div className="leads-grid-no-rows">No leads to display.</div>
                  ),
                }}
              />
              {loadingMore && (
                <div className="leads-load-more" role="status" aria-live="polite">
                  <span className="leads-spinner" aria-hidden="true" />
                  <span>Loading more leads…</span>
                </div>
              )}
              <div className="leads-grid-end" role="status" aria-live="polite">
                {loadingMore
                  ? `Loading more leads… ${leads.length.toLocaleString("en-IN")} loaded`
                  : leads.length >= total
                    ? `You’re all caught up · ${total.toLocaleString("en-IN")} leads`
                    : `Showing ${leads.length.toLocaleString("en-IN")} of ${total.toLocaleString("en-IN")} leads`}
              </div>
            </div>
          </>
        ) : null}

{columnMenuPosition &&
  createPortal(
    <div
      className="leads-column-menu-layer"
      onPointerDown={() => setColumnMenuPosition(null)}
      role="presentation"
    >
      <div
        className="leads-column-menu"
        style={{ top: columnMenuPosition.top, left: columnMenuPosition.left }}
        role="dialog"
        aria-label="Configure table columns"
        onPointerDown={(event) => event.stopPropagation()}
      >
        <div className="leads-column-menu-heading">
          <div><strong>Configure columns</strong><span>Choose which fields are visible.</span></div>
          <button type="button" aria-label="Close column configuration" onClick={() => setColumnMenuPosition(null)}>×</button>
        </div>
        {[
          { key: "lead", label: "Lead / Contact" },
          { key: "status", label: "Status" },
          { key: "interest", label: "Interest" },
          { key: "nextAction", label: "Next follow-up" },
          { key: "createdAt", label: "Created" },
        ].map((column) => (
          <label className="leads-column-option" key={column.key}>
            <input
              type="checkbox"
              checked={visibleColumnKeys.includes(column.key)}
              onChange={(event) => {
                setVisibleColumnKeys((current) =>
                  event.target.checked
                    ? [...current, column.key]
                    : current.filter((key) => key !== column.key),
                );
              }}
            />
            <span>{column.label}</span>
          </label>
        ))}
        <div className="leads-column-menu-footer">
          <button type="button" onClick={() => setVisibleColumnKeys(["lead", "status", "interest", "nextAction", "createdAt"])}>Reset columns</button>
          <button type="button" onClick={() => setColumnMenuPosition(null)}>Done</button>
        </div>
      </div>
    </div>,
    document.body,
  )}

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
              className="leads-modal leads-lead-form-modal"
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
                      <label className="leads-form-field leads-form-contact-search">
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

                      <label className="leads-form-field leads-form-contact">
                        <span>
                          Contact <span aria-hidden="true">*</span>
                        </span>

                        <div className="leads-form-choice-wrap">
                          <InlineChoiceMenu
                            value={form.contact_id}
                            ariaLabel="Choose contact"
                            disabled={saving || contactLoading || formContacts.length === 0}
                            options={[
                              {
                                value: "",
                                label: contactLoading ? "Loading contacts…" : "Select a contact",
                                tone: "leads-tone-interest-unset",
                              },
                              ...formContacts.map((contact) => ({
                                value: contact.id,
                                label: `${getContactName(contact)}${contact.phone ? ` · ${contact.phone}` : ""}`,
                                tone: "leads-tone-contact",
                              })),
                            ]}
                            onChange={(value) =>
                              setForm((current) => ({ ...current, contact_id: value }))
                            }
                          />
                        </div>

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

                      <label className="leads-form-field leads-form-interest">
                        <span>Interest level</span>
                        <InlineChoiceMenu
                          value={form.interest}
                          ariaLabel="Interest level"
                          disabled={saving}
                          options={[
                            { value: "", label: "Not set", tone: "leads-tone-interest-unset" },
                            ...INTERESTS.map((interest) => ({
                              value: interest,
                              label: formatLabel(interest),
                              tone: `leads-tone-interest-${interest.toLowerCase()}`,
                            })),
                          ]}
                          onChange={(value) =>
                            setForm((current) => ({
                              ...current,
                              interest: value as "" | LeadInterest,
                            }))
                          }
                        />
                      </label>
                    </>
                  )}

                  <label className="leads-form-field leads-form-next-action">
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

                  <label className="leads-form-field leads-form-next-action-date">
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
                    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m6 6 12 12M18 6 6 18" /></svg>
                    Cancel
                  </button>

                  <button
                    className={`leads-primary-button ${editingLead ? "leads-save-button" : "leads-create-submit-button"}`}
                    type="submit"
                    disabled={
                      saving ||
                      (!editingLead &&
                        (contactLoading || formContacts.length === 0))
                    }
                  >
                    {saving ? (
                      <span className="leads-button-spinner" aria-hidden="true" />
                    ) : editingLead ? (
                      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5 9.2 17 19 7" /></svg>
                    ) : (
                      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14" /></svg>
                    )}
                    {saving ? "Saving…" : editingLead ? "Save changes" : "Create lead"}
                  </button>
                </footer>
              </form>
            </section>
          </div>,
          document.body,
        )}
    </main>
  );
}

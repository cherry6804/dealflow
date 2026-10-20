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
import { contactsApi, type Contact } from "../services/contactApi";
import {
  customerProfilesApi,
  type CustomerProfile,
} from "../services/customerProfileApi";
import { dealsApi, type Deal } from "../services/dealApi";
import {
  referralsApi,
  type Referral,
  type ReferralCreateInput,
  type ReferralStatus,
} from "../services/referralApi";
import "./ReferralsPage.css";

const PAGE_SIZE = 10;

const STATUS_OPTIONS: { value: ReferralStatus; label: string; }[] = [
  { value: "NEW", label: "New" },
  { value: "CONTACTED", label: "Contacted" },
  { value: "CONVERTED", label: "Converted" },
  { value: "NOT_CONVERTED", label: "Not converted" },
];

interface ReferralFormValues {
  referral_name: string;
  referral_phone: string;
  referral_email: string;
  customer_profile_id: string;
  referrer_contact_id: string;
  deal_id: string;
  status: ReferralStatus;
  notes: string;
}

const EMPTY_FORM: ReferralFormValues = {
  referral_name: "",
  referral_phone: "",
  referral_email: "",
  customer_profile_id: "",
  referrer_contact_id: "",
  deal_id: "",
  status: "NEW",
  notes: "",
};

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
}

function getContactName(
  contact:
    | Pick<Contact, "first_name" | "last_name">
    | undefined,
): string {
  if (!contact) {
    return "Contact unavailable";
  }

  return [contact.first_name, contact.last_name]
    .filter(Boolean)
    .join(" ");
}

function getCustomerName(customer: CustomerProfile): string {
  return getContactName(customer.contact);
}

function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatStatus(status: ReferralStatus): string {
  return (
    STATUS_OPTIONS.find((option) => option.value === status)?.label ??
    status.replaceAll("_", " ")
  );
}

function getStatusClass(status: ReferralStatus): string {
  switch (status) {
    case "CONVERTED":
      return "referrals-status referrals-status-converted";
    case "CONTACTED":
      return "referrals-status referrals-status-contacted";
    case "NOT_CONVERTED":
      return "referrals-status referrals-status-not-converted";
    default:
      return "referrals-status referrals-status-new";
  }
}

function getAssociationLabels(
  referral: Referral,
  customers: CustomerProfile[],
  contacts: Contact[],
  deals: Deal[],
): string[] {
  const labels: string[] = [];

  if (referral.customer_profile_id) {
    const customer = customers.find(
      (item) => item.id === referral.customer_profile_id,
    );

    labels.push(
      customer
        ? `Customer: ${getCustomerName(customer)}`
        : "Customer linked",
    );
  }

  if (referral.referrer_contact_id) {
    const contact = contacts.find(
      (item) => item.id === referral.referrer_contact_id,
    );

    labels.push(
      contact
        ? `Referrer: ${getContactName(contact)}`
        : "Referrer linked",
    );
  }

  if (referral.deal_id) {
    const deal = deals.find((item) => item.id === referral.deal_id);

    labels.push(
      deal
        ? `Deal: ${deal.id.slice(0, 8)}`
        : "Deal linked",
    );
  }

  return labels;
}

export default function ReferralsPage() {
  const [referrals, setReferrals] = useState<Referral[]>([]);
  const [customers, setCustomers] = useState<CustomerProfile[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  const [loading, setLoading] = useState(true);
  const [lookupsLoading, setLookupsLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingReferral, setEditingReferral] = useState<Referral | null>(
    null,
  );
  const [form, setForm] = useState<ReferralFormValues>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [sortColumns, setSortColumns] = useState<SortColumn[]>([]);
  const [visibleColumnKeys, setVisibleColumnKeys] = useState<string[]>([
    "referral", "contact", "associations", "status", "createdAt",
  ]);
  const [columnMenuPosition, setColumnMenuPosition] = useState<{ top: number; left: number; } | null>(null);
  const [actionMenu, setActionMenu] = useState<{ referral: Referral; top: number; left: number; } | null>(null);
  const [compactGrid, setCompactGrid] = useState(() => typeof window !== "undefined" && window.innerWidth >= 1600);

  const modalRef = useRef<HTMLElement>(null);
  const requestSequence = useRef(0);

  const loadReferrals = useCallback(async () => {
    const sequence = ++requestSequence.current;

    setLoading(true);
    setError("");

    try {
      const result = await referralsApi.list({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        status: statusFilter
          ? (statusFilter as ReferralStatus)
          : undefined,
      });

      if (sequence !== requestSequence.current) {
        return;
      }

      setReferrals(result.items);
      setTotal(result.total);
    } catch (loadError) {
      if (sequence !== requestSequence.current) {
        return;
      }

      setError(getErrorMessage(loadError));
    } finally {
      if (sequence === requestSequence.current) {
        setLoading(false);
      }
    }
  }, [page, search, statusFilter]);

  useEffect(() => {
    void loadReferrals();

    return () => {
      requestSequence.current += 1;
    };
  }, [loadReferrals]);

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
    if (!isFormOpen) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusTimer = window.setTimeout(() => {
      modalRef.current
        ?.querySelector<HTMLElement>(
          "input:not([type=hidden]), select, textarea, button",
        )
        ?.focus();
    }, 50);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) {
        setIsFormOpen(false);
        setEditingReferral(null);
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
    function updateDensity() {
      setCompactGrid(window.innerWidth >= 1600);
    }
    function closeFloatingMenus() {
      setActionMenu(null);
      setColumnMenuPosition(null);
    }
    function handleGlobalKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setActionMenu(null);
        setColumnMenuPosition(null);
      }
    }
    window.addEventListener("resize", updateDensity);
    window.addEventListener("scroll", closeFloatingMenus, true);
    document.addEventListener("keydown", handleGlobalKeyDown);
    return () => {
      window.removeEventListener("resize", updateDensity);
      window.removeEventListener("scroll", closeFloatingMenus, true);
      document.removeEventListener("keydown", handleGlobalKeyDown);
    };
  }, []);

  const loadLookups = useCallback(async () => {
    setLookupsLoading(true);

    try {
      const [customerResult, contactResult, dealResult] = await Promise.all([
        customerProfilesApi.list({
          page: 1,
          page_size: 100,
          is_active: true,
        }),
        contactsApi.list({
          page: 1,
          page_size: 100,
          is_active: true,
        }),
        dealsApi.list({
          page: 1,
          page_size: 100,
        }),
      ]);

      setCustomers(customerResult.items);
      setContacts(contactResult.items.filter((item) => item.is_active));
      setDeals(dealResult.items);
    } catch (lookupError) {
      setFormError(
        `Could not load association options. ${getErrorMessage(lookupError)}`,
      );
    } finally {
      setLookupsLoading(false);
    }
  }, []);

  function openCreateForm() {
    setEditingReferral(null);
    setForm(EMPTY_FORM);
    setFormError("");
    setSuccess("");
    setIsFormOpen(true);
    void loadLookups();
  }

  function openEditForm(referral: Referral) {
    setEditingReferral(referral);
    setForm({
      referral_name: referral.referral_name ?? "",
      referral_phone: referral.referral_phone ?? "",
      referral_email: referral.referral_email ?? "",
      customer_profile_id: referral.customer_profile_id ?? "",
      referrer_contact_id: referral.referrer_contact_id ?? "",
      deal_id: referral.deal_id ?? "",
      status: referral.status,
      notes: referral.notes ?? "",
    });
    setFormError("");
    setSuccess("");
    setIsFormOpen(true);
    void loadLookups();
  }

  function closeForm() {
    if (saving) {
      return;
    }

    setIsFormOpen(false);
    setEditingReferral(null);
    setForm(EMPTY_FORM);
    setFormError("");
  }

  function updateForm<K extends keyof ReferralFormValues>(
    field: K,
    value: ReferralFormValues[K],
  ) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function validateForm(): string {
    if (!form.referral_name.trim()) {
      return "Enter the referral name.";
    }

    if (
      !form.customer_profile_id &&
      !form.referrer_contact_id &&
      !form.deal_id
    ) {
      return "Link the referral to a customer, referring contact, or deal.";
    }

    if (form.referral_email.trim()) {
      const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

      if (!emailPattern.test(form.referral_email.trim())) {
        return "Enter a valid email address.";
      }
    }

    return "";
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setFormError("");
    setError("");
    setSuccess("");

    const validationError = validateForm();

    if (validationError) {
      setFormError(validationError);
      return;
    }

    const payload: ReferralCreateInput = {
      referral_name: form.referral_name.trim(),
      referral_phone: form.referral_phone.trim() || null,
      referral_email: form.referral_email.trim() || null,
      customer_profile_id: form.customer_profile_id || null,
      referrer_contact_id: form.referrer_contact_id || null,
      deal_id: form.deal_id || null,
      status: form.status,
      notes: form.notes.trim() || null,
    };

    setSaving(true);

    try {
      if (editingReferral) {
        await referralsApi.update(editingReferral.id, payload);
        setSuccess("Referral updated successfully.");
      } else {
        await referralsApi.create(payload);
        setSuccess("Referral created successfully.");
      }

      setIsFormOpen(false);
      setEditingReferral(null);
      setForm(EMPTY_FORM);

      if (!editingReferral) {
        setPage(1);
        setSearch("");
        setSearchInput("");
        setStatusFilter("");
      } else {
        await loadReferrals();
      }

      if (!editingReferral) {
        const result = await referralsApi.list({
          page: 1,
          page_size: PAGE_SIZE,
        });

        setReferrals(result.items);
        setTotal(result.total);
      }
    } catch (submitError) {
      setFormError(getErrorMessage(submitError));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeactivate(referral: Referral) {
    const confirmed = window.confirm(
      `Deactivate the referral "${referral.referral_name}"?`,
    );

    if (!confirmed) {
      return;
    }

    setError("");
    setSuccess("");

    try {
      await referralsApi.deactivate(referral.id);
      setSuccess("Referral deactivated successfully.");

      const result = await referralsApi.list({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        status: statusFilter
          ? (statusFilter as ReferralStatus)
          : undefined,
      });

      if (result.items.length === 0 && page > 1) {
        setPage((current) => current - 1);
      } else {
        setReferrals(result.items);
        setTotal(result.total);
      }
    } catch (deactivateError) {
      setError(getErrorMessage(deactivateError));
    }
  }

  function handleStatusChange(value: string) {
    setPage(1);
    setStatusFilter(value);
  }

  const sortedReferrals = useMemo(() => {
    if (sortColumns.length === 0) return referrals;
    return [...referrals].sort((left, right) => {
      for (const sort of sortColumns) {
        let a: string | number = "";
        let b: string | number = "";
        switch (sort.columnKey) {
          case "referral":
            a = left.referral_name;
            b = right.referral_name;
            break;
          case "contact":
            a = `${left.referral_email ?? ""} ${left.referral_phone ?? ""}`;
            b = `${right.referral_email ?? ""} ${right.referral_phone ?? ""}`;
            break;
          case "associations":
            a = getAssociationLabels(left, customers, contacts, deals).join(" ");
            b = getAssociationLabels(right, customers, contacts, deals).join(" ");
            break;
          case "status":
            a = formatStatus(left.status);
            b = formatStatus(right.status);
            break;
          case "createdAt":
            a = new Date(left.created_at).getTime() || 0;
            b = new Date(right.created_at).getTime() || 0;
            break;
          default:
            break;
        }
        const comparison = typeof a === "number" && typeof b === "number"
          ? a - b
          : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
        if (comparison !== 0) return sort.direction === "DESC" ? -comparison : comparison;
      }
      return 0;
    });
  }, [referrals, sortColumns, customers, contacts, deals]);

  const openColumnMenu = useCallback((event: { currentTarget: HTMLButtonElement; }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 240;
    setColumnMenuPosition((current) => current ? null : {
      top: Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - 320)),
      left: Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12)),
    });
  }, []);

  const openActionMenu = useCallback((event: { currentTarget: HTMLButtonElement; }, referral: Referral) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 220;
    const menuHeight = 112;
    const top = rect.bottom + menuHeight + 12 > window.innerHeight
      ? Math.max(12, rect.top - menuHeight - 6)
      : rect.bottom + 6;
    const left = Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12));
    setActionMenu((current) => current?.referral.id === referral.id ? null : { referral, top, left });
  }, []);

  const columns = useMemo<readonly Column<Referral>[]>(() => [
    {
      key: "referral", name: "Referral", minWidth: 190, width: 230, resizable: true, sortable: true,
      renderCell: ({ row }) => {
        const name = row.referral_name || "Unnamed referral";
        const initials = name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "R";
        return <div className="referrals-person-cell"><span className="referrals-avatar" aria-hidden="true">{initials}</span><span className="referrals-person-copy"><strong title={name}>{name}</strong><span title={`#${row.id.slice(0, 8)}`}>#{row.id.slice(0, 8)}</span></span></div>;
      },
    },
    {
      key: "contact", name: "Contact details", minWidth: 180, width: 230, resizable: true, sortable: true,
      renderCell: ({ row }) => <div className="referrals-grid-contact"><span title={row.referral_email || "No email"}>{row.referral_email || "No email"}</span><span title={row.referral_phone || "No phone"}>{row.referral_phone || "No phone"}</span></div>,
    },
    {
      key: "associations", name: "Associations", minWidth: 200, width: 260, resizable: true, sortable: true,
      renderCell: ({ row }) => {
        const labels = getAssociationLabels(row, customers, contacts, deals);
        return <div className="referrals-grid-associations">{labels.length ? labels.map((label) => <span key={label} title={label}>{label}</span>) : <span>—</span>}</div>;
      },
    },
    {
      key: "status", name: "Status", minWidth: 125, width: 145, resizable: true, sortable: true,
      renderCell: ({ row }) => <span className={getStatusClass(row.status)}>{formatStatus(row.status)}</span>,
    },
    {
      key: "createdAt", name: "Created", minWidth: 120, width: 140, resizable: true, sortable: true,
      renderCell: ({ row }) => <span className="referrals-created-date">{formatDate(row.created_at)}</span>,
    },
    {
      key: "actions", name: "Actions", minWidth: 82, width: 96, resizable: false, sortable: false,
      renderCell: ({ row }) => <div className="referrals-grid-actions" onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}><button className="referrals-icon-action" type="button" aria-label={`Open actions for ${row.referral_name}`} aria-haspopup="menu" aria-expanded={actionMenu?.referral.id === row.id} title="Referral actions" onClick={(event) => openActionMenu(event, row)}><svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg></button></div>,
    },
    {
      key: "configure", name: "", width: "1fr", minWidth: 44, resizable: false, sortable: false,
      renderHeaderCell: () => <button className="referrals-configure-columns-button" type="button" onClick={openColumnMenu} aria-label="Configure table columns" title="Configure columns" aria-expanded={columnMenuPosition !== null}><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M9 4v16M15 4v16" /></svg></button>,
    },
  ], [customers, contacts, deals, actionMenu, openActionMenu, openColumnMenu, columnMenuPosition]);

  const visibleColumns = useMemo(() => columns.filter((column) =>
    column.key === "actions" || column.key === "configure" || visibleColumnKeys.includes(column.key),
  ), [columns, visibleColumnKeys]);

  return (
    <section className="referrals-page">
      <header className="referrals-header">
        <div>
          <h1>Referrals</h1>
          <p className="referrals-subtitle">
            Track introductions, manage referral sources, and turn opportunities into successful deals.
          </p>
        </div>
      </header>

      {error && (
        <div className="referrals-alert referrals-alert-error" role="alert">
          <span>{error}</span>
          <button type="button" className="referrals-dismiss" onClick={() => setError("")} aria-label="Dismiss error">×</button>
        </div>
      )}
      {success && (
        <div className="referrals-alert referrals-alert-success" role="status">
          <span>{success}</span>
          <button type="button" className="referrals-dismiss" onClick={() => setSuccess("")} aria-label="Dismiss success">×</button>
        </div>
      )}

      <div className="referrals-toolbar">
        <label className="referrals-search">
          <svg className="referrals-search-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.2 4.2" /></svg>
          <input aria-label="Search referrals" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search referral name, email or phone" />
        </label>
        <label className="referrals-filter">
          <span className="referrals-visually-hidden">Filter by status</span>
          <select aria-label="Filter referrals by status" value={statusFilter} onChange={(event) => handleStatusChange(event.target.value)}>
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <button className="referrals-primary-button" type="button" onClick={openCreateForm}>
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
          Add referral
        </button>
      </div>

      {loading ? (
        <div className="referrals-state" role="status" aria-live="polite"><span className="referrals-spinner" /><p>Loading referrals…</p></div>
      ) : referrals.length === 0 ? (
        <div className="referrals-empty">
          <div className="referrals-empty-icon" aria-hidden="true">↗</div>
          <h3>{search || statusFilter ? "No referrals match these filters" : "Add your first referral"}</h3>
          <p>{search || statusFilter ? "Try another search term or status filter." : "Capture a referral and link it to a customer, contact, or deal."}</p>
          {search || statusFilter ? <button className="referrals-secondary-button" type="button" onClick={() => { setSearchInput(""); setSearch(""); setStatusFilter(""); setPage(1); }}>Clear filters</button> : <button className="referrals-primary-button" type="button" onClick={openCreateForm}><span aria-hidden="true">+</span> Add referral</button>}
        </div>
      ) : (
        <div className="referrals-grid-shell">
          <DataGrid
            className="referrals-react-data-grid"
            aria-label="Referrals directory"
            columns={visibleColumns}
            rows={sortedReferrals}
            rowKeyGetter={(row) => row.id}
            rowHeight={compactGrid ? 48 : 62}
            headerRowHeight={52}
            defaultColumnOptions={{ resizable: true, sortable: true }}
            sortColumns={sortColumns}
            onSortColumnsChange={setSortColumns}
            style={{
              height: Math.min(52 + sortedReferrals.length * (compactGrid ? 48 : 62), Math.max(260, (typeof window !== "undefined" ? window.innerHeight : 900) * 0.68)),
              minHeight: 52 + Math.min(sortedReferrals.length, 1) * (compactGrid ? 48 : 62),
            }}
            renderers={{ noRowsFallback: <div className="referrals-grid-no-rows">No referrals to display.</div> }}
          />
          <footer className="referrals-grid-footer">
            <p><strong>{total}</strong> referrals in your workspace</p>
            <div className="referrals-pagination-controls">
              <span className="customers-caught-up"><span aria-hidden="true" />You’re all caught up</span>
            </div>
          </footer>
        </div>
      )}

      {actionMenu && createPortal(
        <div className="referrals-action-menu-layer" role="presentation" onPointerDown={() => setActionMenu(null)}>
          <section className="referrals-action-menu" style={{ top: actionMenu.top, left: actionMenu.left }} role="menu" aria-label="Referral actions" onPointerDown={(event) => event.stopPropagation()}>
            <header className="referrals-action-menu-header"><div><strong>Referral actions</strong><span>{actionMenu.referral.referral_name}</span></div><button type="button" aria-label="Close referral actions" onClick={() => setActionMenu(null)}>×</button></header>
            <button type="button" role="menuitem" onClick={() => { const referral = actionMenu.referral; setActionMenu(null); openEditForm(referral); }}><span className="referrals-menu-icon" aria-hidden="true">✎</span><span><strong>Edit referral</strong><small>Update details and linked records</small></span></button>
            <button type="button" role="menuitem" className="referrals-menu-danger" onClick={() => { const referral = actionMenu.referral; setActionMenu(null); void handleDeactivate(referral); }}><span className="referrals-menu-icon" aria-hidden="true">⊘</span><span><strong>Deactivate referral</strong><small>Remove it from active workflows</small></span></button>
          </section>
        </div>, document.body,
      )}

      {columnMenuPosition && createPortal(
        <div className="referrals-column-menu-layer" role="presentation" onPointerDown={() => setColumnMenuPosition(null)}>
          <div className="referrals-column-menu" style={{ top: columnMenuPosition.top, left: columnMenuPosition.left }} role="dialog" aria-label="Configure table columns" onPointerDown={(event) => event.stopPropagation()}>
            <div className="referrals-column-menu-heading"><div><strong>Configure columns</strong><span>Choose which fields are visible.</span></div><button type="button" aria-label="Close column configuration" onClick={() => setColumnMenuPosition(null)}>×</button></div>
            {[
              { key: "referral", label: "Referral" },
              { key: "contact", label: "Contact details" },
              { key: "associations", label: "Associations" },
              { key: "status", label: "Status" },
              { key: "createdAt", label: "Created" },
            ].map((column) => <label className="referrals-column-option" key={column.key}><input type="checkbox" checked={visibleColumnKeys.includes(column.key)} onChange={(event) => setVisibleColumnKeys((current) => event.target.checked ? [...current, column.key] : current.filter((key) => key !== column.key))} /><span>{column.label}</span></label>)}
            <div className="referrals-column-menu-footer"><button type="button" onClick={() => setVisibleColumnKeys(["referral", "contact", "associations", "status", "createdAt"])}>Reset columns</button><button type="button" onClick={() => setColumnMenuPosition(null)}>Done</button></div>
          </div>
        </div>, document.body,
      )}

      {isFormOpen && createPortal(
        <div
          className="referrals-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              closeForm();
            }
          }}
        >
          <section
            ref={modalRef}
            className="referrals-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="referrals-form-title"
          >
            <header className="referrals-modal-header">
              <div>
                <span className="referrals-eyebrow">
                  {editingReferral ? "REFERRAL DETAILS" : "OPPORTUNITY DETAILS"}
                </span>
                <h2 id="referrals-form-title">
                  {editingReferral ? "Edit referral" : "Add referral"}
                </h2>
                <p>
                  {editingReferral
                    ? "Update referral information and linked records."
                    : "Choose a referral and connect the relevant records."}
                </p>
              </div>
              <button
                type="button"
                className="referrals-modal-close"
                aria-label="Close form"
                onClick={closeForm}
                disabled={saving}
              >
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="m6 6 12 12M18 6 6 18" /></svg>
              </button>
            </header>

            <form className="referrals-form" onSubmit={handleSubmit}>
              <div className="referrals-form-body">
                {formError && (
                  <div className="referrals-alert referrals-alert-error" role="alert">
                    {formError}
                  </div>
                )}

                <section className="referrals-form-section">
                  <h3>Referral details</h3>

                  <div className="referrals-form-grid">
                    <label className="referrals-form-field referrals-field-full">
                      <span>Referral name <i>*</i></span>
                      <input
                        required
                        maxLength={200}
                        value={form.referral_name}
                        onChange={(event) =>
                          updateForm("referral_name", event.target.value)
                        }
                        placeholder="Enter the referred person's name"
                      />
                    </label>

                    <label className="referrals-form-field">
                      <span>Phone</span>
                      <input
                        type="tel"
                        maxLength={30}
                        value={form.referral_phone}
                        onChange={(event) =>
                          updateForm("referral_phone", event.target.value)
                        }
                        placeholder="Phone number"
                      />
                    </label>

                    <label className="referrals-form-field">
                      <span>Email</span>
                      <input
                        type="email"
                        maxLength={254}
                        value={form.referral_email}
                        onChange={(event) =>
                          updateForm("referral_email", event.target.value)
                        }
                        placeholder="name@example.com"
                      />
                    </label>

                    <label className="referrals-form-field">
                      <span>Status</span>
                      <select
                        value={form.status}
                        onChange={(event) =>
                          updateForm("status", event.target.value as ReferralStatus)
                        }
                      >
                        {STATUS_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </section>

                <section className="referrals-form-section">
                  <h3>Link existing records</h3>
                  <p className="referrals-section-hint">
                    At least one association is required. Link a customer,
                    referring contact, deal, or multiple records.
                  </p>

                  <div className="referrals-form-grid">
                    <label className="referrals-form-field">
                      <span>Customer</span>
                      <select
                        value={form.customer_profile_id}
                        onChange={(event) =>
                          updateForm("customer_profile_id", event.target.value)
                        }
                      >
                        <option value="">No customer selected</option>
                        {customers.map((customer) => (
                          <option key={customer.id} value={customer.id}>
                            {getCustomerName(customer)}
                            {customer.contact.phone
                              ? ` · ${customer.contact.phone}`
                              : ""}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="referrals-form-field">
                      <span>Referring contact</span>
                      <select
                        value={form.referrer_contact_id}
                        onChange={(event) =>
                          updateForm("referrer_contact_id", event.target.value)
                        }
                      >
                        <option value="">No referrer selected</option>
                        {contacts.map((contact) => (
                          <option key={contact.id} value={contact.id}>
                            {getContactName(contact)}
                            {contact.phone ? ` · ${contact.phone}` : ""}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="referrals-form-field referrals-field-full">
                      <span>Deal</span>
                      <select
                        value={form.deal_id}
                        onChange={(event) =>
                          updateForm("deal_id", event.target.value)
                        }
                      >
                        <option value="">No deal selected</option>
                        {deals.map((deal) => (
                          <option key={deal.id} value={deal.id}>
                            Deal #{deal.id.slice(0, 8)} · {deal.stage}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>

                  {lookupsLoading && (
                    <p className="referrals-section-hint" role="status">
                      Loading customers, contacts, and deals…
                    </p>
                  )}

                  {!lookupsLoading &&
                    customers.length + contacts.length + deals.length === 0 && (
                      <p className="referrals-section-hint">
                        No association options are currently available. You
                        need at least one valid association to create a referral.
                      </p>
                    )}
                </section>

                <section className="referrals-form-section">
                  <h3>Notes</h3>
                  <label className="referrals-form-field">
                    <span>Additional context</span>
                    <textarea
                      rows={4}
                      maxLength={5000}
                      value={form.notes}
                      onChange={(event) =>
                        updateForm("notes", event.target.value)
                      }
                      placeholder="Add referral source details or follow-up notes..."
                    />
                  </label>
                </section>
              </div>

              <footer className="referrals-form-actions">
                <button
                  type="button"
                  className="referrals-secondary-button"
                  onClick={closeForm}
                  disabled={saving}
                >
                  <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="m6 6 12 12M18 6 6 18" /></svg>
                  Cancel
                </button>
                <button
                  type="submit"
                  className="referrals-primary-button"
                  disabled={saving || lookupsLoading}
                >
                  {!saving && <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>}
                  {saving ? "Saving…" : editingReferral ? "Save changes" : "Create referral"}
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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, MouseEvent } from "react";
import { DataGrid, type Column, type SortColumn } from "react-data-grid";
import "react-data-grid/lib/styles.css";
import { createPortal } from "react-dom";
import { ApiError } from "../lib/api";
import { contactsApi, type Contact } from "../services/contactApi";
import {
  customerProfilesApi,
  type CustomerProfile,
} from "../services/customerProfileApi";
import SiteVisitHistory from "../components/SiteVisitHistory";
import "./CustomersPage.css";

const MODAL_EXIT_DURATION = 200;

type StatusFilter = "active" | "inactive";

type ActionMenuState = {
  customer: CustomerProfile;
  top: number;
  left: number;
};

type CustomerListResult = {
  items: CustomerProfile[];
  total: number;
};

function displayName(contact: {
  first_name: string;
  last_name: string | null;
}): string {
  return [contact.first_name, contact.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);

  if (parts.length === 0) {
    return "C";
  }

  return parts
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
}

function formatDate(value: string): string {
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

async function getAllProfiles(isActive: boolean): Promise<CustomerProfile[]> {
  const firstPage = await customerProfilesApi.list({
    page: 1,
    page_size: 100,
    is_active: isActive,
  });

  const profiles = [...firstPage.items];

  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const result = await customerProfilesApi.list({
      page,
      page_size: 100,
      is_active: isActive,
    });

    profiles.push(...result.items);
  }

  return profiles;
}

async function getAllActiveContacts(): Promise<Contact[]> {
  const firstPage = await contactsApi.list({
    page: 1,
    page_size: 100,
    is_active: true,
  });

  const contacts = [...firstPage.items];

  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const result = await contactsApi.list({
      page,
      page_size: 100,
      is_active: true,
    });

    contacts.push(...result.items);
  }

  return contacts;
}

async function getAllCustomers(
  search: string,
  statusFilter: StatusFilter,
): Promise<CustomerListResult> {
  const firstPage = await customerProfilesApi.list({
    page: 1,
    page_size: 100,
    search,
    is_active: statusFilter === "active",
  });

  const customers = [...firstPage.items];

  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const result = await customerProfilesApi.list({
      page,
      page_size: 100,
      search,
      is_active: statusFilter === "active",
    });

    customers.push(...result.items);
  }

  return {
    items: customers,
    total: firstPage.total,
  };
}

export default function CustomersPage() {
  const [customers, setCustomers] = useState<CustomerProfile[]>([]);
  const [total, setTotal] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [registerOpen, setRegisterOpen] = useState(false);
  const [isDialogClosing, setIsDialogClosing] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [registeredContactIds, setRegisteredContactIds] = useState<Set<string>>(
    new Set(),
  );
  const [contactsLoading, setContactsLoading] = useState(false);
  const [selectedContactId, setSelectedContactId] = useState("");
  const [registrationNotes, setRegistrationNotes] = useState("");
  const [historyCustomer, setHistoryCustomer] =
    useState<CustomerProfile | null>(null);
  const [editingCustomer, setEditingCustomer] =
    useState<CustomerProfile | null>(null);
  const [editingNotes, setEditingNotes] = useState("");
  const [actionMenu, setActionMenu] = useState<ActionMenuState | null>(null);
  const [visibleColumnKeys, setVisibleColumnKeys] = useState<string[]>([
    "customer", "contact", "registered", "status",
  ]);
  const [columnMenuPosition, setColumnMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [sortColumns, setSortColumns] = useState<SortColumn[]>([]);
  const [compactGrid, setCompactGrid] = useState(() => typeof window !== "undefined" && window.innerWidth >= 1600);
  const modalRef = useRef<HTMLElement>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadCustomers = useCallback(async () => {
    setLoading(true);

    try {
      const result = await getAllCustomers(search, statusFilter);
      setCustomers(result.items);
      setTotal(result.total);
      setError("");
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter]);

  useEffect(() => {
    let cancelled = false;

    async function fetchCustomers() {
      setLoading(true);

      try {
        const result = await getAllCustomers(search, statusFilter);

        if (!cancelled) {
          setCustomers(result.items);
          setTotal(result.total);
          setError("");
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(errorMessage(loadError));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void fetchCustomers();

    return () => {
      cancelled = true;
    };
  }, [search, statusFilter]);

  // Match Contacts: search as the user types, without a separate Search button.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const nextSearch = searchInput.trim();
      if (nextSearch !== search) setSearch(nextSearch);
    }, 300);

    return () => window.clearTimeout(timer);
  }, [searchInput, search]);

  useEffect(() => {
    if (!actionMenu) {
      return;
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setActionMenu(null);
    }
    const closeMenu = () => setActionMenu(null);

    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeMenu);
    window.addEventListener("scroll", closeMenu, true);

    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeMenu);
      window.removeEventListener("scroll", closeMenu, true);
    };
  }, [actionMenu]);

  useEffect(() => {
    if (!columnMenuPosition) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setColumnMenuPosition(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [columnMenuPosition]);

  useEffect(() => {
    const updateGridDensity = () => setCompactGrid(window.innerWidth >= 1600);
    updateGridDensity();
    window.addEventListener("resize", updateGridDensity, { passive: true });
    return () => window.removeEventListener("resize", updateGridDensity);
  }, []);

  useEffect(() => () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
  }, []);

  const closeRegisterDialog = useCallback(() => {
    if (saving || isDialogClosing || !registerOpen) return;
    setIsDialogClosing(true);
    closeTimerRef.current = window.setTimeout(() => {
      setRegisterOpen(false);
      setIsDialogClosing(false);
      closeTimerRef.current = null;
    }, MODAL_EXIT_DURATION);
  }, [saving, isDialogClosing, registerOpen]);

  const closeEditDialog = useCallback(() => {
    if (saving || isDialogClosing || !editingCustomer) return;
    setIsDialogClosing(true);
    closeTimerRef.current = window.setTimeout(() => {
      setEditingCustomer(null);
      setIsDialogClosing(false);
      closeTimerRef.current = null;
    }, MODAL_EXIT_DURATION);
  }, [saving, isDialogClosing, editingCustomer]);

  useEffect(() => {
    if (!registerOpen && !editingCustomer && !historyCustomer) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(() => {
      modalRef.current?.querySelector<HTMLElement>("select, textarea, input:not([type=hidden]), button")?.focus();
    }, 50);

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (actionMenu) setActionMenu(null);
      else if (historyCustomer) setHistoryCustomer(null);
      else if (editingCustomer) closeEditDialog();
      else closeRegisterDialog();
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [registerOpen, editingCustomer, historyCustomer, actionMenu, closeEditDialog, closeRegisterDialog]);

  async function openRegisterDialog() {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setIsDialogClosing(false);
    setRegisterOpen(true);
    setSelectedContactId("");
    setRegistrationNotes("");
    setError("");
    setNotice("");
    setContactsLoading(true);

    try {
      const [allContacts, activeProfiles, inactiveProfiles] = await Promise.all([
        getAllActiveContacts(),
        getAllProfiles(true),
        getAllProfiles(false),
      ]);

      const existingIds = new Set(
        [...activeProfiles, ...inactiveProfiles].map(
          (profile) => profile.contact_id,
        ),
      );

      setRegisteredContactIds(existingIds);
      setContacts(allContacts.filter((contact) => !existingIds.has(contact.id)));
    } catch (loadError) {
      setError(errorMessage(loadError));
      setRegisterOpen(false);
    } finally {
      setContactsLoading(false);
    }
  }

  async function registerCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedContactId) {
      setError("Select a Contact to register as a customer.");
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");

    try {
      await customerProfilesApi.register({
        contact_id: selectedContactId,
        customer_notes: registrationNotes.trim() || null,
      });

      setRegisterOpen(false);
      setNotice("Customer registered successfully.");
      setSearch("");
      setSearchInput("");
      setStatusFilter("active");

      const result = await getAllCustomers("", "active");
      setCustomers(result.items);
      setTotal(result.total);
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  function openEditDialog(customer: CustomerProfile) {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setIsDialogClosing(false);
    setActionMenu(null);
    setEditingCustomer(customer);
    setEditingNotes(customer.customer_notes ?? "");
    setError("");
    setNotice("");
  }

  async function saveCustomerNotes(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!editingCustomer) {
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");

    try {
      await customerProfilesApi.update(editingCustomer.id, {
        customer_notes: editingNotes.trim() || null,
      });

      setEditingCustomer(null);
      setNotice("Customer notes updated.");
      await loadCustomers();
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function toggleCustomerStatus(customer: CustomerProfile) {
    setActionMenu(null);

    const action = customer.is_active ? "deactivate" : "reactivate";
    const name = displayName(customer.contact) || "this customer";

    if (
      !window.confirm(
        `Are you sure you want to ${action} ${name}'s customer profile?`,
      )
    ) {
      return;
    }

    setSaving(true);
    setError("");
    setNotice("");

    try {
      await customerProfilesApi.update(customer.id, {
        is_active: !customer.is_active,
      });

      setNotice(
        customer.is_active
          ? "Customer profile deactivated."
          : "Customer profile reactivated.",
      );
      await loadCustomers();
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchInput.trim());
    setActionMenu(null);
  }

  function changeStatus(value: StatusFilter) {
    setStatusFilter(value);
    setError("");
    setNotice("");
    setActionMenu(null);
  }

  function openActionMenu(
    event: MouseEvent<HTMLButtonElement>,
    customer: CustomerProfile,
  ) {
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 248;
    const menuHeight = 190;
    const top = rect.bottom + menuHeight + 12 > window.innerHeight
      ? Math.max(12, rect.top - menuHeight - 6)
      : rect.bottom + 6;
    const left = Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12));

    setActionMenu((current) =>
      current?.customer.id === customer.id
        ? null
        : { customer, top, left },
    );
  }

  const openColumnMenu = useCallback((event: { currentTarget: HTMLButtonElement }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 240;
    setColumnMenuPosition((current) => current ? null : {
      top: Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - 330)),
      left: Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12)),
    });
  }, []);

  const sortedCustomers = useMemo(() => {
    if (sortColumns.length === 0) return customers;
    return [...customers].sort((left, right) => {
      for (const sort of sortColumns) {
        let a: string | number = "";
        let b: string | number = "";
        switch (sort.columnKey) {
          case "customer":
            a = displayName(left.contact) || "Unnamed contact";
            b = displayName(right.contact) || "Unnamed contact";
            break;
          case "contact":
            a = `${left.contact.email || ""} ${left.contact.phone || ""}`;
            b = `${right.contact.email || ""} ${right.contact.phone || ""}`;
            break;
          case "registered":
            a = new Date(left.created_at).getTime() || 0;
            b = new Date(right.created_at).getTime() || 0;
            break;
          case "status":
            a = left.is_active ? "Active" : "Inactive";
            b = right.is_active ? "Active" : "Inactive";
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
  }, [customers, sortColumns]);

  const columns = useMemo<readonly Column<CustomerProfile>[]>(() => [
    {
      key: "customer", name: "Customer", minWidth: 210, width: 280, resizable: true, sortable: true,
      renderCell: ({ row }) => {
        const name = displayName(row.contact) || "Unnamed contact";
        return <div className="customers-grid-person"><span className="customers-grid-avatar" aria-hidden="true">{getInitials(name)}</span><span className="customers-grid-person-copy"><strong title={name}>{name}</strong><span title={row.customer_notes?.trim() || "No customer notes"}>{row.customer_notes?.trim() || "No customer notes"}</span></span></div>;
      },
    },
    {
      key: "contact", name: "Contact details", minWidth: 210, width: 260, resizable: true, sortable: true,
      renderCell: ({ row }) => <span className="customers-grid-contact"><span title={row.contact.email || "No email"}>{row.contact.email || "No email"}</span><span title={row.contact.phone || "No phone"}>{row.contact.phone || "No phone"}</span></span>,
    },
    {
      key: "registered", name: "Registered", minWidth: 120, width: 145, resizable: true, sortable: true,
      renderCell: ({ row }) => <span className="customers-grid-date">{formatDate(row.created_at)}</span>,
    },
    {
      key: "status", name: "Status", minWidth: 110, width: 125, resizable: true, sortable: true,
      renderCell: ({ row }) => <span className={`customers-status-pill ${row.is_active ? "is-active" : "is-inactive"}`}><span aria-hidden="true" />{row.is_active ? "Active" : "Inactive"}</span>,
    },
    {
      key: "actions", name: "Actions", minWidth: 76, width: 88, resizable: false, sortable: false,
      renderCell: ({ row }) => {
        const name = displayName(row.contact) || "customer";
        return <div className="customers-grid-row-actions" role="group" aria-label={`Actions for ${name}`} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}><button type="button" className="customers-grid-action-trigger" aria-label={`Open actions for ${name}`} aria-haspopup="menu" aria-expanded={actionMenu?.customer.id === row.id} title="Customer actions" disabled={saving} onClick={(event) => openActionMenu(event, row)}><svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg></button></div>;
      },
    },
    {
      key: "configure", name: "", width: "1fr", minWidth: 44, resizable: false, sortable: false,
      renderHeaderCell: () => <button className="customers-configure-columns-button" type="button" onClick={openColumnMenu} aria-label="Configure table columns" title="Configure columns" aria-expanded={columnMenuPosition !== null}><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 4v16M15 4v16"/></svg></button>,
      renderCell: () => <span aria-hidden="true" />,
    },
  ], [actionMenu, columnMenuPosition, openColumnMenu, saving]);

  const visibleColumns = useMemo(
    () => columns.filter((column) => column.key === "configure" || column.key === "actions" || visibleColumnKeys.includes(column.key)),
    [columns, visibleColumnKeys],
  );

  const registeredContactOptions = contacts.filter(
    (contact) => !registeredContactIds.has(contact.id),
  );

  return (
    <section className="customers-page">
      <header className="customers-header">
        <div>
          <h1>Customers</h1>
          <p className="customers-subtitle">
            Manage customer profiles linked to your existing contacts.
          </p>
        </div>
      </header>

      {error && (
        <div className="customers-alert customers-alert-error" role="alert">
          <span>{error}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setError("")}
          >
            ×
          </button>
        </div>
      )}

      {notice && (
        <div className="customers-alert customers-alert-success" role="status">
          <span>{notice}</span>
          <button
            type="button"
            aria-label="Dismiss message"
            onClick={() => setNotice("")}
          >
            ×
          </button>
        </div>
      )}

      <div className="customers-toolbar">
        <form className="customers-search-form" onSubmit={submitSearch}>
          <label className="customers-search-field">
            <span className="customers-visually-hidden">Search customers</span>
            <span className="customers-search-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-4-4" />
              </svg>
            </span>
            <input
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Search customer name, email or phone"
              aria-label="Search customer name, email or phone"
            />
            {searchInput && (
              <button
                type="button"
                className="customers-search-clear"
                aria-label="Clear customer search"
                onClick={() => {
                  setSearchInput("");
                  setSearch("");
                  setActionMenu(null);
                }}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="m18 6-12 12M6 6l12 12" /></svg>
              </button>
            )}
          </label>
        </form>

        <label className="customers-status-filter">
          <span>Status</span>
          <select
            value={statusFilter}
            onChange={(event) => changeStatus(event.target.value as StatusFilter)}
            disabled={loading || saving}
          >
            <option value="active">Active customers</option>
            <option value="inactive">Inactive customers</option>
          </select>
        </label>

        <button
          type="button"
          className="customers-button customers-button-primary customers-add-button"
          onClick={() => void openRegisterDialog()}
          disabled={saving}
        >
          <span aria-hidden="true">＋</span> Register customer
        </button>
      </div>

      {loading ? (
        <div className="customers-state" role="status" aria-live="polite">
          <span className="customers-spinner" aria-hidden="true" />
          <p>Loading customer profiles…</p>
        </div>
      ) : customers.length === 0 ? (
        <div className="customers-state customers-empty-state">
          <div className="customers-empty-icon" aria-hidden="true">◎</div>
          <h3>{search ? "No matching customers" : statusFilter === "active" ? "No active customers yet" : "No inactive customers"}</h3>
          <p>{search ? "Try a different search term." : statusFilter === "active" ? "Register an existing Contact to create a customer profile." : "Deactivated profiles will appear here."}</p>
          {!search && statusFilter === "active" && (
            <button type="button" className="customers-button customers-button-primary" onClick={() => void openRegisterDialog()}>
              Register your first customer
            </button>
          )}
        </div>
      ) : (
        <section className="customers-grid-shell" aria-label="Customer directory">
          <DataGrid
            className="customers-react-data-grid"
            aria-label="Customers directory"
            columns={visibleColumns}
            rows={sortedCustomers}
            rowKeyGetter={(row) => row.id}
            rowHeight={compactGrid ? 48 : 62}
            headerRowHeight={52}
            defaultColumnOptions={{ resizable: true, sortable: true }}
            sortColumns={sortColumns}
            onSortColumnsChange={setSortColumns}
            style={{
              height: Math.min(
                52 + sortedCustomers.length * (compactGrid ? 48 : 62),
                Math.max(260, (typeof window !== "undefined" ? window.innerHeight : 900) * 0.68),
              ),
              minHeight: 52 + Math.min(sortedCustomers.length, 1) * (compactGrid ? 48 : 62),
            }}
            renderers={{ noRowsFallback: <div className="customers-grid-no-rows">No customers to display.</div> }}
          />
          <footer className="customers-grid-footer" aria-live="polite">
            <span>
              {search || statusFilter === "inactive"
                ? `${customers.length} ${customers.length === 1 ? "customer" : "customers"} shown`
                : `${total} ${total === 1 ? "customer" : "customers"} in your workspace`}
            </span>
            <span className="customers-caught-up"><span aria-hidden="true" />You’re all caught up</span>
          </footer>
        </section>
      )}

      {actionMenu && createPortal(
        <div
          className="customers-action-menu-layer"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setActionMenu(null);
            }
          }}
        >
          <div
            className="customers-action-menu"
            role="menu"
            aria-label={`Actions for ${displayName(actionMenu.customer.contact) || "customer"}`}
            style={{ top: actionMenu.top, left: actionMenu.left }}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                const customer = actionMenu.customer;
                setActionMenu(null);
                setHistoryCustomer(customer);
              }}
            >
              <span className="customers-menu-icon" aria-hidden="true">◷</span>
              View visit history
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => openEditDialog(actionMenu.customer)}
            >
              <span className="customers-menu-icon" aria-hidden="true">✎</span>
              Edit notes
            </button>
            <div className="customers-action-menu-divider" />
            <button
              type="button"
              role="menuitem"
              className={actionMenu.customer.is_active ? "is-danger" : "is-positive"}
              onClick={() => void toggleCustomerStatus(actionMenu.customer)}
            >
              <span className="customers-menu-icon" aria-hidden="true">
                {actionMenu.customer.is_active ? "⊘" : "✓"}
              </span>
              {actionMenu.customer.is_active ? "Deactivate customer" : "Reactivate customer"}
            </button>
          </div>
        </div>,
        document.body,
      )}

      {columnMenuPosition && createPortal(
        <div className="customers-column-menu-layer" onPointerDown={() => setColumnMenuPosition(null)} role="presentation">
          <div className="customers-column-menu" style={{ top: columnMenuPosition.top, left: columnMenuPosition.left }} role="dialog" aria-label="Configure table columns" onPointerDown={(event) => event.stopPropagation()}>
            <div className="customers-column-menu-heading"><div><strong>Configure columns</strong><span>Choose which fields are visible.</span></div><button type="button" aria-label="Close column configuration" onClick={() => setColumnMenuPosition(null)}>×</button></div>
            {[
              { key: "customer", label: "Customer" },
              { key: "contact", label: "Contact details" },
              { key: "registered", label: "Registered" },
              { key: "status", label: "Status" },
            ].map((column) => <label className="customers-column-option" key={column.key}><input type="checkbox" checked={visibleColumnKeys.includes(column.key)} onChange={(event) => setVisibleColumnKeys((current) => event.target.checked ? [...current, column.key] : current.filter((key) => key !== column.key))} /><span>{column.label}</span></label>)}
            <div className="customers-column-menu-footer"><button type="button" onClick={() => setVisibleColumnKeys(["customer", "contact", "registered", "status"])}>Reset columns</button><button type="button" onClick={() => setColumnMenuPosition(null)}>Done</button></div>
          </div>
        </div>, document.body,
      )}

      {registerOpen && createPortal(
        <div
          className={`customers-modal-backdrop ${isDialogClosing ? "is-closing" : ""}`}
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeRegisterDialog();
          }}
        >
          <section
            ref={modalRef}
            className={`customers-modal ${isDialogClosing ? "is-closing" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="customers-register-title"
          >
            <header className="customers-modal-header">
              <div>
                <p className="customers-eyebrow">CUSTOMER PROFILE</p>
                <h2 id="customers-register-title">Register a customer</h2>
                <p>Select an existing Contact to create a customer profile.</p>
              </div>
              <button
                type="button"
                className="customers-modal-close"
                aria-label="Close dialog"
                onClick={closeRegisterDialog}
                disabled={saving || isDialogClosing}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="m18 6-12 12M6 6l12 12" /></svg>
              </button>
            </header>

            <form className="customers-modal-form" onSubmit={registerCustomer}>
              <div className="customers-modal-body">
                {contactsLoading ? (
                  <div className="customers-state compact">
                    <span className="customers-spinner" aria-hidden="true" />
                    <p>Loading available Contacts…</p>
                  </div>
                ) : (
                  <>
                    <div className="customers-form-section">
                      <h3>Customer details</h3>
                      <p>Only active Contacts that are not already registered can be selected.</p>
                    </div>
                    <label className="customers-form-field">
                      <span>Existing Contact <i>*</i></span>
                      <select
                        required
                        value={selectedContactId}
                        onChange={(event) => setSelectedContactId(event.target.value)}
                        disabled={saving || registeredContactOptions.length === 0}
                      >
                        <option value="">Select a Contact</option>
                        {registeredContactOptions.map((contact) => (
                          <option key={contact.id} value={contact.id}>
                            {displayName(contact) || "Unnamed contact"}
                            {contact.email ? ` · ${contact.email}` : ""}
                            {contact.phone ? ` · ${contact.phone}` : ""}
                          </option>
                        ))}
                      </select>
                      <small>
                        {registeredContactOptions.length === 0
                          ? "All active Contacts are already registered, or there are no active Contacts."
                          : `${registeredContactOptions.length} available Contact${registeredContactOptions.length === 1 ? "" : "s"}.`}
                      </small>
                    </label>
                    <label className="customers-form-field">
                      <span>Customer notes</span>
                      <textarea
                        rows={4}
                        value={registrationNotes}
                        onChange={(event) => setRegistrationNotes(event.target.value)}
                        placeholder="Add useful context, preferences or requirements (optional)"
                        maxLength={5000}
                        disabled={saving}
                      />
                      <small>{registrationNotes.length}/5000 characters</small>
                    </label>
                  </>
                )}
              </div>

              <footer className="customers-modal-footer">
                <button
                  type="button"
                  className="customers-button customers-button-secondary"
                  onClick={closeRegisterDialog}
                  disabled={saving || isDialogClosing}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="m18 6-12 12M6 6l12 12" /></svg>
                  Cancel
                </button>
                <button
                  type="submit"
                  className="customers-button customers-button-primary"
                  disabled={
                    saving || contactsLoading || !selectedContactId ||
                    registeredContactOptions.length === 0
                  }
                >
                  {!saving && <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>}
                  {saving ? "Registering…" : "Register customer"}
                </button>
              </footer>
            </form>
          </section>
        </div>,
        document.body,
      )}

      {editingCustomer && createPortal(
        <div
          className={`customers-modal-backdrop ${isDialogClosing ? "is-closing" : ""}`}
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeEditDialog();
          }}
        >
          <section
            ref={modalRef}
            className={`customers-modal customers-modal-compact ${isDialogClosing ? "is-closing" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="customers-edit-title"
          >
            <header className="customers-modal-header">
              <div>
                <p className="customers-eyebrow">CUSTOMER PROFILE</p>
                <h2 id="customers-edit-title">Edit customer notes</h2>
                <p>{displayName(editingCustomer.contact)}</p>
              </div>
              <button
                type="button"
                className="customers-modal-close"
                aria-label="Close dialog"
                onClick={closeEditDialog}
                disabled={saving || isDialogClosing}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="m18 6-12 12M6 6l12 12" /></svg>
              </button>
            </header>

            <form className="customers-modal-form" onSubmit={saveCustomerNotes}>
              <div className="customers-modal-body">
                <label className="customers-form-field">
                  <span>Customer notes</span>
                  <textarea
                    rows={5}
                    value={editingNotes}
                    onChange={(event) => setEditingNotes(event.target.value)}
                    placeholder="Add relevant customer notes"
                    maxLength={5000}
                    disabled={saving}
                  />
                  <small>{editingNotes.length}/5000 characters</small>
                </label>
              </div>
              <footer className="customers-modal-footer">
                <button
                  type="button"
                  className="customers-button customers-button-secondary"
                  onClick={closeEditDialog}
                  disabled={saving || isDialogClosing}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="m18 6-12 12M6 6l12 12" /></svg>
                  Cancel
                </button>
                <button
                  type="submit"
                  className="customers-button customers-button-primary"
                  disabled={saving}
                >
                  {!saving && <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" /><path d="M17 21v-8H7v8M7 3v5h8" /></svg>}
                  {saving ? "Saving…" : "Save notes"}
                </button>
              </footer>
            </form>
          </section>
        </div>,
        document.body,
      )}

      {historyCustomer && createPortal(
        <div
          className="customers-modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setHistoryCustomer(null);
            }
          }}
        >
          <section
            className="customers-modal customers-history-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="customer-visit-history-title"
          >
            <header className="customers-modal-header">
              <div>
                <p className="customers-eyebrow">CUSTOMER PROFILE</p>
                <h2 id="customer-visit-history-title">Visit history</h2>
                <p>{displayName(historyCustomer.contact)}</p>
              </div>
              <button
                type="button"
                className="customers-modal-close"
                aria-label="Close visit history"
                onClick={() => setHistoryCustomer(null)}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="m18 6-12 12M6 6l12 12" /></svg>
              </button>
            </header>
            <div className="customers-modal-body customers-history-body">
              <SiteVisitHistory
                customerProfileId={historyCustomer.id}
                title="Customer site visits"
              />
            </div>
            <footer className="customers-modal-footer">
              <button
                type="button"
                className="customers-button customers-button-secondary"
                onClick={() => setHistoryCustomer(null)}
              >
                Close
              </button>
            </footer>
          </section>
        </div>,
        document.body,
      )}
    </section>
  );
}

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";
import { DataGrid, type Column, type SortColumn } from "react-data-grid";
import "react-data-grid/lib/styles.css";

import GridColumnOptionList from "../components/GridColumnOptionList";
import { useGridViewPreferences } from "../hooks/useGridViewPreferences";
import { ApiError } from "../lib/api";
import { CONTACTS_GRID_VIEW } from "../lib/gridViewConfigs";
import { arrangeGridColumns } from "../lib/gridViewPreferences";
import {
  contactsApi,
  type Contact,
  type ContactCreateInput,
} from "../services/contactApi";
import "./ContactsPage.css";

const PAGE_SIZE = 100;
const MODAL_EXIT_DURATION = 200;

const EMPTY_FORM: ContactCreateInput = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
};

type ContactFieldErrors = {
  email?: string;
  phone?: string;
};

type ContactActionMenu = {
  contact: Contact;
  top: number;
  left: number;
};

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
}

function getDuplicateFieldErrors(error: unknown): ContactFieldErrors {
  if (!(error instanceof ApiError)) return {};

  // Errors arrive as { error: { code, message, details } }.
  const body = error.details as { error?: { details?: unknown } } | null | undefined;
  const duplicate = body?.error?.details as { code?: unknown; fields?: unknown } | undefined;
  if (!duplicate || duplicate.code !== "duplicate_contact" || !Array.isArray(duplicate.fields)) {
    return {};
  }

  const errors: ContactFieldErrors = {};
  if (duplicate.fields.includes("email")) {
    errors.email = "A contact with this email address already exists in your organization.";
  }
  if (duplicate.fields.includes("phone")) {
    errors.phone = "A contact with this phone number already exists in your organization.";
  }
  return errors;
}

function getContactName(contact: Contact): string {
  return [contact.first_name, contact.last_name].filter(Boolean).join(" ").trim() || "Unnamed contact";
}

function getInitials(contact: Contact): string {
  return getContactName(contact)
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("") || "C";
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

async function fetchAllContacts(search?: string): Promise<Contact[]> {
  const firstPage = await contactsApi.list({
    page: 1,
    page_size: PAGE_SIZE,
    search: search || undefined,
  });
  const contacts = [...firstPage.items];

  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const result = await contactsApi.list({
      page,
      page_size: PAGE_SIZE,
      search: search || undefined,
    });
    contacts.push(...result.items);
  }

  return contacts;
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </svg>
  );
}

function ContactsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="10" cy="7" r="4" />
      <path d="M20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" />
    </svg>
  );
}

function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  );
}

function PhoneIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.4 19.4 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7l.5 2.8a2 2 0 0 1-.6 1.8L7.7 9.6a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 1.8-.6l2.8.5a2 2 0 0 1 1.7 2.7Z" />
    </svg>
  );
}

function DetailsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" />
    </svg>
  );
}

export default function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [sortColumns, setSortColumns] = useState<SortColumn[]>([]);
  const gridView = useGridViewPreferences(CONTACTS_GRID_VIEW);
  const [columnMenuPosition, setColumnMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingContact, setEditingContact] = useState<Contact | null>(null);
  const [isFormClosing, setIsFormClosing] = useState(false);
  const [form, setForm] = useState<ContactCreateInput>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<ContactFieldErrors>({});
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null);
  const [actionMenu, setActionMenu] = useState<ContactActionMenu | null>(null);

  const modalRef = useRef<HTMLElement>(null);
  const actionMenuRef = useRef<HTMLElement>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadContacts = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setContacts(await fetchAllContacts(search));
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const result = await fetchAllContacts(search);
        if (cancelled) return;
        setContacts(result);
        setError("");
      } catch (loadError) {
        if (!cancelled) setError(getErrorMessage(loadError));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [search]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const nextSearch = searchInput.trim();
      if (nextSearch !== search) setSearch(nextSearch);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput, search]);

  useEffect(() => {
    if (!isFormOpen && !selectedContact) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusTimer = window.setTimeout(() => {
      modalRef.current?.querySelector<HTMLInputElement>('input:not([type="hidden"])')?.focus();
    }, 50);

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (actionMenu) {
        setActionMenu(null);
      } else if (selectedContact) {
        setSelectedContact(null);
      } else if (!saving) {
        closeCreateForm();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKeyDown);
    };
    // The effect installs keyboard handling for the currently open dialog.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isFormOpen, selectedContact, saving, actionMenu]);

  useEffect(() => {
    if (!actionMenu) return;

    function onPointerDown(event: PointerEvent) {
      if (event.target instanceof Node && !actionMenuRef.current?.contains(event.target)) {
        setActionMenu(null);
      }
    }
    function onEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setActionMenu(null);
    }
    function closeOnViewportChange() {
      setActionMenu(null);
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onEscape);
    window.addEventListener("resize", closeOnViewportChange);
    window.addEventListener("scroll", closeOnViewportChange, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onEscape);
      window.removeEventListener("resize", closeOnViewportChange);
      window.removeEventListener("scroll", closeOnViewportChange, true);
    };
  }, [actionMenu]);

  useEffect(() => () => {
    if (closeTimerRef.current !== null) window.clearTimeout(closeTimerRef.current);
  }, []);

  const openActionMenu = useCallback((event: MouseEvent<HTMLButtonElement>, contact: Contact) => {
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 220;
    const menuHeight = 230;
    const left = Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12));
    const top = rect.bottom + menuHeight + 8 > window.innerHeight
      ? Math.max(12, rect.top - menuHeight - 8)
      : rect.bottom + 8;

    setActionMenu((current) => current?.contact.id === contact.id ? null : { contact, top, left });
  }, []);

  const openColumnMenu = useCallback((event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 260;
    const menuHeight = 330;
    const left = Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12));
    const top = rect.bottom + menuHeight + 8 > window.innerHeight
      ? Math.max(12, rect.top - menuHeight - 8)
      : rect.bottom + 8;

    setColumnMenuPosition((current) => current ? null : { top, left });
  }, []);

  useEffect(() => {
    if (!columnMenuPosition) return;

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setColumnMenuPosition(null);
    }
    function closeOnViewportChange() {
      setColumnMenuPosition(null);
    }

    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeOnViewportChange);
    window.addEventListener("scroll", closeOnViewportChange, true);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeOnViewportChange);
      window.removeEventListener("scroll", closeOnViewportChange, true);
    };
  }, [columnMenuPosition]);

  const sortedContacts = useMemo(() => {
    if (sortColumns.length === 0) return contacts;
    const sort = sortColumns[0];

    return [...contacts].sort((first, second) => {
      const value = (contact: Contact): string | number => {
        switch (sort.columnKey) {
          case "name": return getContactName(contact).toLocaleLowerCase();
          case "email": return (contact.email || "").toLocaleLowerCase();
          case "phone": return contact.phone || "";
          case "createdAt": return new Date(contact.created_at).getTime() || 0;
          case "status": return contact.is_active ? 1 : 0;
          default: return "";
        }
      };
      const a = value(first);
      const b = value(second);
      const result = typeof a === "number" && typeof b === "number"
        ? a - b
        : String(a).localeCompare(String(b));
      return sort.direction === "DESC" ? -result : result;
    });
  }, [contacts, sortColumns]);

  const columns = useMemo<readonly Column<Contact>[]>(() => [
    {
      key: "name",
      name: "Contact",
      minWidth: 220,
      width: 280,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => (
        <div className="contacts-person-cell">
          <span className="contacts-avatar" aria-hidden="true">{getInitials(row)}</span>
          <span className="contacts-person-copy">
            <strong title={getContactName(row)}>{getContactName(row)}</strong>
            <span title={row.email || row.phone || "No contact details"}>{row.email || row.phone || "No email or phone added"}</span>
          </span>
        </div>
      ),
    },
    {
      key: "email",
      name: "Email address",
      minWidth: 190,
      width: 240,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => <span className="contacts-cell-text" title={row.email || ""}>{row.email || "—"}</span>,
    },
    {
      key: "phone",
      name: "Phone number",
      minWidth: 150,
      width: 175,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => <span className="contacts-cell-text" title={row.phone || ""}>{row.phone || "—"}</span>,
    },
    {
      key: "createdAt",
      name: "Created",
      minWidth: 120,
      width: 140,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => <span className="contacts-date">{formatDate(row.created_at)}</span>,
    },
    {
      key: "status",
      name: "Status",
      minWidth: 110,
      width: 125,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => (
        <span className={`contacts-status ${row.is_active ? "contacts-status-active" : "contacts-status-inactive"}`}>
          <span aria-hidden="true" />{row.is_active ? "Active" : "Inactive"}
        </span>
      ),
    },
    {
      key: "actions",
      name: "Actions",
      minWidth: 88,
      width: 100,
      resizable: false,
      sortable: false,
      renderCell: ({ row }) => (
        <div className="contacts-row-actions" role="group" aria-label={`Actions for ${getContactName(row)}`} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
          <button
            className="contacts-icon-action"
            type="button"
            aria-label={`Open actions for ${getContactName(row)}`}
            aria-haspopup="menu"
            aria-expanded={actionMenu?.contact.id === row.id}
            title="Contact actions"
            onClick={(event) => openActionMenu(event, row)}
          >
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
            </svg>
          </button>
        </div>
      ),
    },
    {
      key: "configure",
      name: "",
      width: "1fr",
      minWidth: 44,
      resizable: false,
      sortable: false,
      renderHeaderCell: () => (
        <button
          className="contacts-configure-columns-button"
          type="button"
          onClick={openColumnMenu}
          aria-label="Configure table columns"
          title="Configure columns"
          aria-expanded={columnMenuPosition !== null}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="4" y="4" width="16" height="16" rx="2" /><path d="M9 4v16M15 4v16" />
          </svg>
        </button>
      ),
      renderCell: () => <span aria-hidden="true" />,
    },
  ], [actionMenu, openActionMenu, openColumnMenu, columnMenuPosition]);

  const visibleColumns = useMemo(
    () => arrangeGridColumns(columns, CONTACTS_GRID_VIEW.columnOptions, gridView.preferences),
    [columns, gridView.preferences],
  );

  function openEditForm(contact: Contact) {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setEditingContact(contact);
    setForm({
      first_name: contact.first_name,
      last_name: contact.last_name ?? "",
      email: contact.email ?? "",
      phone: contact.phone ?? "",
    });
    setFormError("");
    setFieldErrors({});
    setSuccess("");
    setIsFormClosing(false);
    setIsFormOpen(true);
  }

  function openCreateForm() {
    setEditingContact(null);
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setForm(EMPTY_FORM);
    setFormError("");
    setFieldErrors({});
    setSuccess("");
    setIsFormClosing(false);
    setIsFormOpen(true);
  }

  function closeCreateForm() {
    if (saving || isFormClosing || !isFormOpen) return;
    setFormError("");
    setFieldErrors({});
    setIsFormClosing(true);
    closeTimerRef.current = window.setTimeout(() => {
      setIsFormOpen(false);
      setIsFormClosing(false);
      closeTimerRef.current = null;
    }, MODAL_EXIT_DURATION);
  }

  async function handleCreateContact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setFieldErrors({});
    setSuccess("");

    const firstName = form.first_name.trim();
    const lastName = form.last_name?.trim() ?? "";
    const email = form.email?.trim() ?? "";
    const phone = form.phone?.trim() ?? "";

    if (!firstName) {
      setFormError("First name is required.");
      return;
    }
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setFormError("Enter a valid email address.");
      return;
    }

    const payload: ContactCreateInput = {
      first_name: firstName,
      last_name: lastName || null,
      email: email || null,
      phone: phone || null,
    };

    setSaving(true);
    try {
      if (editingContact) {
        const updated = await contactsApi.update(editingContact.id, payload);
        setSelectedContact((current) => (current?.id === updated.id ? updated : current));
      } else {
        await contactsApi.create(payload);
      }
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
      setIsFormOpen(false);
      setIsFormClosing(false);
      setForm(EMPTY_FORM);
      setFormError("");
      if (!editingContact) {
        setSearchInput("");
        setSearch("");
      }
      setEditingContact(null);
      setSuccess(editingContact ? "Contact updated successfully." : "Contact created successfully.");
      setContacts(await fetchAllContacts());
      setError("");
    } catch (createError) {
      const duplicateErrors = getDuplicateFieldErrors(createError);
      if (Object.keys(duplicateErrors).length > 0) {
        setFieldErrors(duplicateErrors);
      } else {
        setFormError(getErrorMessage(createError));
      }
    } finally {
      setSaving(false);
    }
  }

  async function copyContactValue(value: string | null | undefined, label: string) {
    const contact = actionMenu?.contact;
    if (!value) return;

    try {
      await navigator.clipboard.writeText(value);
      setSuccess(`${label} copied to clipboard.`);
      setActionMenu(null);
    } catch {
      setActionMenu(null);
      if (contact) setSelectedContact(contact);
      setSuccess(`Clipboard access is unavailable. You can copy the ${label.toLowerCase()} from contact details.`);
    }
  }

  return (
    <main className="contacts-page contacts-workspace">
      <header className="contacts-page-header">
        <div className="contacts-heading-copy">
          <h1>Contacts</h1>
          <p>Keep your relationships organized and contact details ready when you need them.</p>
        </div>
      </header>

      {success && (
        <div className="contacts-alert contacts-alert-success" role="status">
          <span>{success}</span>
          <button type="button" className="contacts-dismiss" onClick={() => setSuccess("")} aria-label="Dismiss success message">×</button>
        </div>
      )}

      <div className="contacts-filterbar">
        <form className="contacts-search-field" onSubmit={(event) => { event.preventDefault(); setSearch(searchInput.trim()); }}>
          <SearchIcon />
          <label className="contacts-visually-hidden" htmlFor="contacts-search">Search contacts</label>
          <input id="contacts-search" type="search" maxLength={320} value={searchInput} placeholder="Search name, email or phone number" onChange={(event) => setSearchInput(event.target.value)} />
          {searchInput && <button type="button" aria-label="Clear search" onClick={() => { setSearchInput(""); setSearch(""); }}>×</button>}
        </form>
        {(searchInput || search) && <button className="contacts-clear-filters" type="button" onClick={() => { setSearchInput(""); setSearch(""); }}>Clear search</button>}
        <button className="contacts-primary-button contacts-add-button" type="button" onClick={openCreateForm}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
          Add contact
        </button>
      </div>

      {error && (
        <div className="contacts-alert contacts-alert-error" role="alert">
          <div><strong>We couldn’t load contacts</strong><p>{error}</p></div>
          <button className="contacts-secondary-button" type="button" onClick={() => void loadContacts()}>Try again</button>
        </div>
      )}

      {loading ? (
        <div className="contacts-state" role="status" aria-live="polite"><span className="contacts-spinner" aria-hidden="true" /><p>Loading contacts…</p></div>
      ) : !error && sortedContacts.length === 0 ? (
        <div className="contacts-empty">
          <div className="contacts-empty-icon" aria-hidden="true"><ContactsIcon /></div>
          <h3>{search ? "No contacts match this search" : "Start with your first contact"}</h3>
          <p>{search ? "Try another name, email or phone number, or clear your search." : "Add a contact to keep important customer and business details together."}</p>
          {search ? <button className="contacts-secondary-button" type="button" onClick={() => { setSearchInput(""); setSearch(""); }}>Clear search</button> : <button className="contacts-primary-button" type="button" onClick={openCreateForm}>Add your first contact</button>}
        </div>
      ) : !error ? (
        <section className="contacts-grid-shell" aria-label="Contacts grid">
          <DataGrid
            className="contacts-react-data-grid"
            aria-label="Contacts directory"
            columns={visibleColumns}
            rows={sortedContacts}
            rowKeyGetter={(row) => row.id}
            rowHeight={gridView.rowHeight}
            headerRowHeight={52}
            defaultColumnOptions={{ resizable: true, sortable: true }}
            sortColumns={sortColumns}
            onSortColumnsChange={setSortColumns}
            style={{
              height: Math.min(52 + sortedContacts.length * gridView.rowHeight, Math.max(260, (typeof window !== "undefined" ? window.innerHeight : 900) * 0.68)),
              minHeight: 112,
            }}
            renderers={{ noRowsFallback: <div className="contacts-grid-no-rows">No contacts to display.</div> }}
          />
          <footer className="contacts-grid-footer" aria-live="polite">
            <span className="contacts-grid-footer-count"><strong>{sortedContacts.length}</strong> {sortedContacts.length === 1 ? "contact" : "contacts"}{search ? " match your search" : " in your workspace"}</span>
            <span className="contacts-grid-footer-status"><span aria-hidden="true" />{search ? "Filtered results" : "You’re all caught up"}</span>
          </footer>
        </section>
      ) : null}

      {columnMenuPosition && createPortal(
        <div className="contacts-column-menu-layer" onPointerDown={() => setColumnMenuPosition(null)} role="presentation">
          <section
            className="contacts-column-menu"
            style={{ top: columnMenuPosition.top, left: columnMenuPosition.left }}
            role="dialog"
            aria-label="Configure table columns"
            onPointerDown={(event) => event.stopPropagation()}
          >
            <header className="contacts-column-menu-heading">
              <div><strong>Configure columns</strong><span>Choose which fields are visible.</span></div>
              <button type="button" aria-label="Close column configuration" onClick={() => setColumnMenuPosition(null)}>×</button>
            </header>
            <GridColumnOptionList
              columnOptions={gridView.columnOptions}
              onVisibilityChange={gridView.setColumnVisible}
              onMove={gridView.moveColumn}
            />
            <footer className="contacts-column-menu-footer">
              <button type="button" onClick={gridView.resetColumns}>Reset columns</button>
              <button type="button" onClick={() => setColumnMenuPosition(null)}>Done</button>
            </footer>
          </section>
        </div>,
        document.body,
      )}

      {actionMenu && createPortal(
        <div className="contacts-action-menu-layer" role="presentation" onPointerDown={() => setActionMenu(null)}>
          <section ref={actionMenuRef} className="contacts-action-menu" style={{ top: actionMenu.top, left: actionMenu.left }} role="menu" aria-label="Contact actions" onPointerDown={(event) => event.stopPropagation()}>
            <header className="contacts-action-menu-header"><strong>Contact actions</strong><span title={getContactName(actionMenu.contact)}>{getContactName(actionMenu.contact)}</span></header>
            <button type="button" role="menuitem" onClick={() => { openEditForm(actionMenu.contact); setActionMenu(null); }}>Edit contact</button>
            <button type="button" role="menuitem" onClick={() => { setSelectedContact(actionMenu.contact); setActionMenu(null); }}><DetailsIcon />View contact details</button>
            <button type="button" role="menuitem" disabled={!actionMenu.contact.email} onClick={() => void copyContactValue(actionMenu.contact.email, "Email address")}><CopyIcon />Copy email address</button>
            <button type="button" role="menuitem" disabled={!actionMenu.contact.phone} onClick={() => void copyContactValue(actionMenu.contact.phone, "Phone number")}><CopyIcon />Copy phone number</button>
            <a role="menuitem" className={!actionMenu.contact.email ? "is-disabled" : ""} aria-disabled={!actionMenu.contact.email} href={actionMenu.contact.email ? `mailto:${actionMenu.contact.email}` : undefined} onClick={() => setActionMenu(null)}><MailIcon />Send email</a>
            <a role="menuitem" className={!actionMenu.contact.phone ? "is-disabled" : ""} aria-disabled={!actionMenu.contact.phone} href={actionMenu.contact.phone ? `tel:${actionMenu.contact.phone}` : undefined} onClick={() => setActionMenu(null)}><PhoneIcon />Call contact</a>
          </section>
        </div>,
        document.body,
      )}

      {selectedContact && createPortal(
        <div className="contacts-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedContact(null); }}>
          <section className="contacts-modal contacts-details-modal" role="dialog" aria-modal="true" aria-labelledby="contacts-details-title">
            <header className="contacts-modal-header">
              <div><span className="contacts-eyebrow">CONTACT PROFILE</span><h2 id="contacts-details-title">{getContactName(selectedContact)}</h2><p>Contact information and account status.</p></div>
              <button type="button" className="contacts-modal-close" onClick={() => setSelectedContact(null)} aria-label="Close contact details">×</button>
            </header>
            <div className="contacts-details-body">
              <div className="contacts-details-identity">
                <span className="contacts-avatar contacts-avatar-large" aria-hidden="true">{getInitials(selectedContact)}</span>
                <div><strong>{getContactName(selectedContact)}</strong><span className={`contacts-status ${selectedContact.is_active ? "contacts-status-active" : "contacts-status-inactive"}`}><span aria-hidden="true" />{selectedContact.is_active ? "Active" : "Inactive"}</span></div>
              </div>
              <dl className="contacts-details-list">
                <div><dt>Email address</dt><dd>{selectedContact.email || "Not provided"}{selectedContact.email && <button type="button" className="contacts-inline-action" onClick={() => void copyContactValue(selectedContact.email, "Email address")} aria-label="Copy email address" title="Copy email address"><CopyIcon /></button>}</dd></div>
                <div><dt>Phone number</dt><dd>{selectedContact.phone || "Not provided"}{selectedContact.phone && <button type="button" className="contacts-inline-action" onClick={() => void copyContactValue(selectedContact.phone, "Phone number")} aria-label="Copy phone number" title="Copy phone number"><CopyIcon /></button>}</dd></div>
                <div><dt>Created</dt><dd>{formatDate(selectedContact.created_at)}</dd></div>
                <div><dt>Contact ID</dt><dd className="contacts-id-value">{selectedContact.id}</dd></div>
              </dl>
            </div>
            <footer className="contacts-modal-footer">
              <button className="contacts-secondary-button" type="button" onClick={() => setSelectedContact(null)}>Close</button>
              {selectedContact.email && <a className="contacts-primary-button" href={`mailto:${selectedContact.email}`}><MailIcon />Send email</a>}
            </footer>
          </section>
        </div>,
        document.body,
      )}

      {isFormOpen && createPortal(
        <div className={`contacts-modal-backdrop ${isFormClosing ? "is-closing" : ""}`} onMouseDown={(event) => { if (event.target === event.currentTarget) closeCreateForm(); }}>
          <section ref={modalRef} className={`contacts-modal ${isFormClosing ? "is-closing" : ""}`} role="dialog" aria-modal="true" aria-labelledby="contacts-modal-title">
            <header className="contacts-modal-header">
              <div><span className="contacts-eyebrow">CONTACT DETAILS</span><h2 id="contacts-modal-title">{editingContact ? "Edit contact" : "Add a contact"}</h2><p>{editingContact ? "Update this contact's details. Email and phone must stay unique in your organization." : "Create a contact record for your workspace."}</p></div>
              <button type="button" className="contacts-modal-close" onClick={closeCreateForm} disabled={saving || isFormClosing} aria-label="Close form">×</button>
            </header>
            <form className="contacts-form" onSubmit={handleCreateContact}>
              <div className="contacts-form-body">
                {formError && <div className="contacts-alert contacts-alert-error" role="alert">{formError}</div>}
                <div className="contacts-form-section"><h3>Basic information</h3><p>Name is required. Add an email address or phone number to make this contact easier to reach.</p></div>
                <div className="contacts-form-grid">
                  <label className="contacts-form-field"><span>First name <b aria-hidden="true">*</b></span><input autoFocus required maxLength={100} value={form.first_name} onChange={(event) => setForm((current) => ({ ...current, first_name: event.target.value }))} placeholder="e.g. Rahul" disabled={saving} /></label>
                  <label className="contacts-form-field"><span>Last name</span><input maxLength={100} value={form.last_name ?? ""} onChange={(event) => setForm((current) => ({ ...current, last_name: event.target.value }))} placeholder="e.g. Sharma" disabled={saving} /></label>
                  <label className="contacts-form-field contacts-form-field-full"><span>Email address</span><input type="email" maxLength={320} value={form.email ?? ""} aria-invalid={Boolean(fieldErrors.email)} aria-describedby={fieldErrors.email ? "contact-email-error" : undefined} onChange={(event) => { setForm((current) => ({ ...current, email: event.target.value })); setFieldErrors((current) => ({ ...current, email: undefined })); setFormError(""); }} placeholder="name@example.com" disabled={saving} />{fieldErrors.email && <span id="contact-email-error" className="contacts-field-error" role="alert">{fieldErrors.email}</span>}</label>
                  <label className="contacts-form-field contacts-form-field-full"><span>Phone number</span><input type="tel" maxLength={50} value={form.phone ?? ""} aria-invalid={Boolean(fieldErrors.phone)} aria-describedby={fieldErrors.phone ? "contact-phone-error" : undefined} onChange={(event) => { setForm((current) => ({ ...current, phone: event.target.value })); setFieldErrors((current) => ({ ...current, phone: undefined })); setFormError(""); }} placeholder="Enter phone number" disabled={saving} />{fieldErrors.phone && <span id="contact-phone-error" className="contacts-field-error" role="alert">{fieldErrors.phone}</span>}</label>
                </div>
                <p className="contacts-required-note"><span aria-hidden="true">*</span> Required field</p>
              </div>
              <footer className="contacts-modal-footer">
                <button className="contacts-secondary-button" type="button" onClick={closeCreateForm} disabled={saving || isFormClosing}>Cancel</button>
                <button className="contacts-primary-button" type="submit" disabled={saving || isFormClosing}>{saving ? "Saving contact…" : editingContact ? "Save changes" : "Save contact"}</button>
              </footer>
            </form>
          </section>
        </div>,
        document.body,
      )}
    </main>
  );
}

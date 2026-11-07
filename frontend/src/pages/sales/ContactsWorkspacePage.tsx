import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import { RecordDetailDialog, RecordProperty } from "../../components/record/RecordDetailDialog";
import { Badge, Button, Dialog, TextField } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { contactsApi, type Contact, type ContactCreateInput, type ContactUpdateInput } from "../../services/contactApi";
import "./sales.css";

const PAGE_SIZE = 100;

const COLUMNS: GridColumnDef[] = [
  { key: "name", label: "Contact", defaultWidth: 260 },
  { key: "email", label: "Email address", defaultWidth: 240 },
  { key: "phone", label: "Phone", defaultWidth: 170 },
  { key: "status", label: "Status", defaultWidth: 120 },
  { key: "created", label: "Created", defaultWidth: 130 },
];

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function contactName(contact: Pick<Contact, "first_name" | "last_name">): string {
  return [contact.first_name, contact.last_name].filter(Boolean).join(" ");
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** Loads every contact by walking the existing paginated list endpoint. */
async function fetchAllContacts(): Promise<Contact[]> {
  const first = await contactsApi.list({ page: 1, page_size: PAGE_SIZE });
  const items = [...first.items];
  for (let page = 2; page <= first.total_pages; page += 1) {
    const next = await contactsApi.list({ page, page_size: PAGE_SIZE });
    items.push(...next.items);
  }
  return items;
}

function messageFrom(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message) return error.message;
  return fallback;
}

interface ContactForm {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
}

const EMPTY_FORM: ContactForm = { first_name: "", last_name: "", email: "", phone: "" };

function toForm(contact: Contact): ContactForm {
  return {
    first_name: contact.first_name,
    last_name: contact.last_name ?? "",
    email: contact.email ?? "",
    phone: contact.phone ?? "",
  };
}

function validate(form: ContactForm): Partial<Record<keyof ContactForm, string>> {
  const errors: Partial<Record<keyof ContactForm, string>> = {};
  if (!form.first_name.trim()) errors.first_name = "First name is required.";
  if (form.email.trim() && !EMAIL_PATTERN.test(form.email.trim())) errors.email = "Enter a complete email, for example name@company.com.";
  return errors;
}

function toPayload(form: ContactForm): ContactCreateInput {
  return {
    first_name: form.first_name.trim(),
    last_name: form.last_name.trim() || null,
    email: form.email.trim() || null,
    phone: form.phone.trim() || null,
  };
}

/**
 * Contacts on the shared EnterpriseDataGrid. The grid, search, column layout and states come from the shared component.
 * Record details and creation use the existing contacts API. Owner and linked records are not part of the contact
 * contract yet, so they are not shown.
 */
export default function ContactsWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Contact | null>(null);
  const [detailForm, setDetailForm] = useState<ContactForm>(EMPTY_FORM);
  const [detailErrors, setDetailErrors] = useState<Partial<Record<keyof ContactForm, string>>>({});
  const [detailSaving, setDetailSaving] = useState(false);
  const [detailMessage, setDetailMessage] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<ContactForm>(EMPTY_FORM);
  const [createErrors, setCreateErrors] = useState<Partial<Record<keyof ContactForm, string>>>({});
  const [createSaving, setCreateSaving] = useState(false);
  const [createMessage, setCreateMessage] = useState("");
  const [notice, setNotice] = useState("");

  // Fetches all contacts. State is only set after the request settles, so the effect below does not update state synchronously.
  const fetchContacts = useCallback(async () => {
    try {
      setContacts(await fetchAllContacts());
      setLoadError("");
      setStatus("ready");
    } catch (error) {
      setLoadError(messageFrom(error, "Check your connection and try again."));
      setStatus("error");
    }
  }, []);

  const load = useCallback(() => {
    setStatus("loading");
    void fetchContacts();
  }, [fetchContacts]);

  // Initial load. State is set only inside the request callbacks, never synchronously in the effect body.
  useEffect(() => {
    let cancelled = false;
    fetchAllContacts()
      .then((items) => {
        if (cancelled) return;
        setContacts(items);
        setLoadError("");
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(messageFrom(error, "Check your connection and try again."));
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visibleContacts = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return contacts;
    return contacts.filter((contact) =>
      [contactName(contact), contact.email ?? "", contact.phone ?? ""].some((value) => value.toLowerCase().includes(needle)),
    );
  }, [contacts, search]);

  const sortValue = useCallback((contact: Contact, key: string): string | number | null => {
    switch (key) {
      case "email":
        return contact.email;
      case "phone":
        return contact.phone;
      case "status":
        return contact.is_active ? "Active" : "Inactive";
      case "created":
        return new Date(contact.created_at).getTime();
      default:
        return contactName(contact);
    }
  }, []);

  const renderCell = useCallback((contact: Contact, key: string) => {
    switch (key) {
      case "email":
        return contact.email ?? "—";
      case "phone":
        return contact.phone ?? "—";
      case "status":
        return <Badge tone={contact.is_active ? "success" : "neutral"}>{contact.is_active ? "Active" : "Inactive"}</Badge>;
      case "created":
        return formatDate(contact.created_at);
      default:
        return <strong className="df-sales-primary">{contactName(contact)}</strong>;
    }
  }, []);

  function openDetail(contact: Contact) {
    setSelected(contact);
    setDetailForm(toForm(contact));
    setDetailErrors({});
    setDetailMessage("");
  }

  async function saveDetail(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const errors = validate(detailForm);
    setDetailErrors(errors);
    if (Object.keys(errors).length > 0) return;
    const payload: ContactUpdateInput = toPayload(detailForm);
    setDetailSaving(true);
    setDetailMessage("");
    try {
      const updated = await contactsApi.update(selected.id, payload);
      setContacts((current) => current.map((contact) => (contact.id === updated.id ? updated : contact)));
      setSelected(updated);
      setDetailForm(toForm(updated));
      setDetailMessage("Changes saved.");
    } catch (error) {
      setDetailMessage(messageFrom(error, "The changes could not be saved. Try again."));
    } finally {
      setDetailSaving(false);
    }
  }

  async function toggleActive() {
    if (!selected) return;
    setDetailSaving(true);
    setDetailMessage("");
    try {
      const updated = await contactsApi.update(selected.id, { is_active: !selected.is_active });
      setContacts((current) => current.map((contact) => (contact.id === updated.id ? updated : contact)));
      setSelected(updated);
      setDetailMessage(updated.is_active ? "Contact reactivated." : "Contact deactivated.");
    } catch (error) {
      setDetailMessage(messageFrom(error, "The status could not be changed. Try again."));
    } finally {
      setDetailSaving(false);
    }
  }

  function openCreate() {
    setCreateForm(EMPTY_FORM);
    setCreateErrors({});
    setCreateMessage("");
    setCreateOpen(true);
  }

  async function saveCreate(event: FormEvent) {
    event.preventDefault();
    const errors = validate(createForm);
    setCreateErrors(errors);
    if (Object.keys(errors).length > 0) return;
    setCreateSaving(true);
    setCreateMessage("");
    try {
      const created = await contactsApi.create(toPayload(createForm));
      setCreateOpen(false);
      setNotice(`${contactName(created)} was added.`);
      load();
    } catch (error) {
      setCreateMessage(messageFrom(error, "The contact could not be created. Try again."));
    } finally {
      setCreateSaving(false);
    }
  }

  const detailDirty = selected ? JSON.stringify(detailForm) !== JSON.stringify(toForm(selected)) : false;

  return (
    <div className="df-sales-page">
      <h1 className="df-visually-hidden">Contacts</h1>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<Contact>
        gridId="contacts"
        ariaLabel="Contacts"
        columns={COLUMNS}
        rows={visibleContacts}
        rowKey={(contact) => contact.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void load()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search contacts"
        searchPlaceholder="Search name, email or phone"
        emptyTitle="Start with your first contact"
        emptyMessage="Add a contact to keep important customer and business details together."
        noMatchTitle="No contacts match this search"
        noMatchMessage="Try another name, email or phone number."
        createLabel="New contact"
        onCreate={openCreate}
        onOpenRow={openDetail}
        totalCount={contacts.length}
        rangeLabel={search ? "Filtered" : "All contacts shown"}
      />

      <RecordDetailDialog
        open={selected !== null}
        onClose={() => setSelected(null)}
        eyebrow="Contact"
        title={selected ? contactName(selected) : ""}
        closeLabel="Close contact"
        main={
          selected ? (
            <form className="df-sales-form" onSubmit={saveDetail} noValidate>
              <div className="df-sales-form-grid">
                <TextField
                  label="First name"
                  required
                  value={detailForm.first_name}
                  error={detailErrors.first_name}
                  onChange={(event) => setDetailForm({ ...detailForm, first_name: event.target.value })}
                />
                <TextField
                  label="Last name"
                  value={detailForm.last_name}
                  onChange={(event) => setDetailForm({ ...detailForm, last_name: event.target.value })}
                />
                <TextField
                  label="Email address"
                  type="email"
                  value={detailForm.email}
                  error={detailErrors.email}
                  onChange={(event) => setDetailForm({ ...detailForm, email: event.target.value })}
                />
                <TextField
                  label="Phone"
                  type="tel"
                  value={detailForm.phone}
                  onChange={(event) => setDetailForm({ ...detailForm, phone: event.target.value })}
                />
              </div>
              <div className="df-sales-form-actions">
                {detailMessage ? (
                  <p className="df-sales-form-message" role="status">
                    {detailMessage}
                  </p>
                ) : null}
                <Button type="submit" variant="primary" disabled={!detailDirty} loading={detailSaving}>
                  Save changes
                </Button>
              </div>
            </form>
          ) : null
        }
        aside={
          selected ? (
            <>
              <dl className="df-sales-properties">
                <RecordProperty label="Status">
                  <Badge tone={selected.is_active ? "success" : "neutral"}>{selected.is_active ? "Active" : "Inactive"}</Badge>
                </RecordProperty>
                <RecordProperty label="Created">{formatDate(selected.created_at)}</RecordProperty>
                <RecordProperty label="Updated">{formatDate(selected.updated_at)}</RecordProperty>
              </dl>
              <Button variant="secondary" size="sm" onClick={() => void toggleActive()} disabled={detailSaving}>
                {selected.is_active ? "Deactivate contact" : "Reactivate contact"}
              </Button>
            </>
          ) : null
        }
      />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New contact" closeLabel="Close new contact">
        <form className="df-sales-form" onSubmit={saveCreate} noValidate>
          <div className="df-sales-form-grid">
            <TextField
              label="First name"
              required
              value={createForm.first_name}
              error={createErrors.first_name}
              onChange={(event) => setCreateForm({ ...createForm, first_name: event.target.value })}
            />
            <TextField
              label="Last name"
              value={createForm.last_name}
              onChange={(event) => setCreateForm({ ...createForm, last_name: event.target.value })}
            />
            <TextField
              label="Email address"
              type="email"
              value={createForm.email}
              error={createErrors.email}
              onChange={(event) => setCreateForm({ ...createForm, email: event.target.value })}
            />
            <TextField
              label="Phone"
              type="tel"
              value={createForm.phone}
              onChange={(event) => setCreateForm({ ...createForm, phone: event.target.value })}
            />
          </div>
          <div className="df-sales-form-actions">
            {createMessage ? (
              <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                {createMessage}
              </p>
            ) : null}
            <Button variant="secondary" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={createSaving}>
              Save contact
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}

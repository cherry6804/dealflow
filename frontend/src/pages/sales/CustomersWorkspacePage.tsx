import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import SiteVisitHistory from "../../components/SiteVisitHistory";
import { RecordDetailDialog, RecordProperty } from "../../components/record/RecordDetailDialog";
import { Badge, Button, Dialog, SelectField, TextField, TextareaField } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { contactsApi, type Contact } from "../../services/contactApi";
import { customerProfilesApi, type CustomerProfile } from "../../services/customerProfileApi";
import "./sales.css";

const PAGE_SIZE = 100;
const NOTES_MAX = 5000;

type StatusFilter = "active" | "inactive";

const COLUMNS: GridColumnDef[] = [
  { key: "customer", label: "Customer", defaultWidth: 260, primary: true },
  { key: "email", label: "Email address", defaultWidth: 240 },
  { key: "phone", label: "Phone", defaultWidth: 170 },
  { key: "status", label: "Status", defaultWidth: 120 },
  { key: "notes", label: "Notes", defaultWidth: 260, defaultVisible: false },
  { key: "registered", label: "Registered", defaultWidth: 130 },
  { key: "updated", label: "Last updated", defaultWidth: 140, defaultVisible: false },
];

function displayName(contact: Pick<Contact, "first_name" | "last_name">): string {
  return [contact.first_name, contact.last_name].filter(Boolean).join(" ").trim();
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function messageFrom(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

/** Walks the existing paginated customer-profile endpoint for one status. */
async function fetchProfiles(isActive: boolean): Promise<CustomerProfile[]> {
  const first = await customerProfilesApi.list({ page: 1, page_size: PAGE_SIZE, is_active: isActive });
  const items = [...first.items];
  for (let page = 2; page <= first.total_pages; page += 1) {
    const next = await customerProfilesApi.list({ page, page_size: PAGE_SIZE, is_active: isActive });
    items.push(...next.items);
  }
  return items;
}

/** Loads every active contact by walking the existing contacts endpoint. */
async function fetchActiveContacts(): Promise<Contact[]> {
  const first = await contactsApi.list({ page: 1, page_size: PAGE_SIZE, is_active: true });
  const items = [...first.items];
  for (let page = 2; page <= first.total_pages; page += 1) {
    const next = await contactsApi.list({ page, page_size: PAGE_SIZE, is_active: true });
    items.push(...next.items);
  }
  return items;
}

async function fetchAllProfiles(): Promise<CustomerProfile[]> {
  const [active, inactive] = await Promise.all([fetchProfiles(true), fetchProfiles(false)]);
  return [...active, ...inactive];
}

/**
 * Customers on the shared EnterpriseDataGrid. A customer is a registered Contact, so the name and contact details come from the
 * contact record. Customer notes, status and the visit history are the profile's own fields and actions. Customer type and
 * owner are not part of the customer-profile contract, so they are not shown.
 */
export default function CustomersWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [profiles, setProfiles] = useState<CustomerProfile[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("active");
  const [notice, setNotice] = useState("");

  const [selected, setSelected] = useState<CustomerProfile | null>(null);
  const [notesDraft, setNotesDraft] = useState("");
  const [detailSaving, setDetailSaving] = useState(false);
  const [detailMessage, setDetailMessage] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);

  const [registerOpen, setRegisterOpen] = useState(false);
  const [registerContacts, setRegisterContacts] = useState<Contact[]>([]);
  const [registerLoading, setRegisterLoading] = useState(false);
  const [registerContactId, setRegisterContactId] = useState("");
  const [registerNotes, setRegisterNotes] = useState("");
  const [registerSaving, setRegisterSaving] = useState(false);
  const [registerError, setRegisterError] = useState("");

  const loadProfiles = useCallback(async () => {
    try {
      setProfiles(await fetchAllProfiles());
      setLoadError("");
      setStatus("ready");
    } catch (error) {
      setLoadError(messageFrom(error, "Check your connection and try again."));
      setStatus("error");
    }
  }, []);

  // Initial load. State is set only inside the request callbacks, never synchronously in the effect body.
  useEffect(() => {
    let cancelled = false;
    fetchAllProfiles()
      .then((items) => {
        if (cancelled) return;
        setProfiles(items);
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

  const statusProfiles = useMemo(
    () => profiles.filter((profile) => profile.is_active === (statusFilter === "active")),
    [profiles, statusFilter],
  );

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return statusProfiles;
    return statusProfiles.filter((profile) =>
      [displayName(profile.contact), profile.contact.email ?? "", profile.contact.phone ?? "", profile.customer_notes ?? ""].some((value) =>
        value.toLowerCase().includes(needle),
      ),
    );
  }, [statusProfiles, search]);

  const sortValue = useCallback((profile: CustomerProfile, key: string): string | number | null => {
    switch (key) {
      case "email":
        return profile.contact.email;
      case "phone":
        return profile.contact.phone;
      case "status":
        return profile.is_active ? "Active" : "Inactive";
      case "notes":
        return profile.customer_notes?.trim() || null;
      case "registered":
        return new Date(profile.created_at).getTime();
      case "updated":
        return new Date(profile.updated_at).getTime();
      default:
        return displayName(profile.contact) || null;
    }
  }, []);

  const renderCell = useCallback((profile: CustomerProfile, key: string) => {
    switch (key) {
      case "email":
        return profile.contact.email ?? "—";
      case "phone":
        return profile.contact.phone ?? "—";
      case "status":
        return <Badge tone={profile.is_active ? "success" : "neutral"}>{profile.is_active ? "Active" : "Inactive"}</Badge>;
      case "notes":
        return profile.customer_notes?.trim() || "—";
      case "registered":
        return formatDate(profile.created_at);
      case "updated":
        return formatDate(profile.updated_at);
      default:
        return <strong className="df-sales-primary">{displayName(profile.contact) || "Unnamed contact"}</strong>;
    }
  }, []);

  function openDetail(profile: CustomerProfile) {
    setSelected(profile);
    setNotesDraft(profile.customer_notes ?? "");
    setDetailMessage("");
    setHistoryOpen(false);
  }

  async function openRegister() {
    setRegisterOpen(true);
    setRegisterContactId("");
    setRegisterNotes("");
    setRegisterError("");
    setRegisterLoading(true);
    try {
      setRegisterContacts(await fetchActiveContacts());
    } catch (error) {
      setRegisterError(messageFrom(error, "Contacts could not be loaded. Try again."));
    } finally {
      setRegisterLoading(false);
    }
  }

  // Only active contacts that are not already registered as customers can be selected.
  const registrableContacts = useMemo(() => {
    const registered = new Set(profiles.map((profile) => profile.contact_id));
    return registerContacts.filter((contact) => !registered.has(contact.id));
  }, [profiles, registerContacts]);

  async function submitRegister(event: FormEvent) {
    event.preventDefault();
    if (!registerContactId) {
      setRegisterError("Select a Contact to register as a customer.");
      return;
    }
    setRegisterSaving(true);
    setRegisterError("");
    try {
      await customerProfilesApi.register({
        contact_id: registerContactId,
        customer_notes: registerNotes.trim() || null,
      });
      setRegisterOpen(false);
      setStatusFilter("active");
      setNotice("Customer registered successfully.");
      await loadProfiles();
    } catch (error) {
      setRegisterError(messageFrom(error, "The customer could not be registered. Try again."));
    } finally {
      setRegisterSaving(false);
    }
  }

  async function saveNotes(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    if (notesDraft.length > NOTES_MAX) {
      setDetailMessage(`Notes can be at most ${NOTES_MAX} characters.`);
      return;
    }
    setDetailSaving(true);
    setDetailMessage("");
    try {
      const updated = await customerProfilesApi.update(selected.id, { customer_notes: notesDraft.trim() || null });
      setProfiles((current) => current.map((profile) => (profile.id === updated.id ? updated : profile)));
      setSelected(updated);
      setNotesDraft(updated.customer_notes ?? "");
      setDetailMessage("Notes saved.");
    } catch (error) {
      setDetailMessage(messageFrom(error, "The notes could not be saved. Try again."));
    } finally {
      setDetailSaving(false);
    }
  }

  async function toggleStatus() {
    if (!selected) return;
    const action = selected.is_active ? "deactivate" : "reactivate";
    const name = displayName(selected.contact) || "this customer";
    if (!window.confirm(`Are you sure you want to ${action} ${name}'s customer profile?`)) return;
    setDetailSaving(true);
    setDetailMessage("");
    try {
      const updated = await customerProfilesApi.update(selected.id, { is_active: !selected.is_active });
      setProfiles((current) => current.map((profile) => (profile.id === updated.id ? updated : profile)));
      setSelected(updated);
      setDetailMessage(updated.is_active ? "Customer profile reactivated." : "Customer profile deactivated.");
    } catch (error) {
      setDetailMessage(messageFrom(error, "The status could not be changed. Try again."));
    } finally {
      setDetailSaving(false);
    }
  }

  const notesDirty = selected ? notesDraft.trim() !== (selected.customer_notes ?? "").trim() : false;
  const selectedName = selected ? displayName(selected.contact) || "Unnamed contact" : "";

  return (
    <div className="df-sales-page">
      <h1 className="df-visually-hidden">Customers</h1>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<CustomerProfile>
        gridId="customers"
        ariaLabel="Customers"
        columns={COLUMNS}
        rows={rows}
        rowKey={(profile) => profile.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void loadProfiles()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search customers"
        searchPlaceholder="Search name, email, phone or notes"
        emptyTitle={statusFilter === "active" ? "No active customers yet" : "No inactive customers"}
        emptyMessage={
          statusFilter === "active"
            ? "Register an existing Contact to create a customer profile."
            : "Deactivated customer profiles appear here."
        }
        noMatchTitle="No customers match this search"
        noMatchMessage="Try another name, email, phone number or note."
        createLabel="Register customer"
        onCreate={() => void openRegister()}
        onOpenRow={openDetail}
        totalCount={statusProfiles.length}
        rangeLabel={search ? "Filtered" : statusFilter === "active" ? "Active customers" : "Inactive customers"}
        toolbarFilters={
          <select
            className="df-input df-sales-status-select"
            aria-label="Customer status"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
          >
            <option value="active">Active customers</option>
            <option value="inactive">Inactive customers</option>
          </select>
        }
      />

      <RecordDetailDialog
        open={selected !== null}
        onClose={() => setSelected(null)}
        eyebrow="Customer"
        title={selectedName}
        closeLabel="Close customer"
        main={
          selected ? (
            <form className="df-sales-form" onSubmit={saveNotes} noValidate>
              <div className="df-sales-form-grid">
                <TextField label="Name" value={selectedName} readOnly helper="Edit the name on the contact record." />
                <TextField label="Email address" type="email" value={selected.contact.email ?? ""} readOnly />
                <TextField label="Phone" type="tel" value={selected.contact.phone ?? ""} readOnly />
                <TextareaField
                  label="Customer notes"
                  rows={4}
                  value={notesDraft}
                  maxLength={NOTES_MAX}
                  helper={`${notesDraft.length}/${NOTES_MAX} characters`}
                  onChange={(event) => setNotesDraft(event.target.value)}
                />
              </div>
              <div className="df-sales-form-actions">
                {detailMessage ? (
                  <p className="df-sales-form-message" role="status">
                    {detailMessage}
                  </p>
                ) : null}
                <Button type="submit" variant="primary" disabled={!notesDirty} loading={detailSaving}>
                  Save notes
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
                <RecordProperty label="Registered">{formatDate(selected.created_at)}</RecordProperty>
                <RecordProperty label="Last updated">{formatDate(selected.updated_at)}</RecordProperty>
              </dl>
              <div className="df-sales-aside-actions">
                <Button variant="secondary" size="sm" onClick={() => setHistoryOpen(true)} disabled={detailSaving}>
                  View visit history
                </Button>
                <Button variant="secondary" size="sm" onClick={() => void toggleStatus()} disabled={detailSaving}>
                  {selected.is_active ? "Deactivate customer" : "Reactivate customer"}
                </Button>
              </div>
            </>
          ) : null
        }
      />

      <Dialog
        open={historyOpen && selected !== null}
        onClose={() => setHistoryOpen(false)}
        title="Visit history"
        closeLabel="Close visit history"
        description={selectedName}
        size="lg"
        footer={
          <Button variant="secondary" onClick={() => setHistoryOpen(false)}>
            Close
          </Button>
        }
      >
        {selected ? <SiteVisitHistory customerProfileId={selected.id} title="Customer site visits" /> : null}
      </Dialog>

      <Dialog
        open={registerOpen}
        onClose={() => setRegisterOpen(false)}
        title="Register a customer"
        closeLabel="Close register customer"
        description="Select an existing Contact to create a customer profile. Only active Contacts that are not already registered can be selected."
      >
        <form className="df-sales-form" onSubmit={submitRegister} noValidate>
          {registerLoading ? (
            <p className="df-sales-form-message" role="status">
              Loading available Contacts…
            </p>
          ) : (
            <div className="df-sales-form-grid">
              <SelectField
                label="Existing Contact"
                required
                value={registerContactId}
                error={registerError && !registerContactId ? registerError : undefined}
                disabled={registerSaving || registrableContacts.length === 0}
                helper={
                  registrableContacts.length === 0
                    ? "All active Contacts are already registered, or there are no active Contacts."
                    : `${registrableContacts.length} available Contact${registrableContacts.length === 1 ? "" : "s"}.`
                }
                options={[
                  { value: "", label: "Select a Contact" },
                  ...registrableContacts.map((contact) => ({
                    value: contact.id,
                    label: [displayName(contact) || "Unnamed contact", contact.email, contact.phone].filter(Boolean).join(" · "),
                  })),
                ]}
                onChange={(event) => setRegisterContactId(event.target.value)}
              />
              <TextareaField
                label="Customer notes"
                rows={4}
                value={registerNotes}
                maxLength={NOTES_MAX}
                disabled={registerSaving}
                helper={`${registerNotes.length}/${NOTES_MAX} characters`}
                onChange={(event) => setRegisterNotes(event.target.value)}
              />
            </div>
          )}
          <div className="df-sales-form-actions">
            {registerError && registerContactId ? (
              <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                {registerError}
              </p>
            ) : null}
            <Button variant="secondary" onClick={() => setRegisterOpen(false)} disabled={registerSaving}>
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={registerSaving}
              disabled={registerLoading || !registerContactId || registrableContacts.length === 0}
            >
              Register customer
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}

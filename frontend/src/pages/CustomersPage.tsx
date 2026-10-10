import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { contactsApi, type Contact } from "../services/contactApi";
import {
  customerProfilesApi,
  type CustomerProfile,
} from "../services/customerProfileApi";
import "./CustomersPage.css";
import { createPortal } from "react-dom";

const PAGE_SIZE = 10;

type StatusFilter = "active" | "inactive";

function displayName(contact: {
  first_name: string;
  last_name: string | null;
}): string {
  return [contact.first_name, contact.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
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

async function getAllProfiles(
  isActive: boolean,
): Promise<CustomerProfile[]> {
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

export default function CustomersPage() {
  const [customers, setCustomers] = useState<CustomerProfile[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] =
    useState<StatusFilter>("active");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [registerOpen, setRegisterOpen] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [registeredContactIds, setRegisteredContactIds] = useState<
    Set<string>
  >(new Set());
  const [contactsLoading, setContactsLoading] = useState(false);
  const [selectedContactId, setSelectedContactId] = useState("");
  const [registrationNotes, setRegistrationNotes] = useState("");

  const [editingCustomer, setEditingCustomer] =
    useState<CustomerProfile | null>(null);
  const [editingNotes, setEditingNotes] = useState("");

  const loadCustomers = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const result = await customerProfilesApi.list({
        page,
        page_size: PAGE_SIZE,
        search,
        is_active: statusFilter === "active",
      });

      setCustomers(result.items);
      setTotal(result.total);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [page, search, statusFilter]);

  useEffect(() => {
    void loadCustomers();
  }, [loadCustomers]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  async function openRegisterDialog() {
    setRegisterOpen(true);
    setSelectedContactId("");
    setRegistrationNotes("");
    setError("");
    setNotice("");
    setContactsLoading(true);

    try {
      const [allContacts, activeProfiles, inactiveProfiles] =
        await Promise.all([
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
      setContacts(
        allContacts.filter((contact) => !existingIds.has(contact.id)),
      );
    } catch (loadError) {
      setError(errorMessage(loadError));
      setRegisterOpen(false);
    } finally {
      setContactsLoading(false);
    }
  }

  async function registerCustomer(event: React.FormEvent<HTMLFormElement>) {
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
      setPage(1);
      setSearch("");
      setSearchInput("");
      setStatusFilter("active");

      // Refresh after the filter and page state have settled.
      await customerProfilesApi.list({
        page: 1,
        page_size: PAGE_SIZE,
        is_active: true,
      }).then((result) => {
        setCustomers(result.items);
        setTotal(result.total);
      });
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  function openEditDialog(customer: CustomerProfile) {
    setEditingCustomer(customer);
    setEditingNotes(customer.customer_notes ?? "");
    setError("");
    setNotice("");
  }

  async function saveCustomerNotes(
    event: React.FormEvent<HTMLFormElement>,
  ) {
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

  function submitSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  }

  function changeStatus(value: StatusFilter) {
    setStatusFilter(value);
    setPage(1);
    setError("");
    setNotice("");
  }

  const registeredContactOptions = contacts.filter(
    (contact) => !registeredContactIds.has(contact.id),
  );

  return (
    <section className="customers-page">
      <header className="customers-header">
        <div>
          <p className="customers-eyebrow">CUSTOMER MANAGEMENT</p>
          <h1>Customers</h1>
          <p className="customers-subtitle">
            Manage customer profiles linked to your existing contacts.
            Register a contact as a customer only when you choose to.
          </p>
        </div>

        <button
          type="button"
          className="customers-button customers-button-primary"
          onClick={() => void openRegisterDialog()}
          disabled={saving}
        >
          <span aria-hidden="true">＋</span> Register customer
        </button>
      </header>

      {error && (
        <div className="customers-alert customers-alert-error" role="alert">
          {error}
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
          {notice}
          <button
            type="button"
            aria-label="Dismiss message"
            onClick={() => setNotice("")}
          >
            ×
          </button>
        </div>
      )}

      <div className="customers-summary">
        <div className="customers-summary-card">
          <span className="customers-summary-label">
            {statusFilter === "active" ? "Active customers" : "Inactive customers"}
          </span>
          <strong>{loading ? "—" : total}</strong>
          <span className="customers-summary-caption">
            {statusFilter === "active"
              ? "Registered and available for new work"
              : "Profiles retained for historical records"}
          </span>
        </div>
        <div className="customers-summary-card">
          <span className="customers-summary-label">Current view</span>
          <strong>{statusFilter === "active" ? "Active" : "Inactive"}</strong>
          <span className="customers-summary-caption">
            Switch status to view the other group
          </span>
        </div>
      </div>

      <div className="customers-list-panel">
        <div className="customers-list-heading">
          <div>
            <h2>Customer directory</h2>
            <p>Customers are profiles registered from existing Contacts.</p>
          </div>

          <label className="customers-status-filter">
            <span>Status</span>
            <select
              value={statusFilter}
              onChange={(event) =>
                changeStatus(event.target.value as StatusFilter)
              }
              disabled={loading || saving}
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </label>
        </div>

        <form className="customers-search-form" onSubmit={submitSearch}>
          <label className="customers-search-field">
            <span className="customers-visually-hidden">
              Search customers
            </span>
            <input
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Search by customer name, email or phone"
            />
          </label>
          <button
            className="customers-button customers-button-secondary"
            type="submit"
            disabled={loading}
          >
            Search
          </button>
          {search && (
            <button
              className="customers-button customers-button-quiet"
              type="button"
              onClick={() => {
                setSearchInput("");
                setSearch("");
                setPage(1);
              }}
            >
              Clear
            </button>
          )}
        </form>

        {loading ? (
          <div className="customers-state">
            <span className="customers-spinner" aria-hidden="true" />
            <p>Loading customer profiles…</p>
          </div>
        ) : customers.length === 0 ? (
          <div className="customers-state">
            <div className="customers-empty-icon" aria-hidden="true">◎</div>
            <h3>
              {search
                ? "No matching customers"
                : statusFilter === "active"
                  ? "No active customers yet"
                  : "No inactive customers"}
            </h3>
            <p>
              {search
                ? "Try a different search term."
                : statusFilter === "active"
                  ? "Register an existing Contact to create a customer profile."
                  : "Deactivated profiles will appear here."}
            </p>
            {!search && statusFilter === "active" && (
              <button
                type="button"
                className="customers-button customers-button-primary"
                onClick={() => void openRegisterDialog()}
              >
                Register your first customer
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="customers-table-wrap">
              <table className="customers-table">
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th>Contact details</th>
                    <th>Registered</th>
                    <th>Status</th>
                    <th className="customers-actions-heading">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {customers.map((customer) => {
                    const name =
                      displayName(customer.contact) || "Unnamed contact";

                    return (
                      <tr key={customer.id}>
                        <td>
                          <div className="customers-person">
                            <span className="customers-avatar" aria-hidden="true">
                              {name.charAt(0).toUpperCase()}
                            </span>
                            <div>
                              <strong>{name}</strong>
                              <small>
                                {customer.customer_notes?.trim()
                                  ? customer.customer_notes
                                  : "No customer notes"}
                              </small>
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="customers-contact-details">
                            <span>{customer.contact.email || "No email"}</span>
                            <span>{customer.contact.phone || "No phone"}</span>
                          </div>
                        </td>
                        <td>{formatDate(customer.created_at)}</td>
                        <td>
                          <span
                            className={
                              customer.is_active
                                ? "customers-status-pill is-active"
                                : "customers-status-pill is-inactive"
                            }
                          >
                            {customer.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td>
                          <div className="customers-row-actions">
                            <button
                              type="button"
                              className="customers-text-button"
                              onClick={() => openEditDialog(customer)}
                              disabled={saving}
                            >
                              Edit notes
                            </button>
                            <button
                              type="button"
                              className={
                                customer.is_active
                                  ? "customers-text-button is-danger"
                                  : "customers-text-button is-positive"
                              }
                              onClick={() => void toggleCustomerStatus(customer)}
                              disabled={saving}
                            >
                              {customer.is_active ? "Deactivate" : "Reactivate"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="customers-pagination">
              <span>
                Showing {(page - 1) * PAGE_SIZE + 1}–
                {Math.min(page * PAGE_SIZE, total)} of {total}
              </span>
              <div>
                <button
                  type="button"
                  className="customers-button customers-button-secondary"
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  disabled={page <= 1 || loading}
                >
                  Previous
                </button>
                <span>
                  Page {page} of {totalPages}
                </span>
                <button
                  type="button"
                  className="customers-button customers-button-secondary"
                  onClick={() =>
                    setPage((current) => Math.min(totalPages, current + 1))
                  }
                  disabled={page >= totalPages || loading}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      
      {registerOpen &&
        createPortal(
          <div
            className="customers-modal-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget && !saving) {
                setRegisterOpen(false);
              }
            }}
          >
            <section
              className="customers-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="customers-register-title"
            >
              <header className="customers-modal-header">
                <div>
                  <p className="customers-eyebrow">CUSTOMER PROFILE</p>
                  <h2 id="customers-register-title">Register a customer</h2>
                  <p>
                    Select an existing Contact. This will not create a new
                    Contact record.
                  </p>
                </div>

                <button
                  type="button"
                  className="customers-modal-close"
                  aria-label="Close dialog"
                  onClick={() => setRegisterOpen(false)}
                  disabled={saving}
                >
                  ×
                </button>
              </header>

              <form
                className="customers-modal-form"
                onSubmit={registerCustomer}
              >
                <div className="customers-modal-body">
                  {contactsLoading ? (
                    <div className="customers-state compact">
                      <span
                        className="customers-spinner"
                        aria-hidden="true"
                      />
                      <p>Loading available Contacts…</p>
                    </div>
                  ) : (
                    <>
                      <label className="customers-form-field">
                        <span>
                          Existing Contact <i>*</i>
                        </span>

                        <select
                          required
                          value={selectedContactId}
                          onChange={(event) =>
                            setSelectedContactId(event.target.value)
                          }
                          disabled={
                            saving ||
                            registeredContactOptions.length === 0
                          }
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
                            : `${registeredContactOptions.length} available Contact${
                                registeredContactOptions.length === 1
                                  ? ""
                                  : "s"
                              }.`}
                        </small>
                      </label>

                      <label className="customers-form-field">
                        <span>Customer notes</span>

                        <textarea
                          rows={4}
                          value={registrationNotes}
                          onChange={(event) =>
                            setRegistrationNotes(event.target.value)
                          }
                          placeholder="Optional notes about this customer"
                          maxLength={5000}
                          disabled={saving}
                        />
                      </label>
                    </>
                  )}
                </div>

                <footer className="customers-modal-footer">
                  <button
                    type="button"
                    className="customers-button customers-button-secondary"
                    onClick={() => setRegisterOpen(false)}
                    disabled={saving}
                  >
                    Cancel
                  </button>

                  <button
                    type="submit"
                    className="customers-button customers-button-primary"
                    disabled={
                      saving ||
                      contactsLoading ||
                      !selectedContactId ||
                      registeredContactOptions.length === 0
                    }
                  >
                    {saving ? "Registering…" : "Register customer"}
                  </button>
                </footer>
              </form>
            </section>
          </div>,
          document.body,
        )}

      {editingCustomer &&
        createPortal(
          <div
            className="customers-modal-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget && !saving) {
                setEditingCustomer(null);
              }
            }}
          >
            <section
              className="customers-modal"
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
                  onClick={() => setEditingCustomer(null)}
                  disabled={saving}
                >
                  ×
                </button>
              </header>

              <form
                className="customers-modal-form"
                onSubmit={saveCustomerNotes}
              >
                <div className="customers-modal-body">
                  <label className="customers-form-field">
                    <span>Customer notes</span>

                    <textarea
                      rows={5}
                      value={editingNotes}
                      onChange={(event) =>
                        setEditingNotes(event.target.value)
                      }
                      placeholder="Add relevant customer notes"
                      maxLength={5000}
                      disabled={saving}
                    />
                  </label>
                </div>

                <footer className="customers-modal-footer">
                  <button
                    type="button"
                    className="customers-button customers-button-secondary"
                    onClick={() => setEditingCustomer(null)}
                    disabled={saving}
                  >
                    Cancel
                  </button>

                  <button
                    type="submit"
                    className="customers-button customers-button-primary"
                    disabled={saving}
                  >
                    {saving ? "Saving…" : "Save notes"}
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

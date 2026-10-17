
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

const STATUS_OPTIONS: { value: ReferralStatus; label: string }[] = [
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

  const modalRef = useRef<HTMLElement>(null);
  const requestSequence = useRef(0);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const firstResult = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastResult = Math.min(page * PAGE_SIZE, total);

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

  return (
    <section className="referrals-page">
      <header className="referrals-header">
        <div>
          <span className="referrals-eyebrow">DEAL WORKSPACE</span>
          <h1>Referrals</h1>
          <p className="referrals-subtitle">
            Track introductions, manage referral sources, and turn
            opportunities into successful deals.
          </p>
        </div>

        <button
          className="referrals-primary-button"
          type="button"
          onClick={openCreateForm}
        >
          <span aria-hidden="true">+</span> Add referral
        </button>
      </header>

      {error && (
        <div className="referrals-alert referrals-alert-error" role="alert">
          <span>{error}</span>
          <button
            type="button"
            className="referrals-dismiss"
            onClick={() => setError("")}
            aria-label="Dismiss error"
          >
            ×
          </button>
        </div>
      )}

      {success && (
        <div
          className="referrals-alert referrals-alert-success"
          role="status"
        >
          <span>{success}</span>
          <button
            type="button"
            className="referrals-dismiss"
            onClick={() => setSuccess("")}
            aria-label="Dismiss success"
          >
            ×
          </button>
        </div>
      )}

      <section className="referrals-summary" aria-label="Referral overview">
        <div className="referrals-summary-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="10" cy="7" r="4" />
            <path d="M20 8v6M17 11h6" />
          </svg>
        </div>
        <div>
          <p className="referrals-summary-label">Total referrals</p>
          <p className="referrals-summary-value">{total}</p>
        </div>
      </section>

      <section className="referrals-panel">
        <header className="referrals-panel-heading">
          <div>
            <h2>Referral records</h2>
            <p>Manage referral details and their linked records.</p>
          </div>
          <button
            type="button"
            className="referrals-secondary-button"
            onClick={() => void loadReferrals()}
            disabled={loading}
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </header>

        <div className="referrals-toolbar">
          <label className="referrals-search">
            <span className="referrals-search-icon" aria-hidden="true">⌕</span>
            <input
              aria-label="Search referrals"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Search by name, email, or phone"
            />
          </label>

          <label className="referrals-filter">
            <span className="referrals-visually-hidden">Filter by status</span>
            <select
              value={statusFilter}
              onChange={(event) => handleStatusChange(event.target.value)}
            >
              <option value="">All statuses</option>
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {loading ? (
          <div className="referrals-state" role="status">
            <span className="referrals-spinner" />
            <p>Loading referrals…</p>
          </div>
        ) : referrals.length === 0 ? (
          <div className="referrals-empty">
            <div className="referrals-empty-icon" aria-hidden="true">↗</div>
            <h3>No referrals found</h3>
            <p>
              {search || statusFilter
                ? "Try a different search term or status filter."
                : "Add your first referral to start tracking introductions."}
            </p>
            {!search && !statusFilter && (
              <button
                className="referrals-primary-button"
                type="button"
                onClick={openCreateForm}
              >
                Add your first referral
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="referrals-table-wrapper">
              <table className="referrals-table">
                <thead>
                  <tr>
                    <th>Referral</th>
                    <th>Contact details</th>
                    <th>Associations</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {referrals.map((referral) => {
                    const associations = getAssociationLabels(
                      referral,
                      customers,
                      contacts,
                      deals,
                    );

                    return (
                      <tr key={referral.id}>
                        <td>
                          <div className="referrals-person">
                            <span className="referrals-avatar" aria-hidden="true">
                              {referral.referral_name.trim().charAt(0).toUpperCase()}
                            </span>
                            <div>
                              <strong>{referral.referral_name}</strong>
                              <span className="referrals-secondary-text">
                                #{referral.id.slice(0, 8)}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="referrals-contact-details">
                            <span>{referral.referral_email || "No email"}</span>
                            <span>{referral.referral_phone || "No phone"}</span>
                          </div>
                        </td>
                        <td>
                          <div className="referrals-associations">
                            {associations.length > 0
                              ? associations.map((label) => (
                                  <span key={label}>{label}</span>
                                ))
                              : <span>—</span>}
                          </div>
                        </td>
                        <td>
                          <span className={getStatusClass(referral.status)}>
                            {formatStatus(referral.status)}
                          </span>
                        </td>
                        <td>{formatDate(referral.created_at)}</td>
                        <td>
                          <div className="referrals-row-actions">
                            <button
                              type="button"
                              className="referrals-text-button"
                              onClick={() => openEditForm(referral)}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className="referrals-text-button referrals-danger-button"
                              onClick={() => void handleDeactivate(referral)}
                            >
                              Deactivate
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="referrals-mobile-list">
              {referrals.map((referral) => (
                <article className="referrals-mobile-card" key={referral.id}>
                  <div className="referrals-mobile-card-heading">
                    <div className="referrals-person">
                      <span className="referrals-avatar" aria-hidden="true">
                        {referral.referral_name.trim().charAt(0).toUpperCase()}
                      </span>
                      <div>
                        <strong>{referral.referral_name}</strong>
                        <span className="referrals-secondary-text">
                          {formatDate(referral.created_at)}
                        </span>
                      </div>
                    </div>
                    <span className={getStatusClass(referral.status)}>
                      {formatStatus(referral.status)}
                    </span>
                  </div>

                  <p>{referral.referral_email || "No email"}</p>
                  <p>{referral.referral_phone || "No phone"}</p>

                  <div className="referrals-row-actions">
                    <button
                      type="button"
                      className="referrals-text-button"
                      onClick={() => openEditForm(referral)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="referrals-text-button referrals-danger-button"
                      onClick={() => void handleDeactivate(referral)}
                    >
                      Deactivate
                    </button>
                  </div>
                </article>
              ))}
            </div>

            <footer className="referrals-pagination">
              <p>
                Showing {firstResult}–{lastResult} of {total}
              </p>
              <div className="referrals-pagination-controls">
                <button
                  type="button"
                  className="referrals-page-button"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => current - 1)}
                >
                  Previous
                </button>
                <span>Page {page} of {totalPages}</span>
                <button
                  type="button"
                  className="referrals-page-button"
                  disabled={page >= totalPages}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </button>
              </div>
            </footer>
          </>
        )}
      </section>

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
                  {editingReferral ? "UPDATE RECORD" : "NEW RECORD"}
                </span>
                <h2 id="referrals-form-title">
                  {editingReferral ? "Edit referral" : "Add referral"}
                </h2>
                <p>
                  Capture referral details and connect the relevant records.
                </p>
              </div>
              <button
                type="button"
                className="referrals-modal-close"
                aria-label="Close form"
                onClick={closeForm}
                disabled={saving}
              >
                ×
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
                  Cancel
                </button>
                <button
                  type="submit"
                  className="referrals-primary-button"
                  disabled={saving || lookupsLoading}
                >
                  {saving
                    ? "Saving…"
                    : editingReferral
                      ? "Save changes"
                      : "Create referral"}
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

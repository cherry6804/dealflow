import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";

import { ApiError } from "../lib/api";
import {
  contactsApi,
  type Contact,
  type ContactCreateInput,
} from "../services/contactApi";

import "./ContactsPage.css";

const PAGE_SIZE = 10;
const MODAL_EXIT_DURATION = 240;

const EMPTY_FORM: ContactCreateInput = {
  first_name: "",
  last_name: "",
  email: "",
  phone: "",
};

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
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

function ContactsIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="10" cy="7" r="4" />
      <path d="M20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </svg>
  );
}

function EmptyContactsIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20v-1.5A5.5 5.5 0 0 1 8 13h2a5.5 5.5 0 0 1 5.5 5.5V20" />
      <path d="M19 8v6M16 11h6" />
    </svg>
  );
}

export default function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isFormClosing, setIsFormClosing] = useState(false);
  const [form, setForm] = useState<ContactCreateInput>(EMPTY_FORM);
  const [formError, setFormError] = useState("");

  const modalRef = useRef<HTMLElement>(null);
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  const loadContacts = useCallback(async () => {
    try {
      const result = await contactsApi.list({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
      });

      setContacts(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
      setError("");
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [page, search]);

  useEffect(() => {
    let cancelled = false;

    async function fetchContacts() {
      try {
        const result = await contactsApi.list({
          page,
          page_size: PAGE_SIZE,
          search: search || undefined,
        });

        if (cancelled) return;

        setContacts(result.items);
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

    void fetchContacts();

    return () => {
      cancelled = true;
    };
  }, [page, search]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const nextSearch = searchInput.trim();

      if (nextSearch !== search) {
        setLoading(true);
        setPage(1);
        setSearch(nextSearch);
      }
    }, 300);

    return () => {
      window.clearTimeout(timer);
    };
  }, [searchInput, search]);

  useEffect(() => {
    if (!isFormOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusTimer = window.setTimeout(() => {
      const firstInput =
        modalRef.current?.querySelector<HTMLInputElement>(
          'input:not([type="hidden"])',
        );

      firstInput?.focus();
    }, 50);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) {
        closeCreateForm();
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", handleKeyDown);
    };
    // The modal installs keyboard handling while it is open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isFormOpen, saving]);

  useEffect(() => {
    return () => {
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
      }
    };
  }, []);

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setSuccess("");
    setLoading(true);
    setPage(1);
    setSearch(searchInput.trim());
  }

  function openCreateForm() {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }

    setForm(EMPTY_FORM);
    setFormError("");
    setSuccess("");
    setIsFormClosing(false);
    setIsFormOpen(true);
  }

  function closeCreateForm() {
    if (saving || isFormClosing || !isFormOpen) return;

    setFormError("");
    setIsFormClosing(true);

    closeTimerRef.current = window.setTimeout(() => {
      setIsFormOpen(false);
      setIsFormClosing(false);
      closeTimerRef.current = null;
    }, MODAL_EXIT_DURATION);
  }

  async function handleCreateContact(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    setFormError("");
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
      await contactsApi.create(payload);

      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }

      setIsFormOpen(false);
      setIsFormClosing(false);
      setForm(EMPTY_FORM);
      setFormError("");
      setSearchInput("");
      setSearch("");
      setPage(1);
      setLoading(true);
      setSuccess("Contact created successfully.");

      const result = await contactsApi.list({
        page: 1,
        page_size: PAGE_SIZE,
      });

      setContacts(result.items);
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

  const firstResult = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastResult = Math.min(page * PAGE_SIZE, total);

  return (
    <section className="contacts-page">
      <header className="contacts-header">
        <div>
          <span className="contacts-eyebrow">YOUR WORKSPACE</span>
          <h1>Contacts</h1>
          <p className="contacts-subtitle">
            Build and manage your real-estate relationships in one place.
          </p>
        </div>

        <button
          className="contacts-primary-button"
          type="button"
          onClick={openCreateForm}
        >
          <span aria-hidden="true">+</span> Add contact
        </button>
      </header>

      <section className="contacts-summary" aria-label="Contact overview">
        <div className="contacts-summary-icon" aria-hidden="true">
          <ContactsIcon />
        </div>

        <div>
          <p className="contacts-summary-label">Total contacts</p>
          <p className="contacts-summary-value">
            {loading && total === 0 ? "—" : total.toLocaleString("en-IN")}
          </p>
        </div>
      </section>

      {success && (
        <div
          className="contacts-alert contacts-alert-success"
          role="status"
        >
          <span>{success}</span>
          <button
            type="button"
            className="contacts-alert-dismiss"
            onClick={() => setSuccess("")}
            aria-label="Dismiss success message"
          >
            ×
          </button>
        </div>
      )}

      <section className="contacts-list-panel">
        <div className="contacts-list-heading">
          <div>
            <h2>All contacts</h2>
            <p>Keep your client and business contact details organized.</p>
          </div>
        </div>

        <form className="contacts-search-form" onSubmit={handleSearch}>
          <label className="contacts-search-field">
            <span className="contacts-search-icon" aria-hidden="true">
              <SearchIcon />
            </span>

            <span className="contacts-visually-hidden">
              Search contacts
            </span>

            <input
              type="search"
              placeholder="Search by name, email or phone..."
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              maxLength={320}
            />
          </label>

          <button className="contacts-secondary-button" type="submit">
            Search
          </button>

          {search && (
            <button
              className="contacts-text-button"
              type="button"
              onClick={() => {
                setSearchInput("");
                setSearch("");
                setPage(1);
                setLoading(true);
              }}
            >
              Clear
            </button>
          )}
        </form>

        {error && (
          <div className="contacts-alert contacts-alert-error" role="alert">
            <div>
              <strong>Couldn't load contacts</strong>
              <p>{error}</p>
            </div>

            <button
              className="contacts-secondary-button"
              type="button"
              onClick={() => {
                setLoading(true);
                setError("");
                void loadContacts();
              }}
            >
              Retry
            </button>
          </div>
        )}

        {loading ? (
          <div className="contacts-state" role="status" aria-live="polite">
            <span className="contacts-spinner" aria-hidden="true" />
            <p>Loading contacts...</p>
          </div>
        ) : !error && contacts.length === 0 ? (
          <div className="contacts-empty-state">
            <div className="contacts-empty-icon" aria-hidden="true">
              <EmptyContactsIcon />
            </div>

            <h3>
              {search ? "No matching contacts" : "Your contacts start here"}
            </h3>

            <p>
              {search
                ? "Try a different search term or clear your search."
                : "Add your first contact to start organizing your real-estate relationships."}
            </p>

            {search ? (
              <button
                className="contacts-secondary-button"
                type="button"
                onClick={() => {
                  setSearchInput("");
                  setSearch("");
                  setPage(1);
                  setLoading(true);
                }}
              >
                Clear search
              </button>
            ) : (
              <button
                className="contacts-primary-button"
                type="button"
                onClick={openCreateForm}
              >
                + Add your first contact
              </button>
            )}
          </div>
        ) : !error ? (
          <>
            <div className="contacts-table-wrapper">
              <table className="contacts-table">
                <thead>
                  <tr>
                    <th scope="col">Contact</th>
                    <th scope="col">Email</th>
                    <th scope="col">Phone</th>
                    <th scope="col">Date added</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>

                <tbody>
                  {contacts.map((contact) => {
                    const fullName = [
                      contact.first_name,
                      contact.last_name,
                    ]
                      .filter(Boolean)
                      .join(" ");

                    return (
                      <tr key={contact.id}>
                        <td>
                          <div className="contacts-person">
                            <span
                              className="contacts-avatar"
                              aria-hidden="true"
                            >
                              {contact.first_name.charAt(0).toUpperCase()}
                              {contact.last_name?.charAt(0).toUpperCase() ??
                                ""}
                            </span>

                            <span className="contacts-person-name">
                              {fullName}
                            </span>
                          </div>
                        </td>

                        <td>{contact.email || "—"}</td>
                        <td>{contact.phone || "—"}</td>
                        <td>{formatDate(contact.created_at)}</td>

                        <td>
                          <span
                            className={`contacts-status ${
                              contact.is_active
                                ? "contacts-status-active"
                                : "contacts-status-inactive"
                            }`}
                          >
                            <span aria-hidden="true" />
                            {contact.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <footer className="contacts-pagination">
              <p>
                Showing <strong>{firstResult}–{lastResult}</strong> of{" "}
                <strong>{total}</strong> contacts
              </p>

              <div className="contacts-pagination-controls">
                <button
                  className="contacts-page-button"
                  type="button"
                  disabled={page <= 1 || loading}
                  onClick={() => {
                    setLoading(true);
                    setPage((current) => current - 1);
                  }}
                >
                  Previous
                </button>

                <span>
                  Page {page}
                  {totalPages > 0 ? ` of ${totalPages}` : ""}
                </span>

                <button
                  className="contacts-page-button"
                  type="button"
                  disabled={page >= totalPages || loading || totalPages === 0}
                  onClick={() => {
                    setLoading(true);
                    setPage((current) => current + 1);
                  }}
                >
                  Next
                </button>
              </div>
            </footer>
          </>
        ) : null}
      </section>

      {isFormOpen &&
  createPortal(
    <div
      className={`contacts-modal-backdrop ${
        isFormClosing ? "is-closing" : ""
      }`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          closeCreateForm();
        }
      }}
      onAnimationEnd={(event) => {
        if (
          event.target === event.currentTarget &&
          event.animationName === "contacts-backdrop-out" &&
          isFormClosing
        ) {
          if (closeTimerRef.current !== null) {
            window.clearTimeout(closeTimerRef.current);
            closeTimerRef.current = null;
          }

          setIsFormOpen(false);
          setIsFormClosing(false);
        }
      }}
    >
      <section
        ref={modalRef}
        className={`contacts-modal ${
          isFormClosing ? "is-closing" : ""
        }`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="contacts-modal-title"
      >
        <header className="contacts-modal-header">
          <div>
            <span className="contacts-eyebrow">CONTACT DETAILS</span>
            <h2 id="contacts-modal-title">Add a contact</h2>
            <p>Enter the details of your new contact.</p>
          </div>

          <button
            type="button"
            className="contacts-modal-close"
            onClick={closeCreateForm}
            disabled={saving || isFormClosing}
            aria-label="Close form"
          >
            ×
          </button>
        </header>

        <form
          className="contacts-form"
          onSubmit={handleCreateContact}
        >
          <div className="contacts-form-body">
            {formError && (
              <div
                className="contacts-alert contacts-alert-error"
                role="alert"
              >
                {formError}
              </div>
            )}

            <div className="contacts-form-grid">
              <label className="contacts-form-field">
                <span>
                  First name <span aria-hidden="true">*</span>
                </span>

                <input
                  autoFocus
                  required
                  maxLength={100}
                  value={form.first_name}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      first_name: event.target.value,
                    }))
                  }
                  placeholder="e.g. Rahul"
                  disabled={saving}
                />
              </label>

              <label className="contacts-form-field">
                <span>Last name</span>

                <input
                  maxLength={100}
                  value={form.last_name ?? ""}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      last_name: event.target.value,
                    }))
                  }
                  placeholder="e.g. Sharma"
                  disabled={saving}
                />
              </label>

              <label className="contacts-form-field contacts-form-field-full">
                <span>Email address</span>

                <input
                  type="email"
                  maxLength={320}
                  value={form.email ?? ""}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      email: event.target.value,
                    }))
                  }
                  placeholder="name@example.com"
                  disabled={saving}
                />
              </label>

              <label className="contacts-form-field contacts-form-field-full">
                <span>Phone number</span>

                <input
                  type="tel"
                  maxLength={50}
                  value={form.phone ?? ""}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      phone: event.target.value,
                    }))
                  }
                  placeholder="Enter phone number"
                  disabled={saving}
                />
              </label>
            </div>

            <p className="contacts-required-note">
              <span aria-hidden="true">*</span> Required field
            </p>
          </div>

          <footer className="contacts-form-actions">
            <button
              className="contacts-secondary-button"
              type="button"
              onClick={closeCreateForm}
              disabled={saving || isFormClosing}
            >
              Cancel
            </button>

            <button
              className="contacts-primary-button"
              type="submit"
              disabled={saving || isFormClosing}
            >
              {saving ? "Saving..." : "Save contact"}
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
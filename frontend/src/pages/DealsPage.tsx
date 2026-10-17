
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";

import { ApiError } from "../lib/api";
import {
  customerProfilesApi,
  type CustomerProfile,
} from "../services/customerProfileApi";
import {
  dealsApi,
  type Deal,
  type DealStage,
} from "../services/dealApi";
import {
  propertiesApi,
  type Property,
} from "../services/propertyApi";

import "./DealsPage.css";

const PAGE_SIZE = 10;

const DEAL_STAGES: DealStage[] = [
  "NEW",
  "QUALIFICATION",
  "NEGOTIATION",
  "BOOKING",
  "CLOSED_WON",
  "CLOSED_LOST",
];

interface DealForm {
  customer_profile_id: string;
  property_id: string;
  stage: DealStage;
  expected_value: string;
  currency: string;
  notes: string;
}

const EMPTY_FORM: DealForm = {
  customer_profile_id: "",
  property_id: "",
  stage: "NEW",
  expected_value: "",
  currency: "INR",
  notes: "",
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : error instanceof Error
      ? error.message
      : "Something went wrong. Please try again.";
}

function label(value: string): string {
  return value
    .split("_")
    .map(
      (part) =>
        part.charAt(0) + part.slice(1).toLowerCase(),
    )
    .join(" ");
}

function amount(
  value: number | string | null,
  currency = "INR",
): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  const numericValue = Number(value);

  if (!Number.isFinite(numericValue)) return "—";

  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(numericValue);
  } catch {
    return `${currency} ${numericValue.toLocaleString("en-IN")}`;
  }
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

function customerName(customer?: CustomerProfile): string {
  if (!customer?.contact) return "Customer";

  return [
    customer.contact.first_name,
    customer.contact.last_name,
  ]
    .filter(Boolean)
    .join(" ") || "Unnamed customer";
}

function propertyAddress(property?: Property): string {
  if (!property) return "Property details unavailable";

  return [
    property.address_line_1,
    property.locality,
    property.city,
  ]
    .filter(Boolean)
    .join(", ") || "Address not provided";
}

function propertyTitle(property?: Property): string {
  if (!property) return "Property";

  const type = property.property_type
    ? label(property.property_type)
    : "Property";

  return property.bhk
    ? `${property.bhk} BHK ${type}`
    : type;
}

function stageClass(stage: string): string {
  return `deals-stage deals-stage-${stage.toLowerCase()}`;
}

export default function DealsPage() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [customers, setCustomers] = useState<CustomerProfile[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState("");

  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [supportDataLoading, setSupportDataLoading] = useState(true);

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [formError, setFormError] = useState("");

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [form, setForm] = useState<DealForm>(EMPTY_FORM);

  const modalRef = useRef<HTMLElement>(null);

  const customerById = useMemo(
    () =>
      new Map(
        customers.map((customer) => [customer.id, customer]),
      ),
    [customers],
  );

  const propertyById = useMemo(
    () =>
      new Map(
        properties.map((property) => [property.id, property]),
      ),
    [properties],
  );

  const loadDeals = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const result = await dealsApi.list({
        page,
        page_size: PAGE_SIZE,
        stage: stageFilter
          ? (stageFilter as DealStage)
          : undefined,
      });

      setDeals(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [page, stageFilter]);

  const loadSelectorData = useCallback(async () => {
    setSupportDataLoading(true);

    try {
      const [customerResult, propertyResult] = await Promise.all([
        customerProfilesApi.list({
          page: 1,
          page_size: 100,
          is_active: true,
        }),
        propertiesApi.search({
          page: 1,
          page_size: 100,
          status: "AVAILABLE",
        }),
      ]);

      setCustomers(customerResult.items);
      setProperties(propertyResult.items);
    } catch (loadError) {
      setFormError(errorMessage(loadError));
    } finally {
      setSupportDataLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDeals();
  }, [loadDeals]);

  useEffect(() => {
    let cancelled = false;

    async function fetchSelectorData() {
      setSupportDataLoading(true);

      try {
        const [customerResult, propertyResult] = await Promise.all([
          customerProfilesApi.list({
            page: 1,
            page_size: 100,
            is_active: true,
          }),
          propertiesApi.search({
            page: 1,
            page_size: 100,
            status: "AVAILABLE",
          }),
        ]);

        if (cancelled) return;

        setCustomers(customerResult.items);
        setProperties(propertyResult.items);
      } catch {
        if (!cancelled) {
          setCustomers([]);
          setProperties([]);
        }
      } finally {
        if (!cancelled) setSupportDataLoading(false);
      }
    }

    void fetchSelectorData();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = searchInput.trim();

      if (next !== search) {
        setPage(1);
        setSearch(next);
      }
    }, 300);

    return () => window.clearTimeout(timer);
  }, [searchInput, search]);

  useEffect(() => {
    setPage(1);
  }, [stageFilter]);

  useEffect(() => {
    if (!isFormOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const timer = window.setTimeout(() => {
      modalRef.current
        ?.querySelector<HTMLInputElement | HTMLSelectElement>(
          "input, select",
        )
        ?.focus();
    }, 50);

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) {
        setIsFormOpen(false);
        setFormError("");
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(timer);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isFormOpen, saving]);

  function openCreateForm() {
    setForm(EMPTY_FORM);
    setFormError("");
    setSuccess("");
    setIsFormOpen(true);

    if (customers.length === 0 || properties.length === 0) {
      void loadSelectorData();
    }
  }

  function updateForm<K extends keyof DealForm>(
    key: K,
    value: DealForm[K],
  ) {
    setForm((current) => ({
      ...current,
      [key]: value,
    }));
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setSuccess("");

    if (!form.customer_profile_id) {
      setFormError("Select a customer.");
      return;
    }

    if (!form.property_id) {
      setFormError("Select an available property.");
      return;
    }

    const expectedValue = form.expected_value.trim()
      ? Number(form.expected_value)
      : null;

    if (
      expectedValue !== null &&
      (!Number.isFinite(expectedValue) || expectedValue < 0)
    ) {
      setFormError(
        "Expected value must be a valid non-negative number.",
      );
      return;
    }

    if (!/^[A-Z]{3}$/.test(form.currency.trim().toUpperCase())) {
      setFormError("Enter a valid three-letter currency code.");
      return;
    }

    setSaving(true);

    try {
      await dealsApi.create({
        customer_profile_id: form.customer_profile_id,
        property_id: form.property_id,
        stage: form.stage,
        expected_value: expectedValue,
        currency: form.currency.trim().toUpperCase(),
        notes: form.notes.trim() || null,
      });

      setIsFormOpen(false);
      setForm(EMPTY_FORM);
      setPage(1);
      setSearch("");
      setSearchInput("");
      setStageFilter("");
      setSuccess("Deal created successfully.");

      // Reload the first page so the new deal is visible.
      const result = await dealsApi.list({
        page: 1,
        page_size: PAGE_SIZE,
      });

      setDeals(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
      setError("");
    } catch (createError) {
      setFormError(errorMessage(createError));
    } finally {
      setSaving(false);
      setLoading(false);
    }
  }

  const filteredDeals = useMemo(() => {
    const term = search.toLowerCase();

    if (!term) return deals;

    return deals.filter((deal) => {
      const customer = customerName(
        customerById.get(deal.customer_profile_id),
      ).toLowerCase();

      const property = propertyAddress(
        propertyById.get(deal.property_id),
      ).toLowerCase();

      return (
        customer.includes(term) ||
        property.includes(term) ||
        deal.id.toLowerCase().includes(term) ||
        deal.stage.toLowerCase().includes(term)
      );
    });
  }, [deals, search, customerById, propertyById]);

  const stageCounts = useMemo(() => {
    const counts: Record<string, number> = {};

    DEAL_STAGES.forEach((stage) => {
      counts[stage] = 0;
    });

    deals.forEach((deal) => {
      counts[deal.stage] = (counts[deal.stage] ?? 0) + 1;
    });

    return counts;
  }, [deals]);

  const visibleValue = useMemo(
    () =>
      deals.reduce(
        (sum, deal) => sum + (Number(deal.expected_value) || 0),
        0,
      ),
    [deals],
  );

  const firstResult = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastResult = Math.min(page * PAGE_SIZE, total);

  return (
    <section className="deals-page">
      <header className="deals-header">
        <div>
          <span className="deals-eyebrow">SALES WORKSPACE</span>
          <h1>Deals</h1>
          <p className="deals-subtitle">
            Track opportunities from qualification through closing.
          </p>
        </div>

        <button
          className="deals-primary-button"
          type="button"
          onClick={openCreateForm}
        >
          <span aria-hidden="true">+</span> New deal
        </button>
      </header>

      {success && (
        <div className="deals-alert deals-alert-success" role="status">
          <span>{success}</span>
          <button
            type="button"
            className="deals-dismiss"
            aria-label="Dismiss success message"
            onClick={() => setSuccess("")}
          >
            ×
          </button>
        </div>
      )}

      <section className="deals-summary" aria-label="Deal summary">
        <div className="deals-summary-icon" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M3 17l6-6 4 4 8-9" />
            <path d="M15 6h6v6" />
          </svg>
        </div>

        <div>
          <p className="deals-summary-label">Matching deals</p>
          <p className="deals-summary-value">
            {loading && total === 0 ? "—" : total.toLocaleString("en-IN")}
          </p>
        </div>

        <div className="deals-summary-divider" />

        <div className="deals-summary-metric">
          <span>Visible pipeline value</span>
          <strong>{amount(visibleValue)}</strong>
          <small>Current page only</small>
        </div>
      </section>

      <section className="deals-panel">
        <header className="deals-panel-heading">
          <div>
            <h2>Deal pipeline</h2>
            <p>Review opportunities and their current stage.</p>
          </div>

          <button
            className="deals-secondary-button"
            type="button"
            disabled={loading}
            onClick={() => void loadDeals()}
          >
            {loading ? "Refreshing..." : "↻ Refresh"}
          </button>
        </header>

        <div className="deals-stage-strip">
          {DEAL_STAGES.map((stage) => (
            <button
              type="button"
              key={stage}
              className={`deals-stage-card ${
                stageFilter === stage ? "selected" : ""
              }`}
              onClick={() => {
                setStageFilter((current) =>
                  current === stage ? "" : stage,
                );
                setPage(1);
              }}
            >
              <span>{label(stage)}</span>
              <strong>{stageCounts[stage] ?? 0}</strong>
            </button>
          ))}
        </div>

        <div className="deals-toolbar">
          <label className="deals-search">
            <span aria-hidden="true" className="deals-search-icon">⌕</span>
            <span className="deals-visually-hidden">Search deals</span>
            <input
              type="search"
              maxLength={320}
              value={searchInput}
              placeholder="Search customer, property, or deal..."
              onChange={(event) => {
                setSearchInput(event.target.value);
                setPage(1);
              }}
            />
          </label>

          <label className="deals-filter">
            <span className="deals-visually-hidden">Filter by stage</span>
            <select
              value={stageFilter}
              onChange={(event) => {
                setStageFilter(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All stages</option>
              {DEAL_STAGES.map((stage) => (
                <option value={stage} key={stage}>
                  {label(stage)}
                </option>
              ))}
            </select>
          </label>
        </div>

        {error && (
          <div className="deals-alert deals-alert-error" role="alert">
            <div>
              <strong>Couldn't load deals</strong>
              <p>{error}</p>
            </div>
            <button
              className="deals-secondary-button"
              type="button"
              onClick={() => void loadDeals()}
            >
              Retry
            </button>
          </div>
        )}

        {loading ? (
          <div className="deals-state" role="status" aria-live="polite">
            <span className="deals-spinner" aria-hidden="true" />
            <p>Loading deals...</p>
          </div>
        ) : !error && filteredDeals.length === 0 ? (
          <div className="deals-empty">
            <div className="deals-empty-icon" aria-hidden="true">◇</div>
            <h3>
              {search || stageFilter
                ? "No matching deals"
                : "Your deal pipeline starts here"}
            </h3>
            <p>
              {search || stageFilter
                ? "Try changing your search or stage filter."
                : "Create your first deal to start tracking a real estate opportunity."}
            </p>
            {search || stageFilter ? (
              <button
                className="deals-secondary-button"
                type="button"
                onClick={() => {
                  setSearch("");
                  setSearchInput("");
                  setStageFilter("");
                  setPage(1);
                }}
              >
                Clear filters
              </button>
            ) : (
              <button
                className="deals-primary-button"
                type="button"
                onClick={openCreateForm}
              >
                + Create your first deal
              </button>
            )}
          </div>
        ) : !error ? (
          <>
            <div className="deals-table-wrapper">
              <table className="deals-table">
                <thead>
                  <tr>
                    <th scope="col">Customer / property</th>
                    <th scope="col">Stage</th>
                    <th scope="col">Expected value</th>
                    <th scope="col">Owner</th>
                    <th scope="col">Created</th>
                  </tr>
                </thead>

                <tbody>
                  {filteredDeals.map((deal) => (
                    <tr key={deal.id}>
                      <td>
                        <div className="deals-name">
                          {customerName(
                            customerById.get(deal.customer_profile_id),
                          )}
                        </div>
                        <div className="deals-secondary-text">
                          {propertyAddress(
                            propertyById.get(deal.property_id),
                          )}
                        </div>
                      </td>
                      <td>
                        <span className={stageClass(deal.stage)}>
                          {label(deal.stage)}
                        </span>
                      </td>
                      <td className="deals-value">
                        {amount(deal.expected_value, deal.currency || "INR")}
                      </td>
                      <td>
                        <span className="deals-owner-name">
                            {deal.owner_name || "Unknown owner"}
                        </span>
                        </td>
                      <td>
                        {formatDate(deal.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="deals-mobile-list">
              {filteredDeals.map((deal) => (
                <article className="deals-mobile-card" key={deal.id}>
                  <div className="deals-mobile-top">
                    <span className={stageClass(deal.stage)}>
                      {label(deal.stage)}
                    </span>
                    <strong>
                      {amount(deal.expected_value, deal.currency || "INR")}
                    </strong>
                  </div>
                  <h3>
                    {customerName(
                      customerById.get(deal.customer_profile_id),
                    )}
                  </h3>
                  <p>
                    {propertyAddress(propertyById.get(deal.property_id))}
                  </p>
                  <footer>
                    <span>{formatDate(deal.created_at)}</span>
                    <span>
                      Owner{" "}
                      {deal.owner_user_id
                        ? `${deal.owner_user_id.slice(0, 8)}…`
                        : "—"}
                    </span>
                  </footer>
                </article>
              ))}
            </div>

            <footer className="deals-pagination">
              <p>
                Showing <strong>{firstResult}–{lastResult}</strong> of{" "}
                <strong>{total}</strong> deals
              </p>

              <div className="deals-pagination-controls">
                <button
                  className="deals-page-button"
                  type="button"
                  disabled={page <= 1 || loading}
                  onClick={() => setPage((current) => current - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {page}{totalPages > 0 ? ` of ${totalPages}` : ""}
                </span>
                <button
                  className="deals-page-button"
                  type="button"
                  disabled={
                    page >= totalPages || totalPages === 0 || loading
                  }
                  onClick={() => setPage((current) => current + 1)}
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
            className="deals-modal-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (
                event.target === event.currentTarget &&
                !saving
              ) {
                setIsFormOpen(false);
                setFormError("");
              }
            }}
          >
            <section
              ref={modalRef}
              className="deals-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="deals-modal-title"
            >
              <header className="deals-modal-header">
                <div>
                  <span className="deals-eyebrow">DEAL DETAILS</span>
                  <h2 id="deals-modal-title">Create a deal</h2>
                  <p>
                    Link a customer to a property and define the opportunity.
                  </p>
                </div>

                <button
                  className="deals-modal-close"
                  type="button"
                  aria-label="Close form"
                  disabled={saving}
                  onClick={() => {
                    setIsFormOpen(false);
                    setFormError("");
                  }}
                >
                  ×
                </button>
              </header>

              <form className="deals-form" onSubmit={handleCreate}>
                <div className="deals-form-body">
                  {formError && (
                    <div
                      className="deals-alert deals-alert-error deals-form-error"
                      role="alert"
                    >
                      <p>{formError}</p>
                    </div>
                  )}

                  {supportDataLoading ? (
                    <div className="deals-state" role="status">
                      <span className="deals-spinner" aria-hidden="true" />
                      <p>Loading customers and available properties...</p>
                    </div>
                  ) : (
                    <>
                      <h3 className="deals-form-section-title">
                        Opportunity
                      </h3>

                      <div className="deals-form-grid">
                        <label className="deals-form-field deals-field-full">
                          <span>Customer *</span>
                          <select
                            required
                            value={form.customer_profile_id}
                            disabled={saving}
                            onChange={(event) =>
                              updateForm(
                                "customer_profile_id",
                                event.target.value,
                              )
                            }
                          >
                            <option value="">Select customer</option>
                            {customers.map((customer) => (
                              <option
                                key={customer.id}
                                value={customer.id}
                              >
                                {customerName(customer)}
                                {customer.contact?.phone
                                  ? ` · ${customer.contact.phone}`
                                  : ""}
                              </option>
                            ))}
                          </select>
                          {customers.length === 0 && (
                            <small>
                              No active customers found. Create a customer
                              before creating a deal.
                            </small>
                          )}
                        </label>

                        <label className="deals-form-field deals-field-full">
                          <span>Available property *</span>
                          <select
                            required
                            value={form.property_id}
                            disabled={saving}
                            onChange={(event) =>
                              updateForm("property_id", event.target.value)
                            }
                          >
                            <option value="">Select property</option>
                            {properties.map((property) => (
                              <option
                                key={property.id}
                                value={property.id}
                              >
                                {propertyTitle(property)} —{" "}
                                {propertyAddress(property)}
                              </option>
                            ))}
                          </select>
                          {properties.length === 0 && (
                            <small>
                              No available properties found. Add a property
                              or change its status to Available.
                            </small>
                          )}
                        </label>

                        <label className="deals-form-field">
                          <span>Initial stage *</span>
                          <select
                            required
                            value={form.stage}
                            disabled={saving}
                            onChange={(event) =>
                              updateForm(
                                "stage",
                                event.target.value as DealStage,
                              )
                            }
                          >
                            {DEAL_STAGES.map((stage) => (
                              <option key={stage} value={stage}>
                                {label(stage)}
                              </option>
                            ))}
                          </select>
                        </label>

                        <label className="deals-form-field">
                          <span>Expected value</span>
                          <input
                            type="number"
                            min="0"
                            step="0.01"
                            value={form.expected_value}
                            disabled={saving}
                            onChange={(event) =>
                              updateForm(
                                "expected_value",
                                event.target.value,
                              )
                            }
                            placeholder="e.g. 6500000"
                          />
                        </label>

                        <label className="deals-form-field">
                          <span>Currency *</span>
                          <select
                            required
                            value={form.currency}
                            disabled={saving}
                            onChange={(event) =>
                              updateForm("currency", event.target.value)
                            }
                          >
                            <option value="INR">INR — Indian Rupee</option>
                            <option value="USD">USD — US Dollar</option>
                            <option value="AED">AED — UAE Dirham</option>
                            <option value="GBP">GBP — Pound Sterling</option>
                          </select>
                        </label>
                      </div>

                      <h3 className="deals-form-section-title">
                        Notes
                      </h3>

                      <div className="deals-form-grid">
                        <label className="deals-form-field deals-field-full">
                          <span>Deal notes</span>
                          <textarea
                            maxLength={2000}
                            rows={4}
                            value={form.notes}
                            disabled={saving}
                            onChange={(event) =>
                              updateForm("notes", event.target.value)
                            }
                            placeholder="Add negotiation context, customer needs, or next steps..."
                          />
                          <small>{form.notes.length}/2000 characters</small>
                        </label>
                      </div>
                    </>
                  )}
                </div>

                <footer className="deals-form-actions">
                  <button
                    className="deals-secondary-button"
                    type="button"
                    disabled={saving}
                    onClick={() => {
                      setIsFormOpen(false);
                      setFormError("");
                    }}
                  >
                    Cancel
                  </button>

                  <button
                    className="deals-primary-button"
                    type="submit"
                    disabled={
                      saving ||
                      supportDataLoading ||
                      customers.length === 0 ||
                      properties.length === 0
                    }
                  >
                    {saving ? "Creating..." : "Create deal"}
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

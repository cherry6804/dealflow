
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
  propertiesApi,
  type Property,
  type PropertyStatus,
  type PropertyTransactionType,
  type PropertyType,
} from "../services/propertyApi";

import "./PropertiesPage.css";

const PAGE_SIZE = 10;

const PROPERTY_TYPES: PropertyType[] = [
  "APARTMENT",
  "VILLA",
  "INDEPENDENT_HOUSE",
  "PLOT",
  "COMMERCIAL",
  "OTHER",
];

const TRANSACTION_TYPES: PropertyTransactionType[] = ["SALE", "RENT", "LEASE"];

const PROPERTY_STATUSES: PropertyStatus[] = [
  "AVAILABLE",
  "RESERVED",
  "SOLD",
  "RENTED",
  "LEASED",
  "UNAVAILABLE",
];

interface PropertyForm {
  transaction_type: PropertyTransactionType;
  price: string;
  currency: string;
  rent: string;
  security_deposit: string;
  maintenance_charge: string;
  address_line_1: string;
  address_line_2: string;
  locality: string;
  city: string;
  state: string;
  postal_code: string;
  property_type: PropertyType;
  bhk: string;
  built_up_area: string;
  carpet_area: string;
  floor_number: string;
  total_floors: string;
  status: PropertyStatus;
  source_contact_id: string;
  owner_contact_id: string;
}

const EMPTY_FORM: PropertyForm = {
  transaction_type: "SALE",
  price: "",
  currency: "INR",
  rent: "",
  security_deposit: "",
  maintenance_charge: "",
  address_line_1: "",
  address_line_2: "",
  locality: "",
  city: "",
  state: "",
  postal_code: "",
  property_type: "APARTMENT",
  bhk: "",
  built_up_area: "",
  carpet_area: "",
  floor_number: "",
  total_floors: "",
  status: "AVAILABLE",
  source_contact_id: "",
  owner_contact_id: "",
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : "Something went wrong. Please try again.";
}

function label(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

function amount(value: number | string | null, currency = "INR"): string {
  if (value === null || value === undefined || value === "") return "—";

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

function propertyAddress(property: Property): string {
  return [
    property.address_line_1,
    property.address_line_2,
    property.locality,
    property.city,
    property.state,
    property.postal_code,
  ]
    .filter(Boolean)
    .join(", ");
}

function propertyTitle(property: Property): string {
  const type = property.property_type
    ? label(property.property_type)
    : "Property";

  const bedroom = property.bhk ? `${property.bhk} BHK ` : "";

  return `${bedroom}${type}`;
}

function priceLabel(property: Property): string {
  if (property.transaction_type === "RENT") {
    return `${amount(property.rent, property.currency || "INR")}/month`;
  }

  if (property.transaction_type === "LEASE") {
    return property.rent !== null
      ? `${amount(property.rent, property.currency || "INR")}/month`
      : amount(property.price, property.currency || "INR");
  }

  return amount(property.price, property.currency || "INR");
}

function statusClass(status: PropertyStatus | null): string {
  switch (status) {
    case "AVAILABLE":
      return "properties-status properties-status-available";
    case "RESERVED":
      return "properties-status properties-status-reserved";
    case "SOLD":
    case "RENTED":
    case "LEASED":
      return "properties-status properties-status-completed";
    default:
      return "properties-status properties-status-unavailable";
  }
}

function numericValue(value: string): number | null {
  if (!value.trim()) return null;

  const result = Number(value);

  return Number.isFinite(result) ? result : null;
}

function optionalText(value: string): string | null {
  return value.trim() || null;
}

export default function PropertiesPage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [transactionFilter, setTransactionFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [cityFilter, setCityFilter] = useState("");

  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [formError, setFormError] = useState("");
  const [partialCreation, setPartialCreation] = useState(false);

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [form, setForm] = useState<PropertyForm>(EMPTY_FORM);

  const modalRef = useRef<HTMLElement>(null);

  const loadProperties = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const result = await propertiesApi.search({
        page,
        page_size: PAGE_SIZE,
        q: search || undefined,
        transaction_type: transactionFilter
          ? (transactionFilter as PropertyTransactionType)
          : undefined,
        status: statusFilter ? (statusFilter as PropertyStatus) : undefined,
        property_type: typeFilter ? (typeFilter as PropertyType) : undefined,
        city: cityFilter || undefined,
      });

      setProperties(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [page, search, transactionFilter, statusFilter, typeFilter, cityFilter]);

  useEffect(() => {
    let cancelled = false;

    async function fetchProperties() {
      try {
        const result = await propertiesApi.search({
          page,
          page_size: PAGE_SIZE,
          q: search || undefined,
          transaction_type: transactionFilter
            ? (transactionFilter as PropertyTransactionType)
            : undefined,
          status: statusFilter ? (statusFilter as PropertyStatus) : undefined,
          property_type: typeFilter ? (typeFilter as PropertyType) : undefined,
          city: cityFilter || undefined,
        });

        if (cancelled) return;

        setProperties(result.items);
        setTotal(result.total);
        setTotalPages(result.total_pages);
        setError("");
      } catch (loadError) {
        if (!cancelled) setError(errorMessage(loadError));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void fetchProperties();

    return () => {
      cancelled = true;
    };
  }, [page, search, transactionFilter, statusFilter, typeFilter, cityFilter]);

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
    let cancelled = false;

    async function fetchContacts() {
      try {
        const result = await contactsApi.list({
          page: 1,
          page_size: 100,
        });

        if (!cancelled) setContacts(result.items);
      } catch {
        if (!cancelled) setContacts([]);
      }
    }

    void fetchContacts();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!isFormOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const timer = window.setTimeout(() => {
      modalRef.current?.querySelector<HTMLInputElement>("input")?.focus();
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
    setPartialCreation(false);
    setIsFormOpen(true);
  }

  function updateForm<K extends keyof PropertyForm>(
    key: K,
    value: PropertyForm[K],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    setPartialCreation(false);
    setSuccess("");

    if (
      form.floor_number.trim() &&
      form.total_floors.trim() &&
      Number(form.floor_number) > Number(form.total_floors)
    ) {
      setFormError("Floor number cannot be greater than total floors.");
      return;
    }

    if (form.transaction_type === "SALE" && !form.price.trim()) {
      setFormError("Enter the sale price.");
      return;
    }

    if (
      (form.transaction_type === "RENT" ||
        form.transaction_type === "LEASE") &&
      !form.rent.trim()
    ) {
      setFormError("Enter the monthly rent.");
      return;
    }

    setSaving(true);

    let propertyId: string | null = null;

    try {
      const created = await propertiesApi.create();
      propertyId = created.id;

      await propertiesApi.updateLocation(propertyId, {
        address_line_1: form.address_line_1.trim(),
        address_line_2: optionalText(form.address_line_2),
        locality: form.locality.trim(),
        city: form.city.trim(),
        state: form.state.trim(),
        postal_code: optionalText(form.postal_code),
        property_type: form.property_type,
        bhk: numericValue(form.bhk),
        built_up_area: numericValue(form.built_up_area),
        carpet_area: numericValue(form.carpet_area),
        floor_number: numericValue(form.floor_number),
        total_floors: numericValue(form.total_floors),
      });

      await propertiesApi.updateCommercial(propertyId, {
        transaction_type: form.transaction_type,
        price: numericValue(form.price),
        currency: form.currency.trim().toUpperCase(),
        rent: numericValue(form.rent),
        security_deposit: numericValue(form.security_deposit),
        maintenance_charge: numericValue(form.maintenance_charge),
      });

      await propertiesApi.updateStatus(propertyId, form.status);

      if (form.source_contact_id || form.owner_contact_id) {
        await propertiesApi.updateAssociation(propertyId, {
          source_contact_id: form.source_contact_id || null,
          owner_contact_id: form.owner_contact_id || null,
        });
      }

      setIsFormOpen(false);
      setForm(EMPTY_FORM);
      setPage(1);
      setSearch("");
      setSearchInput("");
      setTransactionFilter("");
      setStatusFilter("");
      setTypeFilter("");
      setCityFilter("");
      setSuccess("Property created successfully.");

      const result = await propertiesApi.search({
        page: 1,
        page_size: PAGE_SIZE,
      });

      setProperties(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
      setError("");
    } catch (createError) {
      if (propertyId) {
        setPartialCreation(true);
        setFormError(
          `Property ${propertyId} was created, but one of its detail updates failed. ${errorMessage(createError)} Refresh the listing and complete the missing details before relying on this record.`,
        );
      } else {
        setFormError(errorMessage(createError));
      }
    } finally {
      setSaving(false);
      setLoading(false);
    }
  }

  async function handleStatusChange(property: Property, value: string) {
    const status = value as PropertyStatus;

    if (status === property.status || updatingId) return;

    setUpdatingId(property.id);
    setError("");
    setSuccess("");

    try {
      await propertiesApi.updateStatus(property.id, status);
      setSuccess(`Property status updated to ${label(status)}.`);
      await loadProperties();
    } catch (updateError) {
      setError(errorMessage(updateError));
    } finally {
      setUpdatingId(null);
    }
  }

  const firstResult = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastResult = Math.min(page * PAGE_SIZE, total);

  return (
    <section className="properties-page">
      <header className="properties-header">
        <div>
          <span className="properties-eyebrow">INVENTORY WORKSPACE</span>
          <h1>Properties</h1>
          <p className="properties-subtitle">
            Manage property listings, pricing, location, and availability.
          </p>
        </div>

        <button
          className="properties-primary-button"
          type="button"
          onClick={openCreateForm}
        >
          <span aria-hidden="true">+</span> Add property
        </button>
      </header>

      <section className="properties-summary" aria-label="Property inventory">
        <div className="properties-summary-icon" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-5h6v5M9 9h.01M15 9h.01M9 12h.01M15 12h.01" />
          </svg>
        </div>
        <div>
          <p className="properties-summary-label">Matching properties</p>
          <p className="properties-summary-value">
            {loading && total === 0 ? "—" : total.toLocaleString("en-IN")}
          </p>
        </div>
      </section>

      {success && (
        <div className="properties-alert properties-alert-success" role="status">
          <span>{success}</span>
          <button
            type="button"
            className="properties-dismiss"
            aria-label="Dismiss success message"
            onClick={() => setSuccess("")}
          >
            ×
          </button>
        </div>
      )}

      <section className="properties-panel">
        <header className="properties-panel-heading">
          <div>
            <h2>Property inventory</h2>
            <p>Search listings and manage availability.</p>
          </div>
          <button
            className="properties-secondary-button"
            type="button"
            disabled={loading}
            onClick={() => void loadProperties()}
          >
            {loading ? "Refreshing..." : "↻ Refresh"}
          </button>
        </header>

        <div className="properties-toolbar">
          <label className="properties-search">
            <span className="properties-visually-hidden">Search properties</span>
            <span aria-hidden="true" className="properties-search-icon">⌕</span>
            <input
              type="search"
              maxLength={320}
              value={searchInput}
              placeholder="Search address, locality, city or postal code..."
              onChange={(event) => {
                setSearchInput(event.target.value);
                setPage(1);
              }}
            />
          </label>

          <label className="properties-filter">
            <span className="properties-visually-hidden">Transaction type</span>
            <select
              value={transactionFilter}
              onChange={(event) => {
                setTransactionFilter(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All transactions</option>
              {TRANSACTION_TYPES.map((type) => (
                <option value={type} key={type}>{label(type)}</option>
              ))}
            </select>
          </label>

          <label className="properties-filter">
            <span className="properties-visually-hidden">Property status</span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {PROPERTY_STATUSES.map((status) => (
                <option value={status} key={status}>{label(status)}</option>
              ))}
            </select>
          </label>

          <label className="properties-filter">
            <span className="properties-visually-hidden">Property type</span>
            <select
              value={typeFilter}
              onChange={(event) => {
                setTypeFilter(event.target.value);
                setPage(1);
              }}
            >
              <option value="">All property types</option>
              {PROPERTY_TYPES.map((type) => (
                <option value={type} key={type}>{label(type)}</option>
              ))}
            </select>
          </label>

          <label className="properties-filter properties-city-filter">
            <span className="properties-visually-hidden">Filter by city</span>
            <input
              type="text"
              maxLength={160}
              value={cityFilter}
              placeholder="City"
              onChange={(event) => {
                setCityFilter(event.target.value);
                setPage(1);
              }}
            />
          </label>
        </div>

        {error && (
          <div className="properties-alert properties-alert-error" role="alert">
            <div>
              <strong>Couldn't load or update properties</strong>
              <p>{error}</p>
            </div>
            <button
              className="properties-secondary-button"
              type="button"
              onClick={() => void loadProperties()}
            >
              Retry
            </button>
          </div>
        )}

        {loading ? (
          <div className="properties-state" role="status" aria-live="polite">
            <span className="properties-spinner" aria-hidden="true" />
            <p>Loading properties...</p>
          </div>
        ) : !error && properties.length === 0 ? (
          <div className="properties-empty">
            <div className="properties-empty-icon" aria-hidden="true">⌂</div>
            <h3>
              {search || transactionFilter || statusFilter || typeFilter || cityFilter
                ? "No matching properties"
                : "Your property inventory starts here"}
            </h3>
            <p>
              {search || transactionFilter || statusFilter || typeFilter || cityFilter
                ? "Try changing your search or filters."
                : "Add your first property to start managing your inventory."}
            </p>
            {search || transactionFilter || statusFilter || typeFilter || cityFilter ? (
              <button
                className="properties-secondary-button"
                type="button"
                onClick={() => {
                  setSearch("");
                  setSearchInput("");
                  setTransactionFilter("");
                  setStatusFilter("");
                  setTypeFilter("");
                  setCityFilter("");
                  setPage(1);
                }}
              >
                Clear filters
              </button>
            ) : (
              <button
                className="properties-primary-button"
                type="button"
                onClick={openCreateForm}
              >
                + Add your first property
              </button>
            )}
          </div>
        ) : !error ? (
          <>
            <div className="properties-table-wrapper">
              <table className="properties-table">
                <thead>
                  <tr>
                    <th scope="col">Property</th>
                    <th scope="col">Transaction</th>
                    <th scope="col">Price / Rent</th>
                    <th scope="col">Area</th>
                    <th scope="col">Status</th>
                    <th scope="col">Listed</th>
                  </tr>
                </thead>
                <tbody>
                  {properties.map((property) => (
                    <tr key={property.id}>
                      <td>
                        <div className="properties-name">
                          {propertyTitle(property)}
                        </div>
                        <div className="properties-secondary-text">
                          {propertyAddress(property) || "Address not provided"}
                        </div>
                      </td>
                      <td>
                        {property.transaction_type
                          ? label(property.transaction_type)
                          : "—"}
                      </td>
                      <td className="properties-price">
                        {priceLabel(property)}
                        {property.transaction_type === "SALE" &&
                          property.maintenance_charge !== null && (
                            <div className="properties-secondary-text">
                              Maintenance:{" "}
                              {amount(
                                property.maintenance_charge,
                                property.currency || "INR",
                              )}
                            </div>
                          )}
                      </td>
                      <td>
                        {property.built_up_area !== null
                          ? `${property.built_up_area} sq. ft.`
                          : "—"}
                        {property.bhk ? (
                          <div className="properties-secondary-text">
                            {property.bhk} BHK
                          </div>
                        ) : null}
                      </td>
                      <td>
                        <span className={statusClass(property.status)}>
                          {property.status ? label(property.status) : "Unspecified"}
                        </span>
                        <select
                          className="properties-inline-select"
                          aria-label={`Change status for ${propertyTitle(property)}`}
                          value={property.status ?? ""}
                          disabled={updatingId === property.id}
                          onChange={(event) =>
                            void handleStatusChange(property, event.target.value)
                          }
                        >
                          {!property.status && (
                            <option value="">Unspecified</option>
                          )}
                          {PROPERTY_STATUSES.map((status) => (
                            <option value={status} key={status}>{label(status)}</option>
                          ))}
                        </select>
                      </td>
                      <td>
                        {new Intl.DateTimeFormat("en-IN", {
                          day: "2-digit",
                          month: "short",
                          year: "numeric",
                        }).format(new Date(property.created_at))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <footer className="properties-pagination">
              <p>
                Showing <strong>{firstResult}–{lastResult}</strong> of{" "}
                <strong>{total}</strong> properties
              </p>
              <div className="properties-pagination-controls">
                <button
                  className="properties-page-button"
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
                  className="properties-page-button"
                  type="button"
                  disabled={page >= totalPages || totalPages === 0 || loading}
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
      className="properties-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) {
          setIsFormOpen(false);
        }
      }}
    >
      <section
        ref={modalRef}
        className="properties-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="properties-modal-title"
      >
        <header className="properties-modal-header">
          <div>
            <span className="properties-eyebrow">PROPERTY DETAILS</span>
            <h2 id="properties-modal-title">Add a property</h2>
            <p>Enter the listing details and availability.</p>
          </div>

          <button
            className="properties-modal-close"
            type="button"
            aria-label="Close form"
            disabled={saving}
            onClick={() => setIsFormOpen(false)}
          >
            ×
          </button>
        </header>

        <form className="properties-form" onSubmit={handleCreate}>
          <div className="properties-form-body">
            {formError && (
              <div
                className="properties-alert properties-alert-error"
                role="alert"
              >
                {partialCreation && (
                  <strong>Property needs completion</strong>
                )}
                <p>{formError}</p>
              </div>
            )}

            {/* LISTING */}
            <h3 className="properties-form-section-title">Listing</h3>

            <div className="properties-form-grid">
              <label className="properties-form-field">
                <span>Transaction type *</span>
                <select
                  required
                  value={form.transaction_type}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm(
                      "transaction_type",
                      event.target.value as PropertyTransactionType,
                    )
                  }
                >
                  {TRANSACTION_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {label(type)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="properties-form-field">
                <span>Property type *</span>
                <select
                  required
                  value={form.property_type}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm(
                      "property_type",
                      event.target.value as PropertyType,
                    )
                  }
                >
                  {PROPERTY_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {label(type)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="properties-form-field">
                <span>Sale price (optional for rent/lease)</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  required={form.transaction_type === "SALE"}
                  value={form.price}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("price", event.target.value)
                  }
                  placeholder="e.g. 6500000"
                />
              </label>

              <label className="properties-form-field">
                <span>
                  Monthly rent{" "}
                  {form.transaction_type === "SALE" ? "(optional)" : "*"}
                </span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  required={form.transaction_type !== "SALE"}
                  value={form.rent}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("rent", event.target.value)
                  }
                  placeholder="e.g. 25000"
                />
              </label>

              <label className="properties-form-field">
                <span>Security deposit</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.security_deposit}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("security_deposit", event.target.value)
                  }
                />
              </label>

              <label className="properties-form-field">
                <span>Maintenance charge</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.maintenance_charge}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("maintenance_charge", event.target.value)
                  }
                />
              </label>

              <label className="properties-form-field">
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

              <label className="properties-form-field">
                <span>Availability *</span>
                <select
                  required
                  value={form.status}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("status", event.target.value as PropertyStatus)
                  }
                >
                  {PROPERTY_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {label(status)}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {/* LOCATION */}
            <h3 className="properties-form-section-title">Location</h3>

            <div className="properties-form-grid">
              <label className="properties-form-field properties-field-full">
                <span>Address line 1 *</span>
                <input
                  required
                  maxLength={250}
                  value={form.address_line_1}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("address_line_1", event.target.value)
                  }
                  placeholder="Building, street or plot"
                />
              </label>

              <label className="properties-form-field properties-field-full">
                <span>Address line 2</span>
                <input
                  maxLength={250}
                  value={form.address_line_2}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("address_line_2", event.target.value)
                  }
                  placeholder="Apartment, landmark (optional)"
                />
              </label>

              <label className="properties-form-field">
                <span>Locality *</span>
                <input
                  required
                  maxLength={160}
                  value={form.locality}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("locality", event.target.value)
                  }
                />
              </label>

              <label className="properties-form-field">
                <span>City *</span>
                <input
                  required
                  maxLength={160}
                  value={form.city}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("city", event.target.value)
                  }
                />
              </label>

              <label className="properties-form-field">
                <span>State *</span>
                <input
                  required
                  maxLength={160}
                  value={form.state}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("state", event.target.value)
                  }
                />
              </label>

              <label className="properties-form-field">
                <span>Postal code</span>
                <input
                  maxLength={20}
                  value={form.postal_code}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("postal_code", event.target.value)
                  }
                />
              </label>
            </div>

            {/* PROPERTY ATTRIBUTES */}
            <h3 className="properties-form-section-title">
              Property attributes
            </h3>

            <div className="properties-form-grid">
              <label className="properties-form-field">
                <span>BHK</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={form.bhk}
                  disabled={saving}
                  onChange={(event) => updateForm("bhk", event.target.value)}
                />
              </label>

              <label className="properties-form-field">
                <span>Built-up area (sq. ft.)</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.built_up_area}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("built_up_area", event.target.value)
                  }
                />
              </label>

              <label className="properties-form-field">
                <span>Carpet area (sq. ft.)</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.carpet_area}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("carpet_area", event.target.value)
                  }
                />
              </label>

              <label className="properties-form-field">
                <span>Floor number</span>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={form.floor_number}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("floor_number", event.target.value)
                  }
                />
              </label>

              <label className="properties-form-field">
                <span>Total floors</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={form.total_floors}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("total_floors", event.target.value)
                  }
                />
              </label>
            </div>

            {/* CONTACTS */}
            <h3 className="properties-form-section-title">
              Contacts (optional)
            </h3>

            <div className="properties-form-grid">
              <label className="properties-form-field">
                <span>Source contact</span>
                <select
                  value={form.source_contact_id}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("source_contact_id", event.target.value)
                  }
                >
                  <option value="">Not assigned</option>
                  {contacts.map((contact) => (
                    <option key={contact.id} value={contact.id}>
                      {[contact.first_name, contact.last_name]
                        .filter(Boolean)
                        .join(" ")}
                    </option>
                  ))}
                </select>
              </label>

              <label className="properties-form-field">
                <span>Owner contact</span>
                <select
                  value={form.owner_contact_id}
                  disabled={saving}
                  onChange={(event) =>
                    updateForm("owner_contact_id", event.target.value)
                  }
                >
                  <option value="">Not assigned</option>
                  {contacts.map((contact) => (
                    <option key={contact.id} value={contact.id}>
                      {[contact.first_name, contact.last_name]
                        .filter(Boolean)
                        .join(" ")}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <p className="properties-form-hint">
              The property is created first. If a later step fails, the
              property record may exist with incomplete details.
            </p>
          </div>

          {/* FIXED FOOTER */}
          <footer className="properties-form-actions">
            <button
              className="properties-secondary-button"
              type="button"
              disabled={saving}
              onClick={() => setIsFormOpen(false)}
            >
              Cancel
            </button>

            <button
              className="properties-primary-button"
              type="submit"
              disabled={saving}
            >
              {saving ? "Creating..." : "Create property"}
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

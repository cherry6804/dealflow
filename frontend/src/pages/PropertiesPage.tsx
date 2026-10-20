
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
  propertiesApi,
  type Property,
  type PropertyStatus,
  type PropertyTransactionType,
  type PropertyType,
} from "../services/propertyApi";
import SiteVisitHistory from "../components/SiteVisitHistory";
import "./PropertiesPage.css";
import "./DealsPage.css";

const PAGE_SIZE = 10;

const DEFAULT_VISIBLE_PROPERTY_COLUMNS = [
  "property",
  "transaction",
  "price",
  "area",
  "status",
  "createdAt",
] as const;

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
  if (error instanceof ApiError || error instanceof Error) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
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
  const [visibleColumnKeys, setVisibleColumnKeys] = useState<string[]>([
    ...DEFAULT_VISIBLE_PROPERTY_COLUMNS,
  ]);
  const [sortColumns, setSortColumns] = useState<SortColumn[]>([]);
  const [compactGrid, setCompactGrid] = useState(
    () => typeof window !== "undefined" && window.innerWidth >= 1600,
  );
  const [columnMenuPosition, setColumnMenuPosition] = useState<{
    top: number;
    left: number;
  } | null>(null);

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
  const [historyProperty, setHistoryProperty] = useState<Property | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [form, setForm] = useState<PropertyForm>(EMPTY_FORM);

  const modalRef = useRef<HTMLElement>(null);
  const requestSequenceRef = useRef(0);

  useEffect(() => {
    const updateGridDensity = () => setCompactGrid(window.innerWidth >= 1600);
    updateGridDensity();
    window.addEventListener("resize", updateGridDensity, { passive: true });
    return () => window.removeEventListener("resize", updateGridDensity);
  }, []);

  useEffect(() => {
    if (!columnMenuPosition) return;

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setColumnMenuPosition(null);
    };
    const closeOnResize = () => setColumnMenuPosition(null);

    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeOnResize);
    window.addEventListener("scroll", closeOnResize, true);

    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeOnResize);
      window.removeEventListener("scroll", closeOnResize, true);
    };
  }, [columnMenuPosition]);

  const loadProperties = useCallback(async () => {
    const requestId = ++requestSequenceRef.current;

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
      });

      if (requestId !== requestSequenceRef.current) return;

      setProperties(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
    } catch (loadError) {
      if (requestId === requestSequenceRef.current) {
        setError(errorMessage(loadError));
      }
    } finally {
      if (requestId === requestSequenceRef.current) {
        setLoading(false);
      }
    }
  }, [page, search, transactionFilter, statusFilter, typeFilter]);

  useEffect(() => {
    void loadProperties();

    return () => {
      requestSequenceRef.current += 1;
    };
  }, [loadProperties]);

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
    if (!isFormOpen && !historyProperty) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const timer = isFormOpen
      ? window.setTimeout(() => {
          modalRef.current?.querySelector<HTMLInputElement>("input")?.focus();
        }, 50)
      : undefined;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || saving) return;

      if (isFormOpen) {
        setIsFormOpen(false);
        setFormError("");
      }

      if (historyProperty) {
        setHistoryProperty(null);
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      if (timer !== undefined) window.clearTimeout(timer);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isFormOpen, historyProperty, saving]);

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
          `Property ${propertyId} was created, but one of its detail updates failed. ` +
            `${errorMessage(createError)} Refresh the listing and complete the missing details before relying on this record.`,
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

  const propertyColumns = useMemo<readonly Column<Property>[]>(
    () => [
      {
        key: "property",
        name: "Property / Location",
        resizable: true,
        sortable: true,
        width: 280,
        minWidth: 220,
        renderCell: ({ row }) => (
          <div className="properties-grid-property">
            <strong>{propertyTitle(row)}</strong>
            <span>{propertyAddress(row) || "Address not provided"}</span>
          </div>
        ),
      },
      {
        key: "transaction",
        name: "Transaction",
        resizable: true,
        sortable: true,
        width: 110,
        minWidth: 100,
        renderCell: ({ row }) => (
          <span className="properties-grid-secondary">
            {row.transaction_type ? label(row.transaction_type) : "—"}
          </span>
        ),
      },
      {
        key: "price",
        name: "Price / Rent",
        resizable: true,
        sortable: true,
        width: 150,
        minWidth: 130,
        renderCell: ({ row }) => (
          <div className="properties-grid-price">
            <strong>{priceLabel(row)}</strong>
            {row.transaction_type === "SALE" && row.maintenance_charge !== null && (
              <span>
                Maintenance: {amount(row.maintenance_charge, row.currency || "INR")}
              </span>
            )}
          </div>
        ),
      },
      {
        key: "area",
        name: "Area",
        resizable: true,
        sortable: true,
        width: 125,
        minWidth: 110,
        renderCell: ({ row }) => (
          <div className="properties-grid-area">
            <span>
              {row.built_up_area !== null ? `${row.built_up_area} sq. ft.` : "—"}
            </span>
            {row.bhk ? <small>{row.bhk} BHK</small> : null}
          </div>
        ),
      },
      {
        key: "status",
        name: "Status",
        resizable: true,
        sortable: true,
        width: 150,
        minWidth: 130,
        renderCell: ({ row }) => (
          <div className="properties-grid-status">
            <select
              className={`properties-inline-select ${statusClass(row.status)}`}
              aria-label={`Change status for ${propertyTitle(row)}`}
              value={row.status ?? ""}
              disabled={updatingId === row.id}
              onChange={(event) => void handleStatusChange(row, event.target.value)}
            >
              {!row.status && <option value="">Unspecified</option>}
              {PROPERTY_STATUSES.map((status) => (
                <option value={status} key={status}>{label(status)}</option>
              ))}
            </select>
          </div>
        ),
      },
      {
        key: "createdAt",
        name: "Listed",
        resizable: true,
        sortable: true,
        width: 120,
        minWidth: 105,
        renderCell: ({ row }) => (
          <span className="properties-grid-secondary">
            {Number.isNaN(new Date(row.created_at).getTime())
              ? "—"
              : new Intl.DateTimeFormat("en-IN", {
                  day: "2-digit",
                  month: "short",
                  year: "numeric",
                }).format(new Date(row.created_at))}
          </span>
        ),
      },
      {
        key: "actions",
        name: "Actions",
        width: 88,
        minWidth: 76,
        resizable: false,
        sortable: false,
        renderCell: ({ row }) => (
          <button
            type="button"
            className="properties-icon-action"
            aria-label={`View visit history for ${propertyTitle(row)}`}
            title="View visit history"
            onClick={() => setHistoryProperty(row)}
          >
            <svg
              viewBox="0 0 24 24"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            <span>History</span>
          </button>
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
            type="button"
            className="deals-configure-columns-button"
            aria-label="Configure visible columns"
            aria-expanded={columnMenuPosition !== null}
            title="Configure columns"
            onClick={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              const menuWidth = 230;
              const menuHeight = 280;
              const fitsBelow = rect.bottom + menuHeight + 8 <= window.innerHeight;
              const top = fitsBelow
                ? rect.bottom + 6
                : Math.max(8, rect.top - menuHeight - 6);

              setColumnMenuPosition({
                top,
                left: Math.max(
                  8,
                  Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 8),
                ),
              });
            }}
          >
            <svg
              viewBox="0 0 24 24"
              aria-hidden="true"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="4" y="4" width="16" height="16" rx="2" />
              <path d="M9 4v16M15 4v16" />
            </svg>
          </button>
        ),
        renderCell: () => <span aria-hidden="true" />,
      },
    ],
    [updatingId],
  );

  const visiblePropertyColumns = useMemo(
    () => propertyColumns.filter((column) =>
      column.key === "actions" || column.key === "configure" || visibleColumnKeys.includes(column.key),
    ),
    [propertyColumns, visibleColumnKeys],
  );

  const sortedProperties = useMemo(() => {
    if (sortColumns.length === 0) return properties;

    const sorted = [...properties];
    const compareValues = (left: unknown, right: unknown) => {
      if (left == null && right == null) return 0;
      if (left == null) return -1;
      if (right == null) return 1;
      if (typeof left === "number" && typeof right === "number") return left - right;
      return String(left).localeCompare(String(right), undefined, {
        numeric: true,
        sensitivity: "base",
      });
    };

    sorted.sort((left, right) => {
      for (const sort of sortColumns) {
        let leftValue: unknown;
        let rightValue: unknown;

        switch (sort.columnKey) {
          case "property":
            leftValue = `${propertyTitle(left)} ${propertyAddress(left)}`;
            rightValue = `${propertyTitle(right)} ${propertyAddress(right)}`;
            break;
          case "transaction":
            leftValue = left.transaction_type;
            rightValue = right.transaction_type;
            break;
          case "price":
            leftValue = left.transaction_type === "RENT" ? left.rent : left.price;
            rightValue = right.transaction_type === "RENT" ? right.rent : right.price;
            break;
          case "area":
            leftValue = left.built_up_area;
            rightValue = right.built_up_area;
            break;
          case "status":
            leftValue = left.status;
            rightValue = right.status;
            break;
          case "createdAt":
            leftValue = new Date(left.created_at).getTime();
            rightValue = new Date(right.created_at).getTime();
            break;
          default:
            continue;
        }

        const comparison = compareValues(leftValue, rightValue);
        if (comparison !== 0) return sort.direction === "ASC" ? comparison : -comparison;
      }
      return 0;
    });

    return sorted;
  }, [properties, sortColumns]);

  const firstResult = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastResult = Math.min(page * PAGE_SIZE, total);
  const hasActiveFilters = Boolean(
    search || transactionFilter || statusFilter || typeFilter,
  );

  function clearFilters() {
    setSearch("");
    setSearchInput("");
    setTransactionFilter("");
    setStatusFilter("");
    setTypeFilter("");
    setPage(1);
  }

  return (
    <main className="deals-page properties-page">
      <header className="deals-page-header">
        <div className="deals-heading-copy">
          <h1>Properties</h1>
          <p>Manage property listings, pricing, location, and availability.</p>
        </div>
      </header>

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

      <div className="deals-filterbar" role="search" aria-label="Filter properties">
        <label className="deals-search-field">
          <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m16 16 4 4" />
          </svg>
          <span className="properties-visually-hidden">Search properties</span>
          <input
            type="search"
            maxLength={320}
            value={searchInput}
            placeholder="Search address, locality, city or postal code"
            onChange={(event) => {
              setSearchInput(event.target.value);
              setPage(1);
            }}
          />
          {searchInput && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                setSearchInput("");
                setSearch("");
                setPage(1);
              }}
            >
              ×
            </button>
          )}
        </label>

        <label className="deals-filter-field">
          <span>Transaction</span>
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

        <label className="deals-filter-field">
          <span>Status</span>
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

        <label className="deals-filter-field">
          <span>Property type</span>
          <select
            value={typeFilter}
            onChange={(event) => {
              setTypeFilter(event.target.value);
              setPage(1);
            }}
          >
            <option value="">All types</option>
            {PROPERTY_TYPES.map((type) => (
              <option value={type} key={type}>{label(type)}</option>
            ))}
          </select>
        </label>

        <button
          className="deals-primary-button deals-add-button"
          type="button"
          onClick={openCreateForm}
        >
          <svg
            viewBox="0 0 24 24"
            aria-hidden="true"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 5v14M5 12h14" />
          </svg>
          Add property
        </button>

        {hasActiveFilters && (
          <button className="deals-clear-filters" type="button" onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>

      {error && (
        <div className="properties-alert properties-alert-error" role="alert">
          <div>
            <strong>Could not load or update properties</strong>
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

      <div className="deals-grid-shell properties-grid-shell">
        {loading && properties.length === 0 ? (
          <div className="properties-state" role="status" aria-live="polite">
            <span className="properties-spinner" aria-hidden="true" />
            <p>Loading properties...</p>
          </div>
        ) : !error && properties.length === 0 ? (
          <div className="properties-empty">
            <div className="properties-empty-icon" aria-hidden="true">⌂</div>
            <h3>{hasActiveFilters ? "No matching properties" : "Your property inventory starts here"}</h3>
            <p>
              {hasActiveFilters
                ? "Try changing your search or filters."
                : "Add your first property to start managing your inventory."}
            </p>
            {hasActiveFilters ? (
              <button className="properties-secondary-button" type="button" onClick={clearFilters}>
                Clear filters
              </button>
            ) : (
              <button className="properties-primary-button" type="button" onClick={openCreateForm}>
                <span aria-hidden="true">+</span> Add your first property
              </button>
            )}
          </div>
        ) : !error ? (
          <>
            <DataGrid
              className="deals-react-data-grid properties-react-data-grid"
              aria-label="Property inventory"
              columns={visiblePropertyColumns}
              rows={sortedProperties}
              rowKeyGetter={(row) => row.id}
              rowHeight={compactGrid ? 48 : 62}
              headerRowHeight={52}
              defaultColumnOptions={{ resizable: true, sortable: true }}
              sortColumns={sortColumns}
              onSortColumnsChange={setSortColumns}
              style={{
                height: Math.min(
                  52 + sortedProperties.length * (compactGrid ? 48 : 62),
                  Math.max(260, (typeof window !== "undefined" ? window.innerHeight : 900) * 0.66),
                ),
                minHeight: 52 + Math.min(sortedProperties.length, 1) * (compactGrid ? 48 : 62),
              }}
              renderers={{
                noRowsFallback: <div className="deals-grid-no-rows">No properties to display.</div>,
              }}
            />
            <footer className="properties-grid-footer">
              <div className="properties-grid-footer-count" aria-live="polite">
                <strong>{total.toLocaleString("en-IN")}</strong>{" "}
                {total === 1 ? "property" : "properties"} in your workspace
                {total > 0 && (
                  <span className="properties-grid-footer-range">
                    Showing {firstResult}–{lastResult}
                  </span>
                )}
              </div>

              <div className="properties-grid-footer-right">
                <span className="properties-grid-footer-status">
                  <span className="properties-grid-footer-status-dot" aria-hidden="true" />
                  You’re all caught up
                </span>

                {totalPages > 1 && (
                  <div className="properties-pagination-controls" aria-label="Property pages">
                    <button
                      className="properties-page-button"
                      type="button"
                      disabled={page <= 1 || loading}
                      onClick={() => setPage((current) => current - 1)}
                    >
                      Previous
                    </button>
                    <span>Page {page} of {totalPages}</span>
                    <button
                      className="properties-page-button"
                      type="button"
                      disabled={page >= totalPages || loading}
                      onClick={() => setPage((current) => current + 1)}
                    >
                      Next
                    </button>
                  </div>
                )}
              </div>
            </footer>
          </>
        ) : (
          <div className="properties-empty">
            <h3>Properties could not be displayed</h3>
            <p>Retry the request to load the property inventory.</p>
          </div>
        )}
      </div>

      {columnMenuPosition && createPortal(
        <>
          <button
            className="properties-column-menu-backdrop"
            type="button"
            aria-label="Close column settings"
            onClick={() => setColumnMenuPosition(null)}
          />
          <div
            className="properties-column-menu"
            role="dialog"
            aria-label="Configure property columns"
            style={{ top: columnMenuPosition.top, left: columnMenuPosition.left }}
          >
            <div className="properties-column-menu-heading">Visible columns</div>
            {DEFAULT_VISIBLE_PROPERTY_COLUMNS.map((key) => {
              const names: Record<string, string> = {
                property: "Property / Location",
                transaction: "Transaction",
                price: "Price / Rent",
                area: "Area",
                status: "Status",
                createdAt: "Listed",
              };
              return (
                <label className="properties-column-menu-option" key={key}>
                  <input
                    type="checkbox"
                    checked={visibleColumnKeys.includes(key)}
                    onChange={(event) => setVisibleColumnKeys((current) =>
                      event.target.checked
                        ? [...current, key]
                        : current.filter((item) => item !== key),
                    )}
                  />
                  <span>{names[key]}</span>
                </label>
              );
            })}
            <div className="properties-column-menu-footer">
              <button type="button" onClick={() => setVisibleColumnKeys([...DEFAULT_VISIBLE_PROPERTY_COLUMNS])}>
                Reset
              </button>
              <button type="button" onClick={() => setColumnMenuPosition(null)}>
                Done
              </button>
            </div>
          </div>
        </>,
        document.body,
      )}

      {isFormOpen &&
        createPortal(
          <div
            className="properties-modal-backdrop"
            role="presentation"
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

      {historyProperty &&
        createPortal(
          <div
            className="properties-modal-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) {
                setHistoryProperty(null);
              }
            }}
          >
            <section
              className="properties-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="property-visit-history-title"
            >
              <header className="properties-modal-header">
                <div>
                  <span className="properties-eyebrow">PROPERTY DETAILS</span>
                  <h2 id="property-visit-history-title">Visit history</h2>
                  <p>
                    {propertyTitle(historyProperty)}
                    {propertyAddress(historyProperty)
                      ? ` · ${propertyAddress(historyProperty)}`
                      : ""}
                  </p>
                </div>
                <button
                  type="button"
                  className="properties-modal-close"
                  aria-label="Close visit history"
                  onClick={() => setHistoryProperty(null)}
                >
                  ×
                </button>
              </header>

              <div className="properties-form-body">
                <SiteVisitHistory
                  propertyId={historyProperty.id}
                  title="Property site visits"
                />
              </div>

              <footer className="properties-form-actions">
                <button
                  type="button"
                  className="properties-secondary-button"
                  onClick={() => setHistoryProperty(null)}
                >
                  Close
                </button>
              </footer>
            </section>
          </div>,
          document.body,
        )}
    </main>
  );
}

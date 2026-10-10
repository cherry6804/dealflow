
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";
import { ApiError } from "../lib/api";
import { contactsApi, type Contact } from "../services/contactApi";
import { leadsApi, type Lead } from "../services/leadApi";
import {
  requirementsApi,
  type CustomerRequirement,
  type RequirementAssociation,
  type RequirementLocation,
  type RequirementPossessionParkingPreference,
  type RequirementPropertyPreference,
  type RequirementStatus,
  type PropertyType,
  type PossessionPreference,
  type ParkingPreference,
} from "../services/requirementApi";
import "./RequirementsPage.css";
import {
  customerProfilesApi,
  type CustomerProfile,
} from "../services/customerProfileApi";
const PAGE_SIZE = 10;

const PROPERTY_TYPES: PropertyType[] = [
  "APARTMENT",
  "VILLA",
  "INDEPENDENT_HOUSE",
  "PLOT",
  "COMMERCIAL",
  "OTHER",
];

const POSSESSION_OPTIONS: PossessionPreference[] = [
  "READY_TO_MOVE",
  "WITHIN_3_MONTHS",
  "WITHIN_6_MONTHS",
  "WITHIN_12_MONTHS",
  "AFTER_12_MONTHS",
  "ANY",
];

const PARKING_OPTIONS: ParkingPreference[] = [
  "REQUIRED",
  "PREFERRED",
  "NOT_REQUIRED",
  "ANY",
];

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}

function formatLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

function formatCurrency(value: string | number | null): string {
  if (value == null || value === "") return "Not set";

  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);

  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(number);
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "—";

  return date.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function optionalNumber(value: string): number | null {
  if (!value.trim()) return null;

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function contactName(contact: Contact | undefined): string {
  if (!contact) return "Contact unavailable";

  return (
    [contact.first_name, contact.last_name]
      .filter(Boolean)
      .join(" ") ||
    contact.email ||
    contact.phone ||
    "Unnamed contact"
  );
}

function customerProfileName(profile: CustomerProfile): string {
  const contact = profile.contact;

  return (
    [contact.first_name, contact.last_name]
      .filter(Boolean)
      .join(" ") ||
    contact.email ||
    contact.phone ||
    "Unnamed customer"
  );
}

interface LeadOption {
  lead: Lead;
  contact?: Contact;
}

export default function RequirementsPage() {
  const [items, setItems] = useState<CustomerRequirement[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);

  const [statusFilter, setStatusFilter] = useState<
    "" | RequirementStatus
  >("");

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);

  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [modalOpen, setModalOpen] = useState(false);
  const [requirement, setRequirement] =
    useState<CustomerRequirement | null>(null);

  const [locations, setLocations] =
    useState<RequirementLocation[]>([]);
  const [preferences, setPreferences] =
    useState<RequirementPropertyPreference[]>([]);
  const [possession, setPossession] =
    useState<RequirementPossessionParkingPreference | null>(null);
  const [association, setAssociation] =
    useState<RequirementAssociation | null>(null);

  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [customerProfiles, setCustomerProfiles] = useState<
    CustomerProfile[]
  >([]);

  const [leadSearch, setLeadSearch] = useState("");
  const [selectedLeadId, setSelectedLeadId] = useState("");
  const [customerProfileId, setCustomerProfileId] = useState("");

  const [budgetMin, setBudgetMin] = useState("");
  const [budgetMax, setBudgetMax] = useState("");

  const [city, setCity] = useState("");
  const [locality, setLocality] = useState("");
  const [propertyType, setPropertyType] =
    useState<PropertyType>("APARTMENT");
  const [bhkMin, setBhkMin] = useState("");
  const [bhkMax, setBhkMax] = useState("");

  const [possessionValue, setPossessionValue] =
    useState<PossessionPreference>("ANY");
  const [parkingValue, setParkingValue] =
    useState<ParkingPreference>("ANY");
  const [parkingSpaces, setParkingSpaces] = useState("");

  const contactsById = useMemo(
    () => new Map(contacts.map((contact) => [contact.id, contact])),
    [contacts],
  );

  const leadOptions = useMemo<LeadOption[]>(() => {
    const query = leadSearch.trim().toLowerCase();

    return leads
      .filter((lead) => lead.is_active)
      .map((lead) => ({
        lead,
        contact: contactsById.get(lead.contact_id),
      }))
      .filter(({ lead, contact }) => {
        if (!query) return true;

        return [
          contactName(contact),
          contact?.email ?? "",
          contact?.phone ?? "",
          lead.status,
          lead.interest ?? "",
        ]
          .join(" ")
          .toLowerCase()
          .includes(query);
      });
  }, [leads, contactsById, leadSearch]);

  const loadRequirements = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const result = await requirementsApi.list({
        page,
        page_size: PAGE_SIZE,
        ...(statusFilter ? { status: statusFilter } : {}),
      });

      setItems(result.items);
      setTotal(result.total);
      setTotalPages(result.total_pages);
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  useEffect(() => {
    void loadRequirements();
  }, [loadRequirements]);

  useEffect(() => {
    let cancelled = false;

    async function loadOptions() {
      try {
        const [leadResult, contactResult, customerProfileResult] =
          await Promise.all([
            leadsApi.list({
              page: 1,
              page_size: 100,
              is_active: true,
            }),
            contactsApi.list({
              page: 1,
              page_size: 100,
              is_active: true,
            }),
            customerProfilesApi.list({
              page: 1,
              page_size: 100,
              is_active: true,
            }),
          ]);

        if (!cancelled) {
          setLeads(leadResult.items);
          setContacts(contactResult.items);
          setCustomerProfiles(customerProfileResult.items);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(
            `Unable to load assignment options: ${getErrorMessage(loadError)}`,
          );
        }
      }
    }

    void loadOptions();

    return () => {
      cancelled = true;
    };
  }, []);

  // Lock the background page while the modal is open.
  useEffect(() => {
    if (!modalOpen) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving && !busy) {
        setModalOpen(false);
        setRequirement(null);
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [modalOpen, saving, busy]);

  const loadRequirement = useCallback(
    async (id: string): Promise<boolean> => {
      setBusy(true);
      setError("");
      setNotice("");

      try {
        const record = await requirementsApi.get(id);

        setRequirement(record);
        setBudgetMin(
          record.budget_min == null ? "" : String(record.budget_min),
        );
        setBudgetMax(
          record.budget_max == null ? "" : String(record.budget_max),
        );

        const [
          locationResult,
          preferenceResult,
          possessionResult,
          associationResult,
        ] = await Promise.allSettled([
          requirementsApi.listLocations(id),
          requirementsApi.listPropertyPreferences(id),
          requirementsApi.getPossessionParking(id),
          requirementsApi.getAssociation(id),
        ]);

        setLocations(
          locationResult.status === "fulfilled"
            ? locationResult.value
            : [],
        );
        setPreferences(
          preferenceResult.status === "fulfilled"
            ? preferenceResult.value
            : [],
        );

        const possessionRecord =
          possessionResult.status === "fulfilled"
            ? possessionResult.value
            : null;

        setPossession(possessionRecord);
        setPossessionValue(
          possessionRecord?.possession_preference ?? "ANY",
        );
        setParkingValue(
          possessionRecord?.parking_preference ?? "ANY",
        );
        setParkingSpaces(
          possessionRecord?.parking_spaces_min == null
            ? ""
            : String(possessionRecord.parking_spaces_min),
        );

        const associationRecord =
          associationResult.status === "fulfilled"
            ? associationResult.value
            : null;

        setAssociation(associationRecord);
        setSelectedLeadId(associationRecord?.lead_id ?? "");
        setCustomerProfileId(
          associationRecord?.customer_profile_id ?? "",
        );

        setLeadSearch("");
        setCity("");
        setLocality("");
        setPropertyType("APARTMENT");
        setBhkMin("");
        setBhkMax("");

        return true;
      } catch (loadError) {
        setError(getErrorMessage(loadError));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  async function openCreateModal() {
    setBusy(true);
    setError("");
    setNotice("");

    try {
      // This API creates the record before the details are entered.
      const created = await requirementsApi.create();
      const loaded = await loadRequirement(created.id);

      if (loaded) {
        setModalOpen(true);
        setNotice("Requirement created. Complete the details below.");
      } else {
        await loadRequirements();
      }
    } catch (createError) {
      setError(getErrorMessage(createError));
    } finally {
      setBusy(false);
    }
  }

  async function openEditModal(item: CustomerRequirement) {
    const loaded = await loadRequirement(item.id);
    if (loaded) setModalOpen(true);
  }

  function closeModal() {
    if (saving || busy) return;

    setModalOpen(false);
    setRequirement(null);
    setError("");
    setNotice("");

    void loadRequirements();
  }

  async function handleSaveCore(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!requirement) return;

    const minimum = optionalNumber(budgetMin);
    const maximum = optionalNumber(budgetMax);

    if (
      (budgetMin.trim() && minimum === null) ||
      (budgetMax.trim() && maximum === null)
    ) {
      setError("Enter valid budget amounts.");
      return;
    }

    if (
      (minimum !== null && minimum < 0) ||
      (maximum !== null && maximum < 0)
    ) {
      setError("Budget cannot be negative.");
      return;
    }

    if (
      minimum !== null &&
      maximum !== null &&
      minimum > maximum
    ) {
      setError("Minimum budget cannot exceed maximum budget.");
      return;
    }

    setSaving(true);
    setError("");

    try {
      // The backend's update endpoint is responsible for budget fields.
      const updated = await requirementsApi.update(requirement.id, {
        budget_min: minimum,
        budget_max: maximum,
        budget_currency: "INR",
      });

      setRequirement(updated);
      setNotice("Budget saved.");
      await loadRequirements();
    } catch (saveError) {
      setError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveAssociation(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    if (!requirement) return;

    setSaving(true);
    setError("");

    try {
      const input = {
        lead_id: selectedLeadId || null,
        customer_profile_id: customerProfileId.trim() || null,
      };

      const updated = association
        ? await requirementsApi.updateAssociation(
            requirement.id,
            input,
          )
        : await requirementsApi.createAssociation(
            requirement.id,
            input,
          );

      setAssociation(updated);
      setNotice("Customer assignment saved.");
    } catch (saveError) {
      setError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function handleAddLocation(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    if (!requirement) return;

    if (!city.trim() || !locality.trim()) {
      setError("Enter both city and locality.");
      return;
    }

    setSaving(true);
    setError("");

    try {
      await requirementsApi.createLocation(requirement.id, {
        city: city.trim(),
        locality: locality.trim(),
      });

      setCity("");
      setLocality("");
      setLocations(await requirementsApi.listLocations(requirement.id));
      setNotice("Preferred location added.");
    } catch (saveError) {
      setError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function toggleLocation(location: RequirementLocation) {
    if (!requirement) return;

    setSaving(true);
    setError("");

    try {
      await requirementsApi.updateLocation(
        requirement.id,
        location.id,
        { is_active: !location.is_active },
      );

      setLocations(await requirementsApi.listLocations(requirement.id));
      setNotice("Location updated.");
    } catch (saveError) {
      setError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function handleAddPreference(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    if (!requirement) return;

    const minimum = optionalNumber(bhkMin);
    const maximum = optionalNumber(bhkMax);

    if (
      (bhkMin.trim() &&
        (!Number.isInteger(minimum) || (minimum ?? 0) < 1)) ||
      (bhkMax.trim() &&
        (!Number.isInteger(maximum) || (maximum ?? 0) < 1))
    ) {
      setError("BHK values must be positive whole numbers.");
      return;
    }

    if (
      minimum !== null &&
      maximum !== null &&
      minimum > maximum
    ) {
      setError("Minimum BHK cannot exceed maximum BHK.");
      return;
    }

    setSaving(true);
    setError("");

    try {
      await requirementsApi.createPropertyPreference(
        requirement.id,
        {
          property_type: propertyType,
          bhk_min: minimum,
          bhk_max: maximum,
        },
      );

      setBhkMin("");
      setBhkMax("");
      setPreferences(
        await requirementsApi.listPropertyPreferences(requirement.id),
      );
      setNotice("Property preference added.");
    } catch (saveError) {
      setError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function togglePreference(
    preference: RequirementPropertyPreference,
  ) {
    if (!requirement) return;

    setSaving(true);
    setError("");

    try {
      await requirementsApi.updatePropertyPreference(
        requirement.id,
        preference.id,
        { is_active: !preference.is_active },
      );

      setPreferences(
        await requirementsApi.listPropertyPreferences(requirement.id),
      );
      setNotice("Property preference updated.");
    } catch (saveError) {
      setError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function handleSavePossession(
    event: FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    if (!requirement) return;

    const spaces = optionalNumber(parkingSpaces);

    if (
      parkingSpaces.trim() &&
      (!Number.isInteger(spaces) || (spaces ?? 0) < 1)
    ) {
      setError(
        "Minimum parking spaces must be a positive whole number.",
      );
      return;
    }

    setSaving(true);
    setError("");

    try {
      const input = {
        possession_preference: possessionValue,
        parking_preference: parkingValue,
        parking_spaces_min: spaces,
      };

      const updated = possession
        ? await requirementsApi.updatePossessionParking(
            requirement.id,
            input,
          )
        : await requirementsApi.createPossessionParking(
            requirement.id,
            input,
          );

      setPossession(updated);
      setNotice("Possession and parking preferences saved.");
    } catch (saveError) {
      setError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  const firstResult = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const lastResult = Math.min(page * PAGE_SIZE, total);

  return (
    <section className="requirements-page">
      <header className="requirements-header">
        <div>
          <span className="requirements-eyebrow">
            CUSTOMER WORKSPACE
          </span>
          <h1>Customer requirements</h1>
          <p className="requirements-subtitle">
            Manage customer property needs, budgets, locations, and
            preferences.
          </p>
        </div>

        <button
          className="requirements-primary-button"
          type="button"
          onClick={() => void openCreateModal()}
          disabled={busy || saving}
        >
          + New requirement
        </button>
      </header>

      <section
        className="requirements-summary"
        aria-label="Requirement summary"
      >
        <div className="requirements-summary-icon" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            width="22"
            height="22"
          >
            <path d="M4 5h16v14H4z" />
            <path d="M8 9h8M8 13h5" />
          </svg>
        </div>
        <div>
          <p className="requirements-summary-label">
            Matching requirements
          </p>
          <p className="requirements-summary-value">
            {loading && total === 0
              ? "—"
              : total.toLocaleString("en-IN")}
          </p>
        </div>
      </section>

      {error && !modalOpen && (
        <div
          className="requirements-alert requirements-alert-error"
          role="alert"
        >
          <span>{error}</span>
          <button
            className="requirements-dismiss"
            type="button"
            onClick={() => setError("")}
            aria-label="Dismiss error"
          >
            ×
          </button>
        </div>
      )}

      {notice && !modalOpen && (
        <div
          className="requirements-alert requirements-alert-success"
          role="status"
        >
          <span>{notice}</span>
          <button
            className="requirements-dismiss"
            type="button"
            onClick={() => setNotice("")}
            aria-label="Dismiss notice"
          >
            ×
          </button>
        </div>
      )}

      <section className="requirements-panel">
        <header className="requirements-panel-heading">
          <div>
            <h2>Customer requirement inventory</h2>
            <p>Review budgets and manage saved requirements.</p>
          </div>
          <button
            className="requirements-secondary-button"
            type="button"
            disabled={loading}
            onClick={() => void loadRequirements()}
          >
            {loading ? "Refreshing…" : "↻ Refresh"}
          </button>
        </header>

        <div className="requirements-toolbar">
          <div className="requirements-toolbar-description">
            <strong>Filter requirements</strong>
            <span>Choose which records appear in the table.</span>
          </div>

          <label className="requirements-filter">
            <span>Status</span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setPage(1);
                setStatusFilter(
                  event.target.value as "" | RequirementStatus,
                );
              }}
            >
              <option value="">All statuses</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Inactive</option>
            </select>
          </label>
        </div>

        <div className="requirements-table-wrap">
          <table className="requirements-table">
            <thead>
              <tr>
                <th>Requirement</th>
                <th>Budget range</th>
                <th>Status</th>
                <th>Last updated</th>
                <th className="requirements-actions-heading">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} className="requirements-table-message">
                    Loading requirements…
                  </td>
                </tr>
              ) : error ? (
                <tr>
                  <td colSpan={5} className="requirements-table-message">
                    Unable to load requirements.
                    <button
                      className="requirements-inline-button"
                      type="button"
                      onClick={() => void loadRequirements()}
                    >
                      Retry
                    </button>
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="requirements-table-message">
                    <div className="requirements-empty-icon">⌕</div>
                    <strong>No requirements yet</strong>
                    <p>
                      Create a requirement to capture a customer's
                      property needs.
                    </p>
                    <button
                      className="requirements-secondary-button"
                      type="button"
                      onClick={() => void openCreateModal()}
                    >
                      Create requirement
                    </button>
                  </td>
                </tr>
              ) : (
                items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <div className="requirements-record">
                        <span
                          className="requirements-record-icon"
                          aria-hidden="true"
                        >
                          ⌂
                        </span>
                        <div>
                          <strong>
                            Requirement #{item.id.slice(0, 8)}
                          </strong>
                          <span title={item.id}>{item.id}</span>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="requirements-budget">
                        <strong>
                          {formatCurrency(item.budget_min)}
                        </strong>
                        <span>
                          to {formatCurrency(item.budget_max)}
                        </span>
                      </div>
                    </td>
                    <td>
                      <span
                        className={`requirements-status ${
                          item.is_active
                            ? "is-active"
                            : "is-inactive"
                        }`}
                      >
                        <span className="requirements-status-dot" />
                        {item.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td>{formatDate(item.updated_at)}</td>
                    <td className="requirements-actions-cell">
                      <button
                        className="requirements-edit-button"
                        type="button"
                        disabled={busy || saving}
                        onClick={() => void openEditModal(item)}
                      >
                        View / Edit
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <footer className="requirements-pagination">
          <p>
            Showing <strong>{firstResult}–{lastResult}</strong> of{" "}
            <strong>{total}</strong> requirements
          </p>
          <div className="requirements-pagination-controls">
            <button
              className="requirements-page-button"
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => setPage((current) => current - 1)}
            >
              Previous
            </button>
            <span>
              Page {page}
              {totalPages > 0 ? ` of ${totalPages}` : ""}
            </span>
            <button
              className="requirements-page-button"
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
      </section>

      {modalOpen &&
        requirement &&
        createPortal(
          <div
            className="requirements-modal-backdrop"
            onMouseDown={(event) => {
              if (
                event.target === event.currentTarget &&
                !saving &&
                !busy
              ) {
                closeModal();
              }
            }}
          >
            <section
              className="requirements-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="requirements-modal-title"
            >
              <header className="requirements-modal-header">
                <div>
                  <span className="requirements-eyebrow">
                    REQUIREMENT DETAILS
                  </span>
                  <h2 id="requirements-modal-title">
                    Customer requirement
                  </h2>
                  <p>
                    Manage customer assignment, budget, locations, property
                    preferences, and move-in needs.
                  </p>
                </div>
                <button
                  className="requirements-modal-close"
                  type="button"
                  aria-label="Close form"
                  disabled={saving || busy}
                  onClick={closeModal}
                >
                  ×
                </button>
              </header>

              <div className="requirements-modal-content">
                <div className="requirements-form-body">
                  {error && (
                    <div
                      className="requirements-alert requirements-alert-error"
                      role="alert"
                    >
                      <span>{error}</span>
                      <button
                        type="button"
                        className="requirements-dismiss"
                        onClick={() => setError("")}
                        aria-label="Dismiss error"
                      >
                        ×
                      </button>
                    </div>
                  )}

                  {notice && (
                    <div
                      className="requirements-alert requirements-alert-success"
                      role="status"
                    >
                      <span>{notice}</span>
                      <button
                        type="button"
                        className="requirements-dismiss"
                        onClick={() => setNotice("")}
                        aria-label="Dismiss notice"
                      >
                        ×
                      </button>
                    </div>
                  )}

                  <h3 className="requirements-form-section-title">
                    Customer assignment
                  </h3>

                  <form
                    className="requirements-card"
                    onSubmit={(event) =>
                      void handleSaveAssociation(event)
                    }
                  >
                    <div className="requirements-form-grid">
                      <label className="requirements-form-field">
                        <span>Search active leads</span>
                        <input
                          type="search"
                          value={leadSearch}
                          disabled={saving}
                          onChange={(event) =>
                            setLeadSearch(event.target.value)
                          }
                          placeholder="Name, phone, email or status"
                        />
                      </label>

                      <label className="requirements-form-field">
                        <span>Select lead</span>
                        <select
                          value={selectedLeadId}
                          disabled={saving}
                          onChange={(event) =>
                            setSelectedLeadId(event.target.value)
                          }
                        >
                          <option value="">No lead selected</option>
                          {leadOptions.map(({ lead, contact }) => (
                            <option key={lead.id} value={lead.id}>
                              {contactName(contact)} ·{" "}
                              {formatLabel(lead.status)}
                            </option>
                          ))}
                        </select>
                        <small>
                          {leadOptions.length} matching active lead
                          {leadOptions.length === 1 ? "" : "s"}.
                        </small>
                      </label>

                      <label className="requirements-form-field requirements-field-full">
                        <span>Customer profile</span>
                        <select
                          value={customerProfileId}
                          disabled={saving || busy}
                          onChange={(event) => setCustomerProfileId(event.target.value)}
                        >
                          <option value="">No customer selected</option>

                          {customerProfiles.map((profile) => (
                            <option key={profile.id} value={profile.id}>
                              {customerProfileName(profile)}
                              {profile.contact.email ? ` · ${profile.contact.email}` : ""}
                            </option>
                          ))}
                        </select>

                        <small>
                          {customerProfiles.length === 0
                            ? "No active registered customers are available."
                            : `${customerProfiles.length} active registered customer${
                                customerProfiles.length === 1 ? "" : "s"
                              } available.`}
                        </small>
                      </label>
                    </div>

                    <div className="requirements-card-actions">
                      <button
                        className="requirements-primary-button"
                        type="submit"
                        disabled={saving}
                      >
                        {saving ? "Saving…" : "Save assignment"}
                      </button>
                    </div>
                  </form>

                  <h3 className="requirements-form-section-title">
                    Budget and status
                  </h3>

                  <form
                    className="requirements-card"
                    onSubmit={(event) => void handleSaveCore(event)}
                  >
                    <div className="requirements-form-grid">
                      <label className="requirements-form-field">
                        <span>Minimum budget (₹)</span>
                        <input
                          type="number"
                          min="0"
                          step="any"
                          value={budgetMin}
                          disabled={saving}
                          onChange={(event) =>
                            setBudgetMin(event.target.value)
                          }
                          placeholder="e.g. 2500000"
                        />
                        <small>
                          {formatCurrency(optionalNumber(budgetMin))}
                        </small>
                      </label>

                      <label className="requirements-form-field">
                        <span>Maximum budget (₹)</span>
                        <input
                          type="number"
                          min="0"
                          step="any"
                          value={budgetMax}
                          disabled={saving}
                          onChange={(event) =>
                            setBudgetMax(event.target.value)
                          }
                          placeholder="e.g. 5000000"
                        />
                        <small>
                          {formatCurrency(optionalNumber(budgetMax))}
                        </small>
                      </label>
                    </div>

                    <p className="requirements-form-hint">
                      The budget is saved in Indian rupees.
                    </p>

                    <div className="requirements-card-actions">
                      <button
                        className="requirements-primary-button"
                        type="submit"
                        disabled={saving}
                      >
                        {saving ? "Saving…" : "Save budget"}
                      </button>
                    </div>
                  </form>

                  <h3 className="requirements-form-section-title">
                    Preferred locations
                  </h3>

                  <section className="requirements-card">
                    <form onSubmit={(event) => void handleAddLocation(event)}>
                      <div className="requirements-form-grid">
                        <label className="requirements-form-field">
                          <span>City *</span>
                          <input
                            required
                            value={city}
                            disabled={saving}
                            onChange={(event) =>
                              setCity(event.target.value)
                            }
                            placeholder="e.g. Chennai"
                          />
                        </label>

                        <label className="requirements-form-field">
                          <span>Locality *</span>
                          <input
                            required
                            value={locality}
                            disabled={saving}
                            onChange={(event) =>
                              setLocality(event.target.value)
                            }
                            placeholder="e.g. Tambaram"
                          />
                        </label>
                      </div>

                      <div className="requirements-card-actions">
                        <button
                          className="requirements-secondary-button"
                          type="submit"
                          disabled={saving}
                        >
                          + Add location
                        </button>
                      </div>
                    </form>

                    <div className="requirements-list">
                      {locations.length === 0 ? (
                        <p className="requirements-muted">
                          No preferred locations added.
                        </p>
                      ) : (
                        locations.map((location) => (
                          <div
                            className="requirements-list-item"
                            key={location.id}
                          >
                            <div>
                              <strong>{location.locality}</strong>
                              <span>
                                {location.city}
                                {!location.is_active
                                  ? " · Inactive"
                                  : ""}
                              </span>
                            </div>
                            <button
                              className="requirements-text-button"
                              type="button"
                              disabled={saving}
                              onClick={() =>
                                void toggleLocation(location)
                              }
                            >
                              {location.is_active
                                ? "Deactivate"
                                : "Reactivate"}
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  </section>

                  <h3 className="requirements-form-section-title">
                    Property preferences
                  </h3>

                  <section className="requirements-card">
                    <form
                      onSubmit={(event) =>
                        void handleAddPreference(event)
                      }
                    >
                      <div className="requirements-form-grid">
                        <label className="requirements-form-field">
                          <span>Property type *</span>
                          <select
                            value={propertyType}
                            disabled={saving}
                            onChange={(event) =>
                              setPropertyType(
                                event.target.value as PropertyType,
                              )
                            }
                          >
                            {PROPERTY_TYPES.map((type) => (
                              <option key={type} value={type}>
                                {formatLabel(type)}
                              </option>
                            ))}
                          </select>
                        </label>

                        <label className="requirements-form-field">
                          <span>Minimum BHK</span>
                          <input
                            type="number"
                            min="1"
                            step="1"
                            value={bhkMin}
                            disabled={saving}
                            onChange={(event) =>
                              setBhkMin(event.target.value)
                            }
                            placeholder="Optional"
                          />
                        </label>

                        <label className="requirements-form-field">
                          <span>Maximum BHK</span>
                          <input
                            type="number"
                            min="1"
                            step="1"
                            value={bhkMax}
                            disabled={saving}
                            onChange={(event) =>
                              setBhkMax(event.target.value)
                            }
                            placeholder="Optional"
                          />
                        </label>
                      </div>

                      <div className="requirements-card-actions">
                        <button
                          className="requirements-secondary-button"
                          type="submit"
                          disabled={saving}
                        >
                          + Add property preference
                        </button>
                      </div>
                    </form>

                    <div className="requirements-list">
                      {preferences.length === 0 ? (
                        <p className="requirements-muted">
                          No property preferences added.
                        </p>
                      ) : (
                        preferences.map((preference) => (
                          <div
                            className="requirements-list-item"
                            key={preference.id}
                          >
                            <div>
                              <strong>
                                {formatLabel(preference.property_type)}
                              </strong>
                              <span>
                                {preference.bhk_min == null &&
                                preference.bhk_max == null
                                  ? "Any BHK"
                                  : `${preference.bhk_min ?? "Any"}–${
                                      preference.bhk_max ?? "Any"
                                    } BHK`}
                                {!preference.is_active
                                  ? " · Inactive"
                                  : ""}
                              </span>
                            </div>
                            <button
                              className="requirements-text-button"
                              type="button"
                              disabled={saving}
                              onClick={() =>
                                void togglePreference(preference)
                              }
                            >
                              {preference.is_active
                                ? "Deactivate"
                                : "Reactivate"}
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  </section>

                  <h3 className="requirements-form-section-title">
                    Possession and parking
                  </h3>

                  <form
                    className="requirements-card"
                    onSubmit={(event) =>
                      void handleSavePossession(event)
                    }
                  >
                    <div className="requirements-form-grid">
                      <label className="requirements-form-field">
                        <span>Possession timeline</span>
                        <select
                          value={possessionValue}
                          disabled={saving}
                          onChange={(event) =>
                            setPossessionValue(
                              event.target.value as PossessionPreference,
                            )
                          }
                        >
                          {POSSESSION_OPTIONS.map((option) => (
                            <option key={option} value={option}>
                              {formatLabel(option)}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="requirements-form-field">
                        <span>Parking preference</span>
                        <select
                          value={parkingValue}
                          disabled={saving}
                          onChange={(event) =>
                            setParkingValue(
                              event.target.value as ParkingPreference,
                            )
                          }
                        >
                          {PARKING_OPTIONS.map((option) => (
                            <option key={option} value={option}>
                              {formatLabel(option)}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="requirements-form-field">
                        <span>Minimum parking spaces</span>
                        <input
                          type="number"
                          min="1"
                          step="1"
                          value={parkingSpaces}
                          disabled={saving}
                          onChange={(event) =>
                            setParkingSpaces(event.target.value)
                          }
                          placeholder="Optional"
                        />
                      </label>
                    </div>

                    <div className="requirements-card-actions">
                      <button
                        className="requirements-primary-button"
                        type="submit"
                        disabled={saving}
                      >
                        {saving
                          ? "Saving…"
                          : "Save possession and parking"}
                      </button>
                    </div>
                  </form>
                </div>

                <footer className="requirements-form-actions">
                  <span>Changes are saved per section.</span>
                  <button
                    className="requirements-secondary-button"
                    type="button"
                    disabled={saving || busy}
                    onClick={closeModal}
                  >
                    Done
                  </button>
                </footer>
              </div>
            </section>
          </div>,
          document.body,
        )}
    </section>
  );
}

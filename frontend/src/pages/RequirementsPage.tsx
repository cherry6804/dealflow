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
  type RequirementPropertyMatchResult,
  type RequirementShortlistItem,
} from "../services/requirementApi";
import "./RequirementsPage.css";
import {
  propertiesApi,
  type Property,
} from "../services/propertyApi";
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
    [contact.first_name, contact.last_name].filter(Boolean).join(" ") ||
    contact.email ||
    contact.phone ||
    "Unnamed contact"
  );
}

function customerProfileName(profile: CustomerProfile): string {
  const contact = profile.contact;

  return (
    [contact.first_name, contact.last_name].filter(Boolean).join(" ") ||
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

  const [statusFilter, setStatusFilter] = useState<"" | RequirementStatus>("");

  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);

  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [modalOpen, setModalOpen] = useState(false);
  const [requirement, setRequirement] = useState<CustomerRequirement | null>(
    null,
  );

  const [locations, setLocations] = useState<RequirementLocation[]>([]);
  const [preferences, setPreferences] = useState<
    RequirementPropertyPreference[]
  >([]);
  const [possession, setPossession] =
    useState<RequirementPossessionParkingPreference | null>(null);
  const [association, setAssociation] = useState<RequirementAssociation | null>(
    null,
  );

  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [customerProfiles, setCustomerProfiles] = useState<CustomerProfile[]>(
    [],
  );

  const [shortlist, setShortlist] = useState<RequirementShortlistItem[]>([]);
  const [shortlistLoading, setShortlistLoading] = useState(false);

  const [propertySearch, setPropertySearch] = useState("");
  const [propertyResults, setPropertyResults] = useState<Property[]>([]);
  const [propertySearchLoading, setPropertySearchLoading] = useState(false);
  const [propertySearchError, setPropertySearchError] = useState("");
  const [shortlistActionId, setShortlistActionId] = useState("");

  const [matchRunHistory, setMatchRunHistory] = useState<
    import("../services/requirementApi").RequirementMatchRunSummary[]
  >([]);
  const [matchHistoryLoading, setMatchHistoryLoading] = useState(false);
  const [matchHistoryError, setMatchHistoryError] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [historicalResults, setHistoricalResults] = useState<
    import("../services/requirementApi").RequirementMatchRunResult[]
  >([]);
  const [historicalResultsLoading, setHistoricalResultsLoading] =
    useState(false);
  const [historicalResultsError, setHistoricalResultsError] = useState("");

  const [shortlistEvents, setShortlistEvents] = useState<
    import("../services/requirementApi").RequirementShortlistEvent[]
  >([]);
  const [shortlistEventsLoading, setShortlistEventsLoading] = useState(false);
  const [shortlistEventsError, setShortlistEventsError] = useState("");

  const [matchingProperties, setMatchingProperties] = useState<Property[]>([]);
  const [matchResults, setMatchResults] = useState<
    RequirementPropertyMatchResult[]
  >([]);
  const [matchingLoading, setMatchingLoading] = useState(false);
  const [matchingError, setMatchingError] = useState("");
  const [matchingLoaded, setMatchingLoaded] = useState(false);

  const [leadSearch, setLeadSearch] = useState("");
  const [selectedLeadId, setSelectedLeadId] = useState("");
  const [customerProfileId, setCustomerProfileId] = useState("");

  const [budgetMin, setBudgetMin] = useState("");
  const [budgetMax, setBudgetMax] = useState("");

  const [city, setCity] = useState("");
  const [locality, setLocality] = useState("");
  const [propertyType, setPropertyType] = useState<PropertyType>("APARTMENT");
  const [bhkMin, setBhkMin] = useState("");
  const [bhkMax, setBhkMax] = useState("");

  const [possessionValue, setPossessionValue] =
    useState<PossessionPreference>("ANY");
  const [parkingValue, setParkingValue] = useState<ParkingPreference>("ANY");
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
    let cancelled = false;

    async function fetchRequirements() {
      try {
        const result = await requirementsApi.list({
          page,
          page_size: PAGE_SIZE,
          ...(statusFilter ? { status: statusFilter } : {}),
        });

        if (!cancelled) {
          setItems(result.items);
          setTotal(result.total);
          setTotalPages(result.total_pages);
          setError("");
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(getErrorMessage(loadError));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void fetchRequirements();

    return () => {
      cancelled = true;
    };
  }, [page, statusFilter]);

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


  const loadRequirement = useCallback(async (id: string): Promise<boolean> => {
    setBusy(true);
    setError("");
    setNotice("");
    setShortlistLoading(true);

    try {
      const record = await requirementsApi.get(id);

      setRequirement(record);
      setBudgetMin(record.budget_min == null ? "" : String(record.budget_min));
      setBudgetMax(record.budget_max == null ? "" : String(record.budget_max));

      const [
        locationResult,
        preferenceResult,
        possessionResult,
        associationResult,
        shortlistResult,
      ] = await Promise.allSettled([
        requirementsApi.listLocations(id),
        requirementsApi.listPropertyPreferences(id),
        requirementsApi.getPossessionParking(id),
        requirementsApi.getAssociation(id),
        requirementsApi.listShortlist(id),
      ]);

      setLocations(
        locationResult.status === "fulfilled" ? locationResult.value : [],
      );

      setPreferences(
        preferenceResult.status === "fulfilled" ? preferenceResult.value : [],
      );

      if (shortlistResult.status === "fulfilled") {
        setShortlist(shortlistResult.value.items);
      } else {
        setShortlist([]);
      }

      const possessionRecord =
        possessionResult.status === "fulfilled"
          ? possessionResult.value
          : null;

      setPossession(possessionRecord);
      setPossessionValue(possessionRecord?.possession_preference ?? "ANY");
      setParkingValue(possessionRecord?.parking_preference ?? "ANY");
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
      setCustomerProfileId(associationRecord?.customer_profile_id ?? "");

      setLeadSearch("");
      setCity("");
      setLocality("");
      setPropertyType("APARTMENT");
      setBhkMin("");
      setBhkMax("");

      setPropertySearch("");
      setPropertyResults([]);
      setPropertySearchError("");
      setMatchingProperties([]);
      setMatchResults([]);
      setMatchingError("");
      setMatchingLoaded(false);

      setMatchRunHistory([]);
      setMatchHistoryError("");
      setSelectedRunId("");
      setHistoricalResults([]);
      setHistoricalResultsError("");

      setShortlistEvents([]);
      setShortlistEventsError("");

      void loadMatchHistory(id);
      void loadShortlistActivity(id);

      return true;
    } catch (loadError) {
      setError(getErrorMessage(loadError));
      return false;
    } finally {
      setBusy(false);
      setShortlistLoading(false);
    }
  }, []);


  async function handleSearchProperties(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPropertySearchLoading(true);
    setPropertySearchError("");

    try {
      const result = await propertiesApi.search({
        q: propertySearch.trim() || undefined,
        status: "AVAILABLE",
        page: 1,
        page_size: 10,
      });

      setPropertyResults(result.items);
    } catch (searchError) {
      setPropertySearchError(getErrorMessage(searchError));
      setPropertyResults([]);
    } finally {
      setPropertySearchLoading(false);
    }
  }

  
  async function handleFindMatches() {
    if (!requirement || matchingLoading) return;

    setMatchingLoading(true);
    setMatchingError("");

    try {
      // This executes matching and saves an immutable history record.
      const run = await requirementsApi.recordMatchRun(requirement.id);

      const properties = run.results.map((result) => ({
        ...result.property_snapshot,
        id: result.property_id,
      })) as unknown as Property[];

      const explanations: RequirementPropertyMatchResult[] =
        run.results.map((result) => {
          const snapshot = result.property_snapshot;
          const criteria = result.criteria_results_snapshot.map(
            (criterion) => ({
              criterion: String(criterion.criterion ?? "LOCATION") as
                RequirementPropertyMatchResult["criteria"][number]["criterion"],
              status: String(criterion.status ?? "UNKNOWN") as
                RequirementPropertyMatchResult["criteria"][number]["status"],
              explanation: String(criterion.explanation ?? ""),
            }),
          );

          return {
            property: {
              ...snapshot,
              id: result.property_id,
            } as unknown as Property,
            overall_match: result.overall_match,
            criteria,
          };
        });

      setMatchingProperties(properties);
      setMatchResults(explanations);
      setMatchingLoaded(true);

      try {
        const history = await requirementsApi.listMatchRuns(requirement.id);
        setMatchRunHistory(history.items);
        setMatchHistoryError("");
      } catch (historyError) {
        setMatchHistoryError(getErrorMessage(historyError));
      }
    } catch (matchError) {
      setMatchingError(getErrorMessage(matchError));
      setMatchingProperties([]);
      setMatchResults([]);
      setMatchingLoaded(false);
    } finally {
      setMatchingLoading(false);
    }
  }

  async function loadMatchHistory(requirementId: string) {
    setMatchHistoryLoading(true);
    setMatchHistoryError("");

    try {
      const result = await requirementsApi.listMatchRuns(requirementId);
      setMatchRunHistory(result.items);
    } catch (error) {
      setMatchHistoryError(getErrorMessage(error));
    } finally {
      setMatchHistoryLoading(false);
    }
  }

  async function handleViewHistoricalResults(runId: string) {
    if (!requirement) return;

    setSelectedRunId(runId);
    setHistoricalResultsLoading(true);
    setHistoricalResultsError("");
    setHistoricalResults([]);

    try {
      const results = await requirementsApi.getMatchRunResults(
        requirement.id,
        runId,
      );
      setHistoricalResults(results);
    } catch (error) {
      setHistoricalResultsError(getErrorMessage(error));
    } finally {
      setHistoricalResultsLoading(false);
    }
  }

  async function loadShortlistActivity(requirementId: string) {
    setShortlistEventsLoading(true);
    setShortlistEventsError("");

    try {
      const result = await requirementsApi.listShortlistEvents(requirementId);
      setShortlistEvents(result.items);
    } catch (error) {
      setShortlistEventsError(getErrorMessage(error));
    } finally {
      setShortlistEventsLoading(false);
    }
  }

  async function handleAddToShortlist(property: Property) {
    if (!requirement || shortlistActionId) return;

    if (shortlist.some((item) => item.property.id === property.id)) {
      setNotice("This property is already shortlisted.");
      return;
    }

    setShortlistActionId(property.id);
    setError("");
    setNotice("");

    try {
      await requirementsApi.addToShortlist(requirement.id, property.id);

      const result = await requirementsApi.listShortlist(requirement.id);
      setShortlist(result.items);
      await loadShortlistActivity(requirement.id);
      setNotice("Property added to the shortlist.");
    } catch (actionError) {
      setError(getErrorMessage(actionError));
    } finally {
      setShortlistActionId("");
    }
  }

  async function handleRemoveFromShortlist(propertyId: string) {
    if (!requirement || shortlistActionId) return;

    setShortlistActionId(propertyId);
    setError("");
    setNotice("");

    try {
      await requirementsApi.removeFromShortlist(requirement.id, propertyId);
      await loadShortlistActivity(requirement.id);
      
      setShortlist((current) =>
        current.filter((item) => item.property.id !== propertyId),
      );

      setNotice("Property removed from the shortlist.");
    } catch (actionError) {
      setError(getErrorMessage(actionError));
    } finally {
      setShortlistActionId("");
    }
  }


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

    if (minimum !== null && maximum !== null && minimum > maximum) {
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

  async function handleSaveAssociation(event: FormEvent<HTMLFormElement>) {
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
        ? await requirementsApi.updateAssociation(requirement.id, input)
        : await requirementsApi.createAssociation(requirement.id, input);

      setAssociation(updated);
      setNotice("Customer assignment saved.");
      await loadRequirements();
    } catch (saveError) {
      setError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function handleAddLocation(event: FormEvent<HTMLFormElement>) {
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
      await requirementsApi.updateLocation(requirement.id, location.id, {
        is_active: !location.is_active,
      });

      setLocations(await requirementsApi.listLocations(requirement.id));
      setNotice("Location updated.");
    } catch (saveError) {
      setError(getErrorMessage(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function handleAddPreference(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!requirement) return;

    const minimum = optionalNumber(bhkMin);
    const maximum = optionalNumber(bhkMax);

    if (
      (bhkMin.trim() && (!Number.isInteger(minimum) || (minimum ?? 0) < 1)) ||
      (bhkMax.trim() && (!Number.isInteger(maximum) || (maximum ?? 0) < 1))
    ) {
      setError("BHK values must be positive whole numbers.");
      return;
    }

    if (minimum !== null && maximum !== null && minimum > maximum) {
      setError("Minimum BHK cannot exceed maximum BHK.");
      return;
    }

    setSaving(true);
    setError("");

    try {
      await requirementsApi.createPropertyPreference(requirement.id, {
        property_type: propertyType,
        bhk_min: minimum,
        bhk_max: maximum,
      });

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

  async function togglePreference(preference: RequirementPropertyPreference) {
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

  async function handleSavePossession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!requirement) return;

    const spaces = optionalNumber(parkingSpaces);

    if (
      parkingSpaces.trim() &&
      (!Number.isInteger(spaces) || (spaces ?? 0) < 1)
    ) {
      setError("Minimum parking spaces must be a positive whole number.");
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
        ? await requirementsApi.updatePossessionParking(requirement.id, input)
        : await requirementsApi.createPossessionParking(requirement.id, input);

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
          <span className="requirements-eyebrow">CUSTOMER WORKSPACE</span>
          <h1>Customer requirements</h1>
          <p className="requirements-subtitle">
            Manage customer property needs, budgets, locations, and preferences.
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
          <p className="requirements-summary-label">Matching requirements</p>
          <p className="requirements-summary-value">
            {loading && total === 0 ? "—" : total.toLocaleString("en-IN")}
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
                setStatusFilter(event.target.value as "" | RequirementStatus);
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
                <th>Customer / Requirement</th>
                <th>Budget range</th>
                <th>Status</th>
                <th>Last updated</th>
                <th className="requirements-actions-heading">Actions</th>
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
                      Create a requirement to capture a customer's property
                      needs.
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
                            {item.customer_name?.trim() || "Customer not assigned"}
                          </strong>

                          {item.customer_email && (
                            <span>{item.customer_email}</span>
                          )}

                          {item.customer_phone && (
                            <span>{item.customer_phone}</span>
                          )}

                          <span title={item.id}>
                            REQ-{item.id.replace(/-/g, "").slice(0, 8).toUpperCase()}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td>
                      <div className="requirements-budget">
                        <strong>{formatCurrency(item.budget_min)}</strong>
                        <span>to {formatCurrency(item.budget_max)}</span>
                      </div>
                    </td>
                    <td>
                      <span
                        className={`requirements-status ${
                          item.is_active ? "is-active" : "is-inactive"
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
            Showing{" "}
            <strong>
              {firstResult}–{lastResult}
            </strong>{" "}
            of <strong>{total}</strong> requirements
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
              disabled={page >= totalPages || totalPages === 0 || loading}
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
              if (event.target === event.currentTarget && !saving && !busy) {
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
                  <h2 id="requirements-modal-title">Customer requirement</h2>
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
                    onSubmit={(event) => void handleSaveAssociation(event)}
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
                          onChange={(event) =>
                            setCustomerProfileId(event.target.value)
                          }
                        >
                          <option value="">No customer selected</option>

                          {customerProfiles.map((profile) => (
                            <option key={profile.id} value={profile.id}>
                              {customerProfileName(profile)}
                              {profile.contact.email
                                ? ` · ${profile.contact.email}`
                                : ""}
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
                          onChange={(event) => setBudgetMin(event.target.value)}
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
                          onChange={(event) => setBudgetMax(event.target.value)}
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
                            onChange={(event) => setCity(event.target.value)}
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
                                {!location.is_active ? " · Inactive" : ""}
                              </span>
                            </div>
                            <button
                              className="requirements-text-button"
                              type="button"
                              disabled={saving}
                              onClick={() => void toggleLocation(location)}
                            >
                              {location.is_active ? "Deactivate" : "Reactivate"}
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
                    <form onSubmit={(event) => void handleAddPreference(event)}>
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
                            onChange={(event) => setBhkMin(event.target.value)}
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
                            onChange={(event) => setBhkMax(event.target.value)}
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
                                {!preference.is_active ? " · Inactive" : ""}
                              </span>
                            </div>
                            <button
                              className="requirements-text-button"
                              type="button"
                              disabled={saving}
                              onClick={() => void togglePreference(preference)}
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
                    Property matching
                  </h3>

                  <section className="requirements-card">
                    <p className="requirements-form-hint">
                      Find properties that match this customer's saved location,
                      property type, BHK, and budget requirements. Review the
                      criterion explanations before proposing a property.
                    </p>

                    <div className="requirements-card-actions">
                      <button
                        className="requirements-primary-button"
                        type="button"
                        disabled={saving || busy || matchingLoading}
                        onClick={() => void handleFindMatches()}
                      >
                        {matchingLoading ? "Finding matches…" : "Find matches"}
                      </button>
                    </div>

                    {matchingError && (
                      <div
                        className="requirements-alert requirements-alert-error"
                        role="alert"
                      >
                        {matchingError}
                      </div>
                    )}

                    {matchingLoaded && (
                      <>
                        <h4>
                          Matching properties ({matchingProperties.length})
                        </h4>

                        {matchingProperties.length === 0 ? (
                          <p className="requirements-muted">
                            No qualifying properties were found. Review the
                            saved requirement criteria and available properties.
                          </p>
                        ) : (
                          <div className="requirements-list">
                            {matchingProperties.map((property) => {
                              const location = [
                                property.locality,
                                property.city,
                                property.state,
                              ]
                                .filter(Boolean)
                                .join(", ");

                              const price =
                                property.transaction_type === "RENT" ||
                                property.transaction_type === "LEASE"
                                  ? property.rent ?? property.price
                                  : property.price;

                              return (
                                <div
                                  className="requirements-list-item"
                                  key={property.id}
                                >
                                  <div>
                                    <strong>
                                      {property.bhk ? `${property.bhk} BHK ` : ""}
                                      {property.property_type
                                        ? formatLabel(property.property_type)
                                        : "Property"}
                                    </strong>

                                    <span>
                                      {location || "Location not provided"}
                                    </span>

                                    <span>
                                      {property.transaction_type
                                        ? formatLabel(property.transaction_type)
                                        : "Transaction unspecified"}
                                      {" · "}
                                      {formatCurrency(price)}
                                    </span>
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}

                        <h4>Criterion explanations</h4>

                        {matchResults.length === 0 ? (
                          <p className="requirements-muted">
                            No criterion explanations were returned by the matching API.
                          </p>
                        ) : (
                          <div className="requirements-list">
                            {matchResults.map((result) => (
                              <div
                                className="requirements-list-item"
                                key={result.property.id}
                              >
                                <div>
                                  <strong>
                                    {result.property.bhk
                                      ? `${result.property.bhk} BHK `
                                      : ""}
                                    {result.property.property_type
                                      ? formatLabel(result.property.property_type)
                                      : "Property"}
                                  </strong>

                                  <span>
                                    Overall result:{" "}
                                    {result.overall_match
                                      ? "Matching"
                                      : "Does not qualify as a full match"}
                                  </span>

                                  {result.criteria.map((criterion) => (
                                    <span key={criterion.criterion}>
                                      <strong>
                                        {formatLabel(criterion.criterion)}:{" "}
                                        {formatLabel(criterion.status)}
                                      </strong>
                                      {" — "}
                                      {criterion.explanation}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </section>


                  <h3 className="requirements-form-section-title">
                    Match run history
                  </h3>

                  <section className="requirements-card">
                    <p className="requirements-form-hint">
                      Review previous matching runs and inspect their saved
                      results without running matching again.
                    </p>

                    {matchHistoryLoading ? (
                      <p className="requirements-muted">
                        Loading match history…
                      </p>
                    ) : matchHistoryError ? (
                      <div className="requirements-alert requirements-alert-error">
                        {matchHistoryError}
                        <button
                          className="requirements-text-button"
                          type="button"
                          onClick={() => void loadMatchHistory(requirement.id)}
                        >
                          Retry
                        </button>
                      </div>
                    ) : matchRunHistory.length === 0 ? (
                      <p className="requirements-muted">
                        No matching runs recorded yet. Select Find matches
                        to create the first run.
                      </p>
                    ) : (
                      <div className="requirements-list">
                        {matchRunHistory.map((run) => (
                          <div className="requirements-list-item" key={run.id}>
                            <div>
                              <strong>
                                Run on{" "}
                                {new Date(run.created_at).toLocaleString("en-IN")}
                              </strong>
                              <span>
                                Candidates: {run.total_candidates} · Matches:{" "}
                                {run.matched_candidates}
                              </span>
                            </div>

                            <button
                              className="requirements-text-button"
                              type="button"
                              disabled={historicalResultsLoading}
                              onClick={() =>
                                void handleViewHistoricalResults(run.id)
                              }
                            >
                              {historicalResultsLoading &&
                              selectedRunId === run.id
                                ? "Loading…"
                                : selectedRunId === run.id
                                  ? "Reload results"
                                  : "View saved results"}
                            </button>
                          </div>
                        ))}
                      </div>
                    )}

                    {historicalResultsError && (
                      <div
                        className="requirements-alert requirements-alert-error"
                        role="alert"
                      >
                        {historicalResultsError}
                      </div>
                    )}

                    {selectedRunId && !historicalResultsLoading &&
                      !historicalResultsError && (
                        <>
                          <h4>Saved results ({historicalResults.length})</h4>

                          {historicalResults.length === 0 ? (
                            <p className="requirements-muted">
                              This run has no saved results.
                            </p>
                          ) : (
                            <div className="requirements-list">
                              {historicalResults.map((result) => {
                                const snapshot = result.property_snapshot;
                                const location = [
                                  snapshot.locality,
                                  snapshot.city,
                                  snapshot.state,
                                ]
                                  .filter(
                                    (value) =>
                                      typeof value === "string" && value,
                                  )
                                  .join(", ");

                                return (
                                  <div
                                    className="requirements-list-item"
                                    key={result.id}
                                  >
                                    <div>
                                      <strong>
                                        {typeof snapshot.property_type === "string"
                                          ? formatLabel(snapshot.property_type)
                                          : "Property"}
                                      </strong>
                                      <span>
                                        {location || "Location not provided"}
                                      </span>
                                      <span>
                                        Result:{" "}
                                        {result.overall_match
                                          ? "Matching"
                                          : "Not a full match"}
                                      </span>
                                      <span>
                                        Property ID: {result.property_id}
                                      </span>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </>
                      )}
                  </section>

                  <h3 className="requirements-form-section-title">
                    Shortlist activity
                  </h3>

                  <section className="requirements-card">
                    <p className="requirements-form-hint">
                      Review the history of properties added to or removed
                      from this requirement's shortlist.
                    </p>

                    {shortlistEventsLoading ? (
                      <p className="requirements-muted">
                        Loading shortlist activity…
                      </p>
                    ) : shortlistEventsError ? (
                      <div className="requirements-alert requirements-alert-error">
                        {shortlistEventsError}
                        <button
                          className="requirements-text-button"
                          type="button"
                          onClick={() =>
                            void loadShortlistActivity(requirement.id)
                          }
                        >
                          Retry
                        </button>
                      </div>
                    ) : shortlistEvents.length === 0 ? (
                      <p className="requirements-muted">
                        No shortlist activity recorded yet.
                      </p>
                    ) : (
                      <div className="requirements-list">
                        {shortlistEvents.map((event) => {
                          const snapshot = event.property_snapshot;
                          const propertyType = snapshot.property_type;

                          return (
                            <div
                              className="requirements-list-item"
                              key={event.id}
                            >
                              <div>
                                <strong>
                                  {event.event_type === "ADDED"
                                    ? "Property added"
                                    : "Property removed"}
                                </strong>
                                <span>
                                  {typeof propertyType === "string"
                                    ? formatLabel(propertyType)
                                    : "Property"}
                                  {" · "}
                                  {event.property_id}
                                </span>
                                <small>
                                  {new Date(event.created_at).toLocaleString(
                                    "en-IN",
                                  )}
                                </small>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </section>


                  <h3 className="requirements-form-section-title">
                    Manual property shortlist
                  </h3>

                  <section className="requirements-card">
                    <p className="requirements-form-hint">
                      Search available properties and select the listings
                      you want to propose for this customer requirement.
                    </p>

                    <form onSubmit={(event) => void handleSearchProperties(event)}>
                      <div className="requirements-form-grid">
                        <label className="requirements-form-field requirements-field-full">
                          <span>Search properties</span>
                          <input
                            type="search"
                            value={propertySearch}
                            disabled={saving || busy || propertySearchLoading}
                            onChange={(event) =>
                              setPropertySearch(event.target.value)
                            }
                            placeholder="Address, locality, city or postal code"
                          />
                        </label>
                      </div>

                      <div className="requirements-card-actions">
                        <button
                          className="requirements-secondary-button"
                          type="submit"
                          disabled={saving || busy || propertySearchLoading}
                        >
                          {propertySearchLoading
                            ? "Searching…"
                            : "Search available properties"}
                        </button>
                      </div>
                    </form>

                    {propertySearchError && (
                      <div
                        className="requirements-alert requirements-alert-error"
                        role="alert"
                      >
                        {propertySearchError}
                      </div>
                    )}

                    {propertyResults.length > 0 && (
                      <div className="requirements-list">
                        {propertyResults.map((property) => {
                          const alreadyShortlisted = shortlist.some(
                            (item) => item.property.id === property.id,
                          );

                          const location = [
                            property.locality,
                            property.city,
                            property.state,
                          ]
                            .filter(Boolean)
                            .join(", ");

                          const price =
                            property.transaction_type === "RENT" ||
                            property.transaction_type === "LEASE"
                              ? property.rent ?? property.price
                              : property.price;

                          return (
                            <div
                              className="requirements-list-item"
                              key={property.id}
                            >
                              <div>
                                <strong>
                                  {property.bhk ? `${property.bhk} BHK ` : ""}
                                  {property.property_type
                                    ? formatLabel(property.property_type)
                                    : "Property"}
                                </strong>
                                <span>
                                  {location || "Location not provided"}
                                </span>
                                <span>
                                  {property.transaction_type
                                    ? formatLabel(property.transaction_type)
                                    : "Transaction unspecified"}
                                  {" · "}
                                  {formatCurrency(price)}
                                </span>
                              </div>

                              <button
                                className="requirements-text-button"
                                type="button"
                                disabled={
                                  saving ||
                                  busy ||
                                  shortlistActionId === property.id ||
                                  alreadyShortlisted
                                }
                                onClick={() =>
                                  void handleAddToShortlist(property)
                                }
                              >
                                {alreadyShortlisted
                                  ? "Shortlisted"
                                  : shortlistActionId === property.id
                                    ? "Adding…"
                                    : "Add to shortlist"}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {!propertySearchLoading &&
                      propertyResults.length === 0 &&
                      !propertySearchError && (
                        <p className="requirements-muted">
                          Search to find available properties. Results will
                          appear here.
                        </p>
                      )}

                    <h4>Shortlisted properties ({shortlist.length})</h4>

                    {shortlistLoading ? (
                      <p className="requirements-muted">
                        Loading shortlisted properties…
                      </p>
                    ) : shortlist.length === 0 ? (
                      <p className="requirements-muted">
                        No properties have been shortlisted for this requirement.
                      </p>
                    ) : (
                      <div className="requirements-list">
                        {shortlist.map((item) => {
                          const property = item.property;
                          const location = [
                            property.locality,
                            property.city,
                            property.state,
                          ]
                            .filter(Boolean)
                            .join(", ");

                          const price =
                            property.transaction_type === "RENT" ||
                            property.transaction_type === "LEASE"
                              ? property.rent ?? property.price
                              : property.price;

                          return (
                            <div
                              className="requirements-list-item"
                              key={property.id}
                            >
                              <div>
                                <strong>
                                  {property.bhk ? `${property.bhk} BHK ` : ""}
                                  {property.property_type
                                    ? formatLabel(property.property_type)
                                    : "Property"}
                                </strong>
                                <span>
                                  {location || "Location not provided"}
                                </span>
                                <span>
                                  {property.transaction_type
                                    ? formatLabel(property.transaction_type)
                                    : "Transaction unspecified"}
                                  {" · "}
                                  {formatCurrency(price)}
                                </span>
                                <small>
                                  Added {formatDate(item.created_at)}
                                </small>
                              </div>

                              <button
                                className="requirements-text-button"
                                type="button"
                                disabled={
                                  saving ||
                                  busy ||
                                  shortlistActionId === property.id
                                }
                                onClick={() =>
                                  void handleRemoveFromShortlist(property.id)
                                }
                              >
                                {shortlistActionId === property.id
                                  ? "Removing…"
                                  : "Remove"}
                              </button>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </section>


                  <h3 className="requirements-form-section-title">
                    Possession and parking
                  </h3>

                  <form
                    className="requirements-card"
                    onSubmit={(event) => void handleSavePossession(event)}
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
                        {saving ? "Saving…" : "Save possession and parking"}
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

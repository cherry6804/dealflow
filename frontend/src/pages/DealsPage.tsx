
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
import {
  customerProfilesApi,
  type CustomerProfile,
} from "../services/customerProfileApi";
import {
  dealNegotiationsApi,
  dealsApi,
  type Deal,
  type DealStage,
  type DealNegotiation,
  type NegotiationHistoryItem,
  type NegotiationState,
} from "../services/dealApi";
import {
  propertiesApi,
  type Property,
} from "../services/propertyApi";
import PaymentMilestonesPanel from "../components/PaymentMilestonesPanel";
import DealCommissionsPanel from "../components/DealCommissionsPanel";

import "./DealsPage.css";

const PAGE_SIZE = 100;

const DEAL_STAGES: DealStage[] = [
  "NEW",
  "QUALIFICATION",
  "NEGOTIATION",
  "BOOKING",
  "CLOSED_WON",
  "CLOSED_LOST",
];

const NEXT_DEAL_STAGE: Partial<Record<DealStage, DealStage>> = {
  NEW: "QUALIFICATION",
  QUALIFICATION: "NEGOTIATION",
  NEGOTIATION: "BOOKING",
};

const NEGOTIATION_TRANSITIONS: Record<
  NegotiationState,
  NegotiationState[]
> = {
  IN_PROGRESS: [
    "WAITING_ON_CUSTOMER",
    "WAITING_ON_SELLER",
    "TERMS_AGREED",
    "STALLED",
    "CANCELLED",
  ],
  WAITING_ON_CUSTOMER: [
    "IN_PROGRESS",
    "WAITING_ON_SELLER",
    "TERMS_AGREED",
    "STALLED",
    "CANCELLED",
  ],
  WAITING_ON_SELLER: [
    "IN_PROGRESS",
    "WAITING_ON_CUSTOMER",
    "TERMS_AGREED",
    "STALLED",
    "CANCELLED",
  ],
  STALLED: [
    "IN_PROGRESS",
    "WAITING_ON_CUSTOMER",
    "WAITING_ON_SELLER",
    "TERMS_AGREED",
    "CANCELLED",
  ],
  TERMS_AGREED: ["IN_PROGRESS", "COMPLETED", "CANCELLED"],
  COMPLETED: ["IN_PROGRESS"],
  CANCELLED: ["IN_PROGRESS"],
};


const NEGOTIATION_COMMENTS: Record<NegotiationState, string[]> = {
  IN_PROGRESS: [
    "Initial discussion started",
    "Negotiation discussion resumed",
    "New offer received",
    "Counteroffer discussed",
    "Customer requested an alternative property",
    "Terms under discussion",
  ],
  WAITING_ON_CUSTOMER: [
    "Customer reviewing the offer",
    "Waiting for customer response",
    "Customer requested more time",
    "Waiting for customer documents",
    "Customer comparing properties",
  ],
  WAITING_ON_SELLER: [
    "Offer shared with seller",
    "Waiting for seller approval",
    "Seller reviewing the offer",
    "Waiting for revised seller price",
    "Seller requested more time",
  ],
  TERMS_AGREED: [
    "Price agreed",
    "Commercial terms agreed",
    "Final terms confirmed",
    "Documentation pending",
  ],
  STALLED: [
    "Price mismatch",
    "Customer not responding",
    "Seller not responding",
    "Budget or financing concern",
    "Decision postponed",
  ],
  COMPLETED: [
    "Negotiation successfully concluded",
    "Terms finalized for handover",
  ],
  CANCELLED: [
    "Customer withdrew interest",
    "Price expectations could not be aligned",
    "Seller withdrew the property",
    "Customer selected another property",
    "Deal no longer proceeding",
  ],
};


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

async function fetchAllDeals(stage?: DealStage): Promise<Deal[]> {
  const firstPage = await dealsApi.list({
    page: 1,
    page_size: PAGE_SIZE,
    stage,
  });

  const allDeals = [...firstPage.items];

  for (let currentPage = 2; currentPage <= firstPage.total_pages; currentPage += 1) {
    const result = await dealsApi.list({
      page: currentPage,
      page_size: PAGE_SIZE,
      stage,
    });

    allDeals.push(...result.items);
  }

  return allDeals;
}

export default function DealsPage() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [customers, setCustomers] = useState<CustomerProfile[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [negotiationDeal, setNegotiationDeal] = useState<Deal | null>(null);
const [negotiation, setNegotiation] = useState<DealNegotiation | null>(null);
const [negotiationHistory, setNegotiationHistory] = useState<
  NegotiationHistoryItem[]
>([]);
const [negotiationLoading, setNegotiationLoading] = useState(false);
const [negotiationSaving, setNegotiationSaving] = useState(false);
const [negotiationError, setNegotiationError] = useState("");
const [negotiationNote, setNegotiationNote] = useState("");
const [nextNegotiationState, setNextNegotiationState] =
  useState<NegotiationState>("IN_PROGRESS");

const [customNegotiationNote, setCustomNegotiationNote] =
  useState("");
  const [paymentMilestoneDeal, setPaymentMilestoneDeal] =
    useState<Deal | null>(null);
  const [commissionDeal, setCommissionDeal] = useState<Deal | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [visibleColumnKeys, setVisibleColumnKeys] = useState<string[]>(["customerProperty", "stage", "expectedValue", "owner", "createdAt"]);
  const [columnMenuPosition, setColumnMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [sortColumns, setSortColumns] = useState<SortColumn[]>([]);
  const [compactGrid, setCompactGrid] = useState(() => typeof window !== "undefined" && window.innerWidth >= 1600);

  const [actionMenu, setActionMenu] = useState<{ deal: Deal; top: number; left: number } | null>(null);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [transitioningDealId, setTransitioningDealId] = useState<string | null>(
  null,
);
const [transitionReason, setTransitionReason] = useState("");
const [transitionError, setTransitionError] = useState("");
  const [closingDeal, setClosingDeal] = useState<Deal | null>(null);
  const [closureOutcome, setClosureOutcome] = useState<"CLOSED_WON" | "CLOSED_LOST">("CLOSED_WON");
  const [closureReason, setClosureReason] = useState("");
  const [closureError, setClosureError] = useState("");
  const [closureSaving, setClosureSaving] = useState(false);
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
      const allDeals = await fetchAllDeals(
        stageFilter ? (stageFilter as DealStage) : undefined,
      );

      setDeals(allDeals);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [stageFilter]);

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
    const updateGridDensity = () => setCompactGrid(window.innerWidth >= 1600);
    updateGridDensity();
    window.addEventListener("resize", updateGridDensity, { passive: true });
    return () => window.removeEventListener("resize", updateGridDensity);
  }, []);

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
        setSearch(next);
      }
    }, 300);

    return () => window.clearTimeout(timer);
  }, [searchInput, search]);

  useEffect(() => {
    if (!columnMenuPosition) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setColumnMenuPosition(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [columnMenuPosition]);

  useEffect(() => {
    if (!actionMenu) return;

    const closeActionMenu = () => setActionMenu(null);
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeActionMenu();
    };

    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeActionMenu);
    window.addEventListener("scroll", closeActionMenu, true);

    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeActionMenu);
      window.removeEventListener("scroll", closeActionMenu, true);
    };
  }, [actionMenu]);

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


  async function openNegotiation(deal: Deal) {
    setNegotiationDeal(deal);
    setNegotiation(null);
    setNegotiationHistory([]);
    setNegotiationError("");
    setNegotiationNote("");
    setCustomNegotiationNote("");
    setNextNegotiationState("IN_PROGRESS");
    setNegotiationLoading(true);

    try {
      const current = await dealNegotiationsApi.get(deal.id);
      setNegotiation(current);
      setNextNegotiationState(current.state);

      try {
        const history = await dealNegotiationsApi.history(deal.id);
        setNegotiationHistory(history.items);
      } catch {
        setNegotiationError(
          "Negotiation loaded, but history could not be loaded. Reopen this panel to retry.",
        );
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        // No negotiation record yet. Allow the user to start tracking.
        setNegotiation(null);
        setNegotiationHistory([]);
        setNegotiationError("");
      } else {
        setNegotiationError(errorMessage(error));
      }
    } finally {
      setNegotiationLoading(false);
    }
  }



async function createNegotiation() {
  if (!negotiationDeal || negotiationSaving) return;

  const note = (
    negotiationNote === "CUSTOM"
      ? customNegotiationNote
      : negotiationNote
  ).trim();

  setNegotiationSaving(true);
  setNegotiationError("");
  setSuccess("");

  try {
    const created = await dealNegotiationsApi.create(
      negotiationDeal.id,
      {
        state: "IN_PROGRESS",
        note: note || undefined,
      },
    );

    // Update the UI immediately after successful creation.
    setNegotiation(created);
    setNextNegotiationState(created.state);
    setNegotiationNote("");
    setCustomNegotiationNote("");
    setNegotiationHistory([]);
    setSuccess("Negotiation started successfully.");

    // History loading is separate so a history failure
    // does not make the successful creation appear to fail.
    try {
      const history = await dealNegotiationsApi.history(
        negotiationDeal.id,
      );
      setNegotiationHistory(history.items);
    } catch {
      setNegotiationError(
        "Negotiation was created, but history could not be refreshed. Close and reopen the negotiation panel to retry.",
      );
    }
  } catch (error) {
    setNegotiationError(errorMessage(error));
  } finally {
    setNegotiationSaving(false);
  }
}

async function saveNegotiationState() {
  if (!negotiationDeal || !negotiation) return;

  const note = (
    negotiationNote === "CUSTOM"
      ? customNegotiationNote
      : negotiationNote
  ).trim();
    const currentState = negotiation.state;
  const targetState = nextNegotiationState;

  if (currentState === targetState) {
    setNegotiationError("Select a different negotiation state.");
    return;
  }

  const requiresReason =
    targetState === "CANCELLED" ||
    ((currentState === "COMPLETED" ||
      currentState === "CANCELLED" ||
      (currentState === "TERMS_AGREED" &&
        targetState === "IN_PROGRESS")) &&
      targetState === "IN_PROGRESS");

  if (requiresReason && !note) {
    setNegotiationError(
      "Enter a reason for cancelling or reopening the negotiation.",
    );
    return;
  }

  setNegotiationSaving(true);
  setNegotiationError("");

  try {
    const updated = await dealNegotiationsApi.update(
      negotiationDeal.id,
      {
        state: targetState,
        note: note || undefined,
      },
    );

    setNegotiation(updated);
    setNextNegotiationState(updated.state);
    setNegotiationNote("");

    const history = await dealNegotiationsApi.history(
      negotiationDeal.id,
    );
    setNegotiationHistory(history.items);
    setSuccess("Negotiation updated successfully.");
  } catch (error) {
    setNegotiationError(errorMessage(error));
  } finally {
    setNegotiationSaving(false);
  }
}

async function handleStageTransition(deal: Deal) {
  const nextStage = NEXT_DEAL_STAGE[deal.stage as DealStage];

  if (!nextStage || transitioningDealId) return;

  setTransitioningDealId(deal.id);
  setTransitionError("");
  setSuccess("");
  setError("");

  try {
    const updatedDeal = await dealsApi.transitionStage(deal.id, {
      stage: nextStage,
      reason: transitionReason.trim() || undefined,
    });

    setDeals((current) =>
      current.map((item) =>
        item.id === updatedDeal.id ? updatedDeal : item,
      ),
    );

    setTransitionReason("");
    setSuccess(
      `Deal moved from ${label(deal.stage)} to ${label(updatedDeal.stage)}.`,
    );

    // Refresh server-backed counts and pagination.
    await loadDeals();
  } catch (transitionFailure) {
    setTransitionError(errorMessage(transitionFailure));
  } finally {
    setTransitioningDealId(null);
  }
}

  function openClosureDialog(deal: Deal) {
    if (deal.stage !== "BOOKING" || transitioningDealId || closureSaving) return;
    setClosingDeal(deal);
    setClosureOutcome("CLOSED_WON");
    setClosureReason("");
    setClosureError("");
    setTransitionError("");
    setSuccess("");
  }

  async function handleCloseDeal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!closingDeal || closureSaving) return;

    const reason = closureReason.trim();
    if (!reason) {
      setClosureError("Enter a reason for closing this deal.");
      return;
    }

    if (reason.length > 2000) {
      setClosureError("The closure reason must be 2,000 characters or fewer.");
      return;
    }

    setClosureSaving(true);
    setClosureError("");
    setTransitionError("");
    setSuccess("");

    try {
      const updatedDeal = await dealsApi.transitionStage(closingDeal.id, {
        stage: closureOutcome,
        reason,
      });

      setDeals((current) =>
        current.map((item) =>
          item.id === updatedDeal.id ? updatedDeal : item,
        ),
      );

      setClosingDeal(null);
      setClosureReason("");
      setSuccess(
        `Deal closed as ${label(updatedDeal.stage)}. The closure reason was recorded in deal history.`,
      );

      // Refresh server-backed counts and pagination without changing payments
      // or commission records associated with the deal.
      await loadDeals();
    } catch (closeFailure) {
      setClosureError(errorMessage(closeFailure));
    } finally {
      setClosureSaving(false);
    }
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
      setSearch("");
      setSearchInput("");
      setStageFilter("");
      setSuccess("Deal created successfully.");

      // Reload the complete directory so the new deal is visible.
      const allDeals = await fetchAllDeals();
      setDeals(allDeals);
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

  const sortedDeals = useMemo(() => {
    if (sortColumns.length === 0) return filteredDeals;

    return [...filteredDeals].sort((left, right) => {
      for (const sort of sortColumns) {
        const getValue = (deal: Deal): string | number => {
          switch (sort.columnKey) {
            case "customerProperty":
              return `${customerName(customerById.get(deal.customer_profile_id))} ${propertyAddress(propertyById.get(deal.property_id))}`;
            case "stage":
              return label(deal.stage);
            case "expectedValue":
              return Number(deal.expected_value) || 0;
            case "owner":
              return deal.owner_name || "Unknown owner";
            case "createdAt":
              return new Date(deal.created_at).getTime() || 0;
            default:
              return "";
          }
        };

        const a = getValue(left);
        const b = getValue(right);
        const comparison = typeof a === "number" && typeof b === "number"
          ? a - b
          : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
        if (comparison !== 0) return sort.direction === "DESC" ? -comparison : comparison;
      }
      return 0;
    });
  }, [filteredDeals, sortColumns, customerById, propertyById]);

  const openColumnMenu = useCallback((event: { currentTarget: HTMLButtonElement }) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 240;
    setColumnMenuPosition((current) => current ? null : {
      top: Math.max(12, Math.min(rect.bottom + 6, window.innerHeight - 300)),
      left: Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12)),
    });
  }, []);

  const openActionMenu = useCallback(
    (event: { currentTarget: HTMLButtonElement }, deal: Deal) => {
      const rect = event.currentTarget.getBoundingClientRect();
      const menuWidth = 264;
      const hasStageAction = Boolean(NEXT_DEAL_STAGE[deal.stage as DealStage]);
      const hasCloseAction = deal.stage === "BOOKING";
      const actionCount = 3 + Number(hasStageAction) + Number(hasCloseAction);
      const menuHeight = Math.min(82 + actionCount * 54, window.innerHeight - 24);
      const top = rect.bottom + menuHeight + 12 > window.innerHeight
        ? Math.max(12, rect.top - menuHeight - 6)
        : rect.bottom + 6;
      const left = Math.max(12, Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 12));

      setActionMenu((current) =>
        current?.deal.id === deal.id ? null : { deal, top, left },
      );
    },
    [],
  );

  const columns = useMemo<readonly Column<Deal>[]>(() => [
    {
      key: "customerProperty",
      name: "Customer / Property",
      minWidth: 250,
      width: 330,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => {
        const name = customerName(customerById.get(row.customer_profile_id));
        const property = propertyById.get(row.property_id);
        const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "D";
        return (
          <div className="deals-person-cell">
            <span className="deals-avatar" aria-hidden="true">{initials}</span>
            <span className="deals-person-copy">
              <strong title={name}>{name}</strong>
              <span title={propertyAddress(property)}>{propertyTitle(property)} · {propertyAddress(property)}</span>
            </span>
          </div>
        );
      },
    },
    {
      key: "stage",
      name: "Stage",
      minWidth: 150,
      width: 170,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => <span className={stageClass(row.stage)}>{label(row.stage)}</span>,
    },
    {
      key: "expectedValue",
      name: "Expected value",
      minWidth: 145,
      width: 165,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => <span className="deals-value">{amount(row.expected_value, row.currency || "INR")}</span>,
    },
    {
      key: "owner",
      name: "Owner",
      minWidth: 150,
      width: 180,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => <span className="deals-owner-name" title={row.owner_name || "Unknown owner"}>{row.owner_name || "Unknown owner"}</span>,
    },
    {
      key: "createdAt",
      name: "Created",
      minWidth: 115,
      width: 135,
      resizable: true,
      sortable: true,
      renderCell: ({ row }) => <span className="deals-created-date">{formatDate(row.created_at)}</span>,
    },
    {
      key: "actions",
      name: "Actions",
      minWidth: 92,
      width: 104,
      resizable: false,
      sortable: false,
      renderCell: ({ row }) => {
        const customer = customerName(customerById.get(row.customer_profile_id));
        const busy = transitioningDealId === row.id || closureSaving;

        return (
          <div
            className="deals-row-actions"
            role="group"
            aria-label={`Actions for ${customer}`}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="deals-icon-action deals-action-menu-trigger"
              type="button"
              aria-label={`Open actions for ${customer}`}
              aria-haspopup="menu"
              aria-expanded={actionMenu?.deal.id === row.id}
              disabled={busy}
              title="Deal actions"
              onClick={(event) => openActionMenu(event, row)}
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="currentColor">
                <circle cx="5" cy="12" r="1.8" />
                <circle cx="12" cy="12" r="1.8" />
                <circle cx="19" cy="12" r="1.8" />
              </svg>
            </button>
            {busy && (
              <span className="deals-action-busy" role="status" aria-label="Updating deal" />
            )}
          </div>
        );
      },
    },
    {
      key: "configure",
      name: "",
      width: "1fr",
      minWidth: 44,
      resizable: false,
      sortable: false,
      renderHeaderCell: () => (
        <button className="deals-configure-columns-button" type="button" onClick={openColumnMenu} aria-label="Configure table columns" title="Configure columns" aria-expanded={columnMenuPosition !== null}>
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 4v16M15 4v16"/></svg>
        </button>
      ),
      renderCell: () => <span aria-hidden="true" />,
    },
  ], [customerById, propertyById, transitioningDealId, closureSaving, openActionMenu, actionMenu, openColumnMenu, columnMenuPosition]);

  const visibleColumns = useMemo(
    () => columns.filter((column) => column.key === "configure" || column.key === "actions" || visibleColumnKeys.includes(column.key)),
    [columns, visibleColumnKeys],
  );

  return (
    <main className="deals-page deals-workspace">
      <header className="deals-page-header">
        <div className="deals-heading-copy">
          <h1>Deals</h1>
          <p>Track opportunities, manage negotiations, and keep every next step visible.</p>
        </div>
      </header>

      {success && (
        <div className="deals-alert deals-alert-success" role="status">
          <span>{success}</span>
          <button type="button" className="deals-dismiss" onClick={() => setSuccess("")} aria-label="Dismiss success message">×</button>
        </div>
      )}
      {transitionError && <div className="deals-alert deals-alert-error" role="alert">{transitionError}</div>}

      <div className="deals-filterbar">
        <label className="deals-search-field">
          <span className="deals-visually-hidden">Search deals</span>
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
          <input type="search" maxLength={320} value={searchInput} placeholder="Search customer, property, stage or deal ID" onChange={(event) => { setSearchInput(event.target.value); }} />
          {searchInput && <button type="button" aria-label="Clear search" onClick={() => { setSearchInput(""); setSearch(""); }}>×</button>}
        </label>
        <label className="deals-filter-field">
          <span>Stage</span>
          <select aria-label="Filter deals by stage" value={stageFilter} onChange={(event) => { setStageFilter(event.target.value); }}>
            <option value="">All stages</option>
            {DEAL_STAGES.map((stage) => <option value={stage} key={stage}>{label(stage)}</option>)}
          </select>
        </label>
        {(searchInput || stageFilter) && <button className="deals-clear-filters" type="button" onClick={() => { setSearchInput(""); setSearch(""); setStageFilter(""); }}>Clear filters</button>}
        <button className="deals-primary-button deals-add-button" type="button" onClick={openCreateForm}>
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14"/></svg>
          New deal
        </button>
      </div>

      {error && <div className="deals-alert deals-alert-error" role="alert"><div><strong>We couldn’t load deals</strong><p>{error}</p></div><button className="deals-secondary-button" type="button" onClick={() => void loadDeals()}>Try again</button></div>}

      {loading ? (
        <div className="deals-state" role="status" aria-live="polite"><span className="deals-spinner" aria-hidden="true"/><p>Loading deals…</p></div>
      ) : !error && filteredDeals.length === 0 ? (
        <div className="deals-empty">
          <div className="deals-empty-icon" aria-hidden="true">◇</div>
          <h3>{search || stageFilter ? "No deals match these filters" : "Start with your first deal"}</h3>
          <p>{search || stageFilter ? "Try another search or clear one or more filters." : "Create a deal to connect a customer with a property and track the opportunity."}</p>
          {search || stageFilter ? <button className="deals-secondary-button" type="button" onClick={() => { setSearchInput(""); setSearch(""); setStageFilter(""); }}>Reset view</button> : <button className="deals-primary-button" type="button" onClick={openCreateForm}>Create your first deal</button>}
        </div>
      ) : !error ? (
        <>
          <div className="deals-grid-shell">
            <DataGrid
              className="deals-react-data-grid"
              aria-label="Deals directory"
              columns={visibleColumns}
              rows={sortedDeals}
              rowKeyGetter={(row) => row.id}
              rowHeight={compactGrid ? 48 : 62}
              headerRowHeight={52}
              defaultColumnOptions={{ resizable: true, sortable: true }}
              sortColumns={sortColumns}
              onSortColumnsChange={setSortColumns}
              style={{
                height: Math.min(52 + sortedDeals.length * (compactGrid ? 48 : 62), Math.max(260, (typeof window !== "undefined" ? window.innerHeight : 900) * 0.68)),
                minHeight: 52 + Math.min(sortedDeals.length, 1) * (compactGrid ? 48 : 62),
              }}
              renderers={{ noRowsFallback: <div className="deals-grid-no-rows">No deals to display.</div> }}
            />
            <footer className="deals-grid-footer" aria-live="polite">
              <span className="deals-grid-footer-count">
                <strong>{sortedDeals.length}</strong> {sortedDeals.length === 1 ? "deal" : "deals"}
                {search || stageFilter ? " match your current view" : " in your workspace"}
              </span>
              <span className="deals-grid-footer-status">
                <span className="deals-grid-footer-status-dot" aria-hidden="true" />
                {search || stageFilter ? "Filtered results" : "You're all caught up"}
              </span>
            </footer>
          </div>
        </>
      ) : null}

      {actionMenu && createPortal(
        <div
          className="deals-action-menu-layer"
          role="presentation"
          onPointerDown={() => setActionMenu(null)}
        >
          <section
            className="deals-action-menu"
            style={{ top: actionMenu.top, left: actionMenu.left }}
            role="menu"
            aria-label="Deal actions"
            onPointerDown={(event) => event.stopPropagation()}
          >
            <header className="deals-action-menu-header">
              <div>
                <strong>Deal actions</strong>
                <span>
                  {customerName(
                    customerById.get(actionMenu.deal.customer_profile_id),
                  )}
                </span>
              </div>
              <button
                type="button"
                aria-label="Close deal actions"
                onClick={() => setActionMenu(null)}
              >
                ×
              </button>
            </header>

            {NEXT_DEAL_STAGE[actionMenu.deal.stage as DealStage] && (
              <button
                className="deals-action-menu-item"
                type="button"
                role="menuitem"
                disabled={transitioningDealId !== null || closureSaving}
                onClick={() => {
                  const selectedDeal = actionMenu.deal;
                  setActionMenu(null);
                  void handleStageTransition(selectedDeal);
                }}
              >
                <span className="deals-action-menu-icon deals-action-menu-icon-primary" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h13M13 6l6 6-6 6" /></svg>
                </span>
                <span className="deals-action-menu-copy">
                  <strong>Move to {label(NEXT_DEAL_STAGE[actionMenu.deal.stage as DealStage]!)}</strong>
                  <small>Advance this deal to the next stage</small>
                </span>
              </button>
            )}

            {actionMenu.deal.stage === "BOOKING" && (
              <button
                className="deals-action-menu-item"
                type="button"
                role="menuitem"
                disabled={transitioningDealId !== null || closureSaving}
                onClick={() => {
                  const selectedDeal = actionMenu.deal;
                  setActionMenu(null);
                  openClosureDialog(selectedDeal);
                }}
              >
                <span className="deals-action-menu-icon deals-action-menu-icon-success" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M7 3h10M9 3v3m6-3v3M5 7h14v14H5z"/><path d="m8 14 2.5 2.5L16 11" /></svg>
                </span>
                <span className="deals-action-menu-copy">
                  <strong>Close deal</strong>
                  <small>Record the final outcome</small>
                </span>
              </button>
            )}

            <div className="deals-action-menu-divider" />

            <button
              className="deals-action-menu-item"
              type="button"
              role="menuitem"
              disabled={negotiationLoading || negotiationSaving}
              onClick={() => {
                const selectedDeal = actionMenu.deal;
                setActionMenu(null);
                void openNegotiation(selectedDeal);
              }}
            >
              <span className="deals-action-menu-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/></svg>
              </span>
              <span className="deals-action-menu-copy">
                <strong>Negotiation</strong>
                <small>View terms and negotiation history</small>
              </span>
            </button>

            <button
              className="deals-action-menu-item"
              type="button"
              role="menuitem"
              onClick={() => {
                const selectedDeal = actionMenu.deal;
                setActionMenu(null);
                setPaymentMilestoneDeal(selectedDeal);
              }}
            >
              <span className="deals-action-menu-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M7 15h3"/></svg>
              </span>
              <span className="deals-action-menu-copy">
                <strong>Payment milestones</strong>
                <small>Track scheduled and received payments</small>
              </span>
            </button>

            <button
              className="deals-action-menu-item"
              type="button"
              role="menuitem"
              onClick={() => {
                const selectedDeal = actionMenu.deal;
                setActionMenu(null);
                setCommissionDeal(selectedDeal);
              }}
            >
              <span className="deals-action-menu-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M16 8 8 16M8.5 8.5h.01M15.5 15.5h.01"/></svg>
              </span>
              <span className="deals-action-menu-copy">
                <strong>Commission</strong>
                <small>Review deal commission details</small>
              </span>
            </button>
          </section>
        </div>,
        document.body,
      )}

      {columnMenuPosition && createPortal(
        <div className="deals-column-menu-layer" onPointerDown={() => setColumnMenuPosition(null)} role="presentation">
          <div className="deals-column-menu" style={{ top: columnMenuPosition.top, left: columnMenuPosition.left }} role="dialog" aria-label="Configure table columns" onPointerDown={(event) => event.stopPropagation()}>
            <div className="deals-column-menu-heading"><div><strong>Configure columns</strong><span>Choose which fields are visible.</span></div><button type="button" aria-label="Close column configuration" onClick={() => setColumnMenuPosition(null)}>×</button></div>
            {[
              { key: "customerProperty", label: "Customer / Property" },
              { key: "stage", label: "Stage" },
              { key: "expectedValue", label: "Expected value" },
              { key: "owner", label: "Owner" },
              { key: "createdAt", label: "Created" },
            ].map((column) => (
              <label className="deals-column-option" key={column.key}>
                <input type="checkbox" checked={visibleColumnKeys.includes(column.key)} onChange={(event) => setVisibleColumnKeys((current) => event.target.checked ? [...current, column.key] : current.filter((key) => key !== column.key))}/>
                <span>{column.label}</span>
              </label>
            ))}
            <div className="deals-column-menu-footer"><button type="button" onClick={() => setVisibleColumnKeys(["customerProperty", "stage", "expectedValue", "owner", "createdAt"])}>Reset columns</button><button type="button" onClick={() => setColumnMenuPosition(null)}>Done</button></div>
          </div>
        </div>, document.body,
      )}

      {closingDeal &&
        createPortal(
          <div
            className="deals-modal-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget && !closureSaving) {
                setClosingDeal(null);
                setClosureError("");
              }
            }}
          >
            <section
              className="deals-modal deals-closure-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="deal-closure-modal-title"
            >
              <header className="deals-modal-header">
                <div>
                  <span className="deals-eyebrow">DEAL WORKSPACE</span>
                  <h2 id="deal-closure-modal-title">Close deal</h2>
                  <p>
                    Confirm the outcome for{" "}
                    {customerName(
                      customerById.get(closingDeal.customer_profile_id),
                    )}{" "}
                    · {propertyAddress(propertyById.get(closingDeal.property_id))}
                  </p>
                </div>
                <button
                  className="deals-modal-close"
                  type="button"
                  aria-label="Close deal closure dialog"
                  disabled={closureSaving}
                  onClick={() => {
                    setClosingDeal(null);
                    setClosureError("");
                  }}
                >
                  ×
                </button>
              </header>

              <form className="deals-form" onSubmit={handleCloseDeal}>
                <div className="deals-form-body">
                  {closureError && (
                    <div
                      className="deals-alert deals-alert-error deals-form-error"
                      role="alert"
                    >
                      <p>{closureError}</p>
                    </div>
                  )}

                  <div className="deals-closure-notice">
                    <strong>This action records a final deal outcome.</strong>
                    <p>
                      A closed deal cannot be reopened through the stage workflow.
                      Existing payment milestones and commission records will not
                      be changed by closing the deal.
                    </p>
                  </div>

                  <label className="deals-form-field">
                    <span>Outcome *</span>
                    <select
                      required
                      value={closureOutcome}
                      disabled={closureSaving}
                      onChange={(event) =>
                        setClosureOutcome(
                          event.target.value as "CLOSED_WON" | "CLOSED_LOST",
                        )
                      }
                    >
                      <option value="CLOSED_WON">Won — deal completed successfully</option>
                      <option value="CLOSED_LOST">Lost — deal did not proceed</option>
                    </select>
                  </label>

                  <label className="deals-form-field deals-closure-reason">
                    <span>Closure reason *</span>
                    <textarea
                      required
                      maxLength={2000}
                      rows={4}
                      value={closureReason}
                      disabled={closureSaving}
                      onChange={(event) => {
                        setClosureReason(event.target.value);
                        setClosureError("");
                      }}
                      placeholder={
                        closureOutcome === "CLOSED_WON"
                          ? "For example: Agreement signed and booking confirmed."
                          : "For example: Customer selected another property."
                      }
                      aria-describedby="deal-closure-reason-help"
                    />
                    <small id="deal-closure-reason-help">
                      {closureReason.length}/2000 characters. This reason is
                      saved to the deal's audit history.
                    </small>
                  </label>
                </div>

                <footer className="deals-form-actions">
                  <button
                    className="deals-secondary-button"
                    type="button"
                    disabled={closureSaving}
                    onClick={() => {
                      setClosingDeal(null);
                      setClosureError("");
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    className="deals-primary-button"
                    type="submit"
                    disabled={closureSaving || !closureReason.trim()}
                  >
                    {closureSaving
                      ? "Closing deal..."
                      : `Confirm ${closureOutcome === "CLOSED_WON" ? "Won" : "Lost"}`}
                  </button>
                </footer>
              </form>
            </section>
          </div>,
          document.body,
        )}

      {negotiationDeal &&
  createPortal(
    <div
      className="deals-modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !negotiationSaving) {
          setNegotiationDeal(null);
          setNegotiationError("");
        }
      }}
    >
      <section
        className="deals-modal deals-negotiation-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="negotiation-modal-title"
      >
        <header className="deals-modal-header">
          <div>
            <span className="deals-eyebrow">DEAL WORKSPACE</span>
            <h2 id="negotiation-modal-title">Negotiation</h2>
            <p>
              {customerName(
                customerById.get(negotiationDeal.customer_profile_id),
              )}{" "}
              · {propertyAddress(
                propertyById.get(negotiationDeal.property_id),
              )}
            </p>
          </div>

          <button
            className="deals-modal-close"
            type="button"
            aria-label="Close negotiation"
            disabled={negotiationSaving}
            onClick={() => setNegotiationDeal(null)}
          >
            ×
          </button>
        </header>

        <div className="deals-form-body">
          {negotiationError && (
            <div className="deals-alert deals-alert-error" role="alert">
              {negotiationError}
            </div>
          )}

          {negotiationLoading ? (
            <div className="deals-state" role="status">
              <span className="deals-spinner" aria-hidden="true" />
              <p>Loading negotiation...</p>
            </div>
          ) : !negotiation ? (
            <section className="deals-negotiation-section">

              <div className="deals-negotiation-section">
                <label
                  className="deals-negotiation-label"
                  htmlFor="negotiation-opening-comment"
                >
                  Opening comment (optional)
                </label>

                <select
                  id="negotiation-opening-comment"
                  value={negotiationNote}
                  onChange={(event) => {
                    setNegotiationNote(event.target.value);
                    setCustomNegotiationNote("");
                  }}
                  disabled={negotiationSaving}
                >
                  <option value="">Select an opening comment</option>
                  <option value="Initial discussion started">
                    Initial discussion started
                  </option>
                  <option value="Customer interested in the property">
                    Customer interested in the property
                  </option>
                  <option value="Price negotiation initiated">
                    Price negotiation initiated
                  </option>
                  <option value="Offer received from customer">
                    Offer received from customer
                  </option>
                  <option value="Follow-up required after site visit">
                    Follow-up required after site visit
                  </option>
                  <option value="CUSTOM">Other — enter custom comment</option>
                </select>

                {negotiationNote === "CUSTOM" && (
                  <textarea
                    value={customNegotiationNote}
                    onChange={(event) =>
                      setCustomNegotiationNote(event.target.value)
                    }
                    placeholder="Enter the opening comment..."
                    rows={3}
                    disabled={negotiationSaving}
                    aria-label="Custom opening comment"
                  />
                )}
              </div>
              <button
                className="deals-primary-button"
                type="button"
                disabled={negotiationSaving}
                onClick={() => void createNegotiation()}
              >
                {negotiationSaving ? "Creating..." : "Start negotiation"}
              </button>
            </section>
          ) : (
            <>
              <section className="deals-negotiation-section">
                <span className="deals-negotiation-label">
                  Current negotiation state
                </span>
                <p>
                  <span
                    className={`deals-stage deals-negotiation-state-${negotiation.state.toLowerCase()}`}
                  >
                    {label(negotiation.state)}
                  </span>
                </p>

                <label className="deals-form-field">
                  <span>Change state</span>
                  <select
                    value={nextNegotiationState}
                    disabled={negotiationSaving}
                    onChange={(event) => {
  setNextNegotiationState(
    event.target.value as NegotiationState,
  );
  setNegotiationNote("");
  setCustomNegotiationNote("");
  setNegotiationError("");
}}
                  >
                    <option value={negotiation.state}>
                      {label(negotiation.state)} (current)
                    </option>
                    {NEGOTIATION_TRANSITIONS[negotiation.state].map(
                      (state) => (
                        <option value={state} key={state}>
                          {label(state)}
                        </option>
                      ),
                    )}
                  </select>
                </label>


<div className="deals-negotiation-section">
  <label
    className="deals-negotiation-label"
    htmlFor="negotiation-update-comment"
  >
    Reason or update comment
  </label>

  <select
    id="negotiation-update-comment"
    value={negotiationNote}
    disabled={negotiationSaving}
    onChange={(event) => {
      setNegotiationNote(event.target.value);
      setCustomNegotiationNote("");
    }}
  >
    <option value="">Select a comment</option>

    {NEGOTIATION_COMMENTS[nextNegotiationState].map((comment) => (
      <option key={comment} value={comment}>
        {comment}
      </option>
    ))}

    <option value="CUSTOM">Other — enter custom comment</option>
  </select>

  {negotiationNote === "CUSTOM" && (
    <textarea
      maxLength={2000}
      rows={3}
      value={customNegotiationNote}
      disabled={negotiationSaving}
      onChange={(event) =>
        setCustomNegotiationNote(event.target.value)
      }
      placeholder="Enter the reason or negotiation update..."
      aria-label="Custom negotiation comment"
    />
  )}

  <small>
    Choose a comment relevant to the new state. A reason is required
    when cancelling or reopening a negotiation.
  </small>
</div>


                <button
                  className="deals-primary-button"
                  type="button"
                  disabled={
                    negotiationSaving ||
                    nextNegotiationState === negotiation.state
                  }
                  onClick={() => void saveNegotiationState()}
                >
                  {negotiationSaving ? "Saving..." : "Save change"}
                </button>
              </section>

              <section className="deals-negotiation-section">
                <h3>Negotiation history</h3>
                {negotiationHistory.length === 0 ? (
                  <p>No history is available yet.</p>
                ) : (
                  <ol className="deals-negotiation-timeline">
                    {negotiationHistory.map((item) => (
                      <li key={item.id}>
                        <div className="deals-negotiation-timeline-marker" />
                        <div className="deals-negotiation-history-content">
                          <strong>
                            {item.from_state
                              ? `${label(item.from_state)} → ${label(item.to_state)}`
                              : `Negotiation created: ${label(item.to_state)}`}
                          </strong>
                          {item.note && <p>{item.note}</p>}
                          <small>
                            {formatDate(item.created_at)} ·{" "}
                            {new Date(item.created_at).toLocaleTimeString(
                              "en-IN",
                              {
                                hour: "2-digit",
                                minute: "2-digit",
                              },
                            )}
                          </small>
                          {item.actor_user_id && (
                            <small>
                              User ID: {item.actor_user_id}
                            </small>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </>
          )}
        </div>

        <footer className="deals-form-actions">
          <button
            className="deals-secondary-button"
            type="button"
            disabled={negotiationSaving}
            onClick={() => setNegotiationDeal(null)}
          >
            Close
          </button>
        </footer>
      </section>
    </div>,
    document.body,
  )}

  {paymentMilestoneDeal && (
    <PaymentMilestonesPanel
      dealId={paymentMilestoneDeal.id}
      dealTitle={`${customerName(
        customerById.get(
          paymentMilestoneDeal.customer_profile_id,
        ),
      )} · ${propertyAddress(
        propertyById.get(paymentMilestoneDeal.property_id),
      )}`}
      onClose={() => setPaymentMilestoneDeal(null)}
    />
  )}

  {commissionDeal && (
    <DealCommissionsPanel
      dealId={commissionDeal.id}
      dealTitle={`${customerName(
        customerById.get(commissionDeal.customer_profile_id),
      )} · ${propertyAddress(
        propertyById.get(commissionDeal.property_id),
      )}`}
      dealValue={commissionDeal.expected_value}
      currency={commissionDeal.currency || "INR"}
      onClose={() => setCommissionDeal(null)}
    />
  )}

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
    </main>
  );
}

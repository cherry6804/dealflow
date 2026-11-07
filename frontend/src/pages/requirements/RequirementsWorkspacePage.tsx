import { useCallback, useEffect, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import type { GridFilterField } from "../../components/grid/gridFilters";
import { Badge } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { contactsApi, type Contact } from "../../services/contactApi";
import { customerProfilesApi, type CustomerProfile } from "../../services/customerProfileApi";
import { leadsApi, type Lead } from "../../services/leadApi";
import { requirementsApi, type CustomerRequirement } from "../../services/requirementApi";
import { fetchAllPages, formatShortDate, personName, SALES_PAGE_SIZE } from "../sales/sales-shared";
import "../sales/sales.css";
import RequirementRecordDialog, { type RequirementCustomerOption, type RequirementLeadOption } from "./RequirementRecordDialog";
import { budgetRange, enumLabel, requirementCustomerName } from "./requirement-workflow";

const COLUMNS: GridColumnDef[] = [
  { key: "requirement", label: "Customer requirement", defaultWidth: 260, primary: true },
  { key: "transaction", label: "Transaction", defaultWidth: 120 },
  { key: "budget", label: "Budget range", defaultWidth: 260 },
  { key: "status", label: "Status", defaultWidth: 120 },
  { key: "created", label: "Created", defaultWidth: 130 },
  { key: "updated", label: "Last updated", defaultWidth: 140, defaultVisible: false },
];

const FILTER_FIELDS: readonly GridFilterField[] = [
  {
    key: "status",
    label: "Status",
    type: "select",
    options: [
      { value: "active", label: "Active" },
      { value: "inactive", label: "Inactive" },
    ],
  },
  {
    key: "transaction",
    label: "Transaction",
    type: "select",
    options: [
      { value: "SALE", label: "Sale" },
      { value: "RENT", label: "Rent" },
      { value: "LEASE", label: "Lease" },
    ],
  },
  { key: "customer", label: "Customer", type: "text" },
  { key: "email", label: "Email address", type: "text" },
  { key: "created", label: "Created", type: "date" },
];

function errorText(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Check your connection and try again.";
}

interface RequirementLookups {
  leads: RequirementLeadOption[];
  customers: RequirementCustomerOption[];
}

async function loadLookups(): Promise<RequirementLookups> {
  const [leads, contacts, profiles] = await Promise.all([
    fetchAllPages((page) => leadsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => contactsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => customerProfilesApi.list({ page, page_size: SALES_PAGE_SIZE, is_active: true })),
  ]);
  const contactById = new Map<string, Contact>(contacts.map((contact) => [contact.id, contact]));
  return {
    leads: leads
      .filter((lead: Lead) => lead.is_active)
      .map((lead) => {
        const contact = contactById.get(lead.contact_id);
        return { lead, label: `${contact ? personName(contact) || "Unnamed contact" : "Contact unavailable"} · ${enumLabel(lead.status)}` };
      }),
    customers: profiles.map((profile: CustomerProfile) => ({
      profile,
      label: personName(profile.contact) || profile.contact.email || "Unnamed customer",
    })),
  };
}

/**
 * Customer requirements on the shared EnterpriseDataGrid. Rows open the requirement record, where budget, the linked lead or
 * customer, locations, property preferences, possession and parking, the shortlist and matching are managed, each section saving on
 * its own as before. Locations, preferences and matches are sub-records and are not in the list data, so they appear in the record,
 * not the grid.
 */
export default function RequirementsWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [requirements, setRequirements] = useState<CustomerRequirement[]>([]);
  const [lookups, setLookups] = useState<RequirementLookups>({ leads: [], customers: [] });
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const reload = useCallback(async () => {
    const [items, lookupData] = await Promise.all([
      fetchAllPages((page) => requirementsApi.list({ page, page_size: SALES_PAGE_SIZE })),
      loadLookups(),
    ]);
    setRequirements(items);
    setLookups(lookupData);
    setLoadError("");
    setStatus("ready");
  }, []);

  // Initial load. State is set only inside the request callbacks, never synchronously in the effect body.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchAllPages((page) => requirementsApi.list({ page, page_size: SALES_PAGE_SIZE })),
      loadLookups(),
    ])
      .then(([items, lookupData]) => {
        if (cancelled) return;
        setRequirements(items);
        setLookups(lookupData);
        setLoadError("");
        setStatus("ready");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(errorText(error));
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return requirements;
    return requirements.filter((item) =>
      [requirementCustomerName(item), item.customer_email ?? "", item.customer_phone ?? ""].some((value) => value.toLowerCase().includes(needle)),
    );
  }, [requirements, search]);

  const sortValue = useCallback((item: CustomerRequirement, key: string): string | number | null => {
    switch (key) {
      case "transaction":
        return item.transaction_type ? enumLabel(item.transaction_type) : null;
      case "budget": {
        const value = Number(item.budget_min);
        return item.budget_min != null && Number.isFinite(value) ? value : null;
      }
      case "status":
        return item.is_active ? "Active" : "Inactive";
      case "created":
        return new Date(item.created_at).getTime();
      case "updated":
        return new Date(item.updated_at).getTime();
      default:
        return requirementCustomerName(item);
    }
  }, []);

  const renderCell = useCallback((item: CustomerRequirement, key: string) => {
    switch (key) {
      case "transaction":
        return item.transaction_type ? enumLabel(item.transaction_type) : "—";
      case "budget":
        return budgetRange(item);
      case "status":
        return <Badge tone={item.is_active ? "success" : "neutral"}>{item.is_active ? "Active" : "Inactive"}</Badge>;
      case "created":
        return formatShortDate(item.created_at);
      case "updated":
        return formatShortDate(item.updated_at);
      default:
        return (
          <span className="df-sales-stack">
            <strong className="df-sales-primary">{requirementCustomerName(item)}</strong>
            <span className="df-sales-muted">{item.customer_email || item.customer_phone || "No contact details"}</span>
          </span>
        );
    }
  }, []);

  const filterValue = useCallback((item: CustomerRequirement, key: string): string | null => {
    switch (key) {
      case "status":
        return item.is_active ? "active" : "inactive";
      case "transaction":
        return item.transaction_type ?? null;
      case "customer":
        return item.customer_name ?? null;
      case "email":
        return item.customer_email ?? null;
      case "created":
        return item.created_at;
      default:
        return null;
    }
  }, []);

  const selected = selectedId ? (requirements.find((item) => item.id === selectedId) ?? null) : null;

  async function createRequirement() {
    setCreating(true);
    setNotice("");
    try {
      // This API creates the record first; the details are completed in the record that opens.
      const created = await requirementsApi.create();
      await reload();
      setSelectedId(created.id);
      setNotice("Requirement created. Complete the details in the record.");
    } catch (error) {
      setLoadError(errorText(error));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="df-sales-page">
      <h1 className="df-visually-hidden">Requirements</h1>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<CustomerRequirement>
        gridId="requirements"
        ariaLabel="Customer requirements"
        columns={COLUMNS}
        rows={rows}
        rowKey={(item) => item.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void reload()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search requirements"
        searchPlaceholder="Search customer, email or phone"
        emptyTitle="No requirements yet"
        emptyMessage="Create a requirement to capture a customer's budget, locations and property preferences."
        noMatchTitle="No requirements match this search or filter"
        noMatchMessage="Try another search, or clear the filters."
        createLabel={creating ? "Creating…" : "New requirement"}
        onCreate={() => void createRequirement()}
        onOpenRow={(item) => setSelectedId(item.id)}
        totalCount={requirements.length}
        rangeLabel={search ? "Filtered" : "All requirements shown"}
        filterFields={FILTER_FIELDS}
        filterValue={filterValue}
      />

      {selected ? (
        <RequirementRecordDialog
          key={selected.id}
          requirement={selected}
          leads={lookups.leads}
          customers={lookups.customers}
          onClose={() => setSelectedId(null)}
          onChanged={(message) => {
            setNotice(message);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}

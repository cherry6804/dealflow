import { useCallback, useEffect, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import type { GridFilterField } from "../../components/grid/gridFilters";
import { Badge } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { contactsApi, type Contact } from "../../services/contactApi";
import { customerProfilesApi, type CustomerProfile } from "../../services/customerProfileApi";
import { dealsApi, type Deal } from "../../services/dealApi";
import { leadsApi, type Lead } from "../../services/leadApi";
import { propertiesApi, type Property } from "../../services/propertyApi";
import { fetchAllPages, formatShortDate, SALES_PAGE_SIZE } from "../sales/sales-shared";
import "../sales/sales.css";
import DealCreateDialog from "./DealCreateDialog";
import DealRecordDialog, { type DealLookups } from "./DealRecordDialog";
import { DEAL_STAGES, dealCustomerName, dealPropertyTitle, dealStageLabel, dealStageTone, formatDealAmount } from "./deal-workflow";

const COLUMNS: GridColumnDef[] = [
  { key: "deal", label: "Deal", defaultWidth: 280, primary: true },
  { key: "stage", label: "Stage", defaultWidth: 150 },
  { key: "value", label: "Expected value", defaultWidth: 170 },
  { key: "owner", label: "Assigned agent", defaultWidth: 170 },
  { key: "created", label: "Created", defaultWidth: 130 },
  { key: "updated", label: "Last updated", defaultWidth: 140, defaultVisible: false },
];

const FILTER_FIELDS: readonly GridFilterField[] = [
  { key: "stage", label: "Stage", type: "select", options: DEAL_STAGES.map((value) => ({ value, label: dealStageLabel(value) })) },
  { key: "customer", label: "Customer", type: "text" },
  { key: "property", label: "Property", type: "text" },
  { key: "owner", label: "Assigned agent", type: "text" },
  { key: "created", label: "Created", type: "date" },
];

function errorText(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Check your connection and try again.";
}

async function loadAll(): Promise<{ deals: Deal[]; lookups: DealLookups }> {
  const [deals, customers, properties, leads, contacts] = await Promise.all([
    fetchAllPages((page) => dealsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => customerProfilesApi.list({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => propertiesApi.search({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => leadsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => contactsApi.list({ page, page_size: SALES_PAGE_SIZE })),
  ]);
  const lookups: DealLookups = {
    customers: customers as CustomerProfile[],
    properties: properties as Property[],
    leads: leads as Lead[],
    contacts: contacts as Contact[],
  };
  return { deals, lookups };
}

/**
 * Deals on the shared EnterpriseDataGrid. Rows open the deal record, where the details, stage moves, closing, negotiation,
 * payment milestones and commissions keep their existing endpoints. Deals have no separate name or reference number, and no
 * expected closing date, so a deal is identified by its customer and property.
 */
export default function DealsWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [deals, setDeals] = useState<Deal[]>([]);
  const [lookups, setLookups] = useState<DealLookups>({ customers: [], properties: [], leads: [], contacts: [] });
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const reload = useCallback(async () => {
    try {
      const result = await loadAll();
      setDeals(result.deals);
      setLookups(result.lookups);
      setLoadError("");
      setStatus("ready");
    } catch (error) {
      setLoadError(errorText(error));
      setStatus("error");
    }
  }, []);

  // Initial load. State is set only inside the request callbacks, never synchronously in the effect body.
  useEffect(() => {
    let cancelled = false;
    loadAll()
      .then((result) => {
        if (cancelled) return;
        setDeals(result.deals);
        setLookups(result.lookups);
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

  const customerById = useMemo(() => new Map(lookups.customers.map((item) => [item.id, item])), [lookups.customers]);
  const propertyById = useMemo(() => new Map(lookups.properties.map((item) => [item.id, item])), [lookups.properties]);

  const customerOf = useCallback((deal: Deal) => dealCustomerName(customerById.get(deal.customer_profile_id)), [customerById]);
  const propertyOf = useCallback((deal: Deal) => dealPropertyTitle(propertyById.get(deal.property_id)), [propertyById]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return deals;
    return deals.filter((deal) =>
      [customerOf(deal), propertyOf(deal), dealStageLabel(deal.stage), deal.owner_name ?? ""].some((value) => value.toLowerCase().includes(needle)),
    );
  }, [deals, search, customerOf, propertyOf]);

  const sortValue = useCallback(
    (deal: Deal, key: string): string | number | null => {
      switch (key) {
        case "stage":
          return dealStageLabel(deal.stage);
        case "value": {
          const value = Number(deal.expected_value);
          return deal.expected_value != null && Number.isFinite(value) ? value : null;
        }
        case "owner":
          return deal.owner_name ?? null;
        case "created":
          return new Date(deal.created_at).getTime();
        case "updated":
          return new Date(deal.updated_at).getTime();
        default:
          return customerOf(deal);
      }
    },
    [customerOf],
  );

  const renderCell = useCallback(
    (deal: Deal, key: string) => {
      switch (key) {
        case "stage":
          return <Badge tone={dealStageTone(deal.stage)}>{dealStageLabel(deal.stage)}</Badge>;
        case "value":
          return formatDealAmount(deal.expected_value, deal.currency);
        case "owner":
          return deal.owner_name ?? "Unassigned";
        case "created":
          return formatShortDate(deal.created_at);
        case "updated":
          return formatShortDate(deal.updated_at);
        default:
          return (
            <span className="df-sales-stack">
              <strong className="df-sales-primary">{customerOf(deal)}</strong>
              <span className="df-sales-muted">{propertyOf(deal)}</span>
            </span>
          );
      }
    },
    [customerOf, propertyOf],
  );

  const filterValue = useCallback(
    (deal: Deal, key: string): string | null => {
      switch (key) {
        case "stage":
          return deal.stage;
        case "customer":
          return customerOf(deal);
        case "property":
          return propertyOf(deal);
        case "owner":
          return deal.owner_name ?? null;
        case "created":
          return deal.created_at;
        default:
          return null;
      }
    },
    [customerOf, propertyOf],
  );

  const selected = selectedId ? (deals.find((deal) => deal.id === selectedId) ?? null) : null;

  return (
    <div className="df-sales-page">
      <h1 className="df-visually-hidden">Deals</h1>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<Deal>
        gridId="deals"
        ariaLabel="Deals"
        columns={COLUMNS}
        rows={rows}
        rowKey={(deal) => deal.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void reload()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search deals"
        searchPlaceholder="Search customer, property, stage or agent"
        emptyTitle="No deals yet"
        emptyMessage="Create a deal for a customer and an available property to start tracking it."
        noMatchTitle="No deals match this search or filter"
        noMatchMessage="Try another search, or clear the filters."
        createLabel="New deal"
        onCreate={() => setCreateOpen(true)}
        onOpenRow={(deal) => setSelectedId(deal.id)}
        totalCount={deals.length}
        rangeLabel={search ? "Filtered" : "All deals shown"}
        filterFields={FILTER_FIELDS}
        filterValue={filterValue}
      />

      {selected ? (
        <DealRecordDialog
          key={selected.id}
          deal={selected}
          lookups={lookups}
          onClose={() => setSelectedId(null)}
          onChanged={(message) => {
            setNotice(message);
            void reload();
          }}
        />
      ) : null}

      {createOpen ? (
        <DealCreateDialog
          lookups={lookups}
          onClose={() => setCreateOpen(false)}
          onCreated={(message) => {
            setCreateOpen(false);
            setNotice(message);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}

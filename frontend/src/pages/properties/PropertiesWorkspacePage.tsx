import { useCallback, useEffect, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import type { GridFilterField } from "../../components/grid/gridFilters";
import SiteVisitHistory from "../../components/SiteVisitHistory";
import { RecordDialog, RecordProperty } from "../../components/record/RecordDialog";
import { Badge, Button, Dialog, SelectField } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { propertiesApi, type Property, type PropertyStatus } from "../../services/propertyApi";
import { fetchAllPages, formatShortDate, SALES_PAGE_SIZE } from "../sales/sales-shared";
import PropertyCreateDialog from "./PropertyCreateDialog";
import {
  PROPERTY_STATUSES,
  PROPERTY_TYPES,
  TRANSACTION_TYPES,
  enumLabel,
  formatAmount,
  propertyAddress,
  propertyLocation,
  propertyPriceLabel,
  propertyStatusTone,
  propertyTitle,
} from "./property-workflow";
import "../sales/sales.css";

const COLUMNS: GridColumnDef[] = [
  { key: "property", label: "Property", defaultWidth: 280, primary: true },
  { key: "transaction", label: "Transaction", defaultWidth: 120 },
  { key: "type", label: "Type", defaultWidth: 150, defaultVisible: false },
  { key: "location", label: "Location", defaultWidth: 200 },
  { key: "price", label: "Price / rent", defaultWidth: 170 },
  { key: "status", label: "Availability", defaultWidth: 150 },
  { key: "created", label: "Listed", defaultWidth: 130 },
  { key: "updated", label: "Last updated", defaultWidth: 140, defaultVisible: false },
];

const FILTER_FIELDS: readonly GridFilterField[] = [
  {
    key: "transaction",
    label: "Transaction",
    type: "select",
    options: TRANSACTION_TYPES.map((value) => ({ value, label: enumLabel(value) })),
  },
  {
    key: "status",
    label: "Availability",
    type: "select",
    options: PROPERTY_STATUSES.map((value) => ({ value, label: enumLabel(value) })),
  },
  {
    key: "type",
    label: "Property type",
    type: "select",
    options: PROPERTY_TYPES.map((value) => ({ value, label: enumLabel(value) })),
  },
  { key: "city", label: "City", type: "text" },
  { key: "locality", label: "Locality", type: "text" },
  { key: "listed", label: "Listed", type: "date" },
];

function filterValueOf(property: Property, key: string): string | null {
  switch (key) {
    case "transaction":
      return property.transaction_type;
    case "status":
      return property.status;
    case "type":
      return property.property_type;
    case "city":
      return property.city;
    case "locality":
      return property.locality;
    case "listed":
      return property.created_at;
    default:
      return null;
  }
}

function errorText(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Check your connection and try again.";
}

/**
 * Properties on the shared EnterpriseDataGrid. Rows open the property record, where availability can be changed and the visit
 * history is available. Listing and creation use the existing property endpoints. Owner is not part of the property record,
 * so no owner column is shown.
 */
export default function PropertiesWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [properties, setProperties] = useState<Property[]>([]);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [noticeTone, setNoticeTone] = useState<"success" | "error">("success");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [statusSaving, setStatusSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);

  const load = useCallback(async () => {
    return fetchAllPages((page) => propertiesApi.search({ page, page_size: SALES_PAGE_SIZE }));
  }, []);

  const reload = useCallback(async () => {
    try {
      setProperties(await load());
      setLoadError("");
      setStatus("ready");
    } catch (error) {
      setLoadError(errorText(error));
      setStatus("error");
    }
  }, [load]);

  // Initial load. State is set only inside the request callbacks, never synchronously in the effect body.
  useEffect(() => {
    let cancelled = false;
    load()
      .then((items) => {
        if (cancelled) return;
        setProperties(items);
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
  }, [load]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return properties;
    return properties.filter((property) =>
      [propertyTitle(property), propertyAddress(property), property.city ?? "", property.locality ?? ""].some((value) =>
        value.toLowerCase().includes(needle),
      ),
    );
  }, [properties, search]);

  const sortValue = useCallback((property: Property, key: string): string | number | null => {
    switch (key) {
      case "transaction":
        return enumLabel(property.transaction_type ?? "");
      case "type":
        return property.property_type ? enumLabel(property.property_type) : null;
      case "location":
        return propertyLocation(property) === "—" ? null : propertyLocation(property);
      case "price": {
        const n = Number(property.transaction_type === "RENT" ? property.rent : property.price);
        return Number.isFinite(n) ? n : null;
      }
      case "status":
        return property.status ? enumLabel(property.status) : null;
      case "created":
        return new Date(property.created_at).getTime();
      case "updated":
        return new Date(property.updated_at).getTime();
      default:
        return propertyTitle(property);
    }
  }, []);

  const renderCell = useCallback((property: Property, key: string) => {
    switch (key) {
      case "transaction":
        return property.transaction_type ? enumLabel(property.transaction_type) : "—";
      case "type":
        return property.property_type ? enumLabel(property.property_type) : "—";
      case "location":
        return propertyLocation(property);
      case "price":
        return propertyPriceLabel(property);
      case "status":
        return <Badge tone={propertyStatusTone(property.status)}>{property.status ? enumLabel(property.status) : "Unspecified"}</Badge>;
      case "created":
        return formatShortDate(property.created_at);
      case "updated":
        return formatShortDate(property.updated_at);
      default:
        return (
          <span className="df-sales-stack">
            <strong className="df-sales-primary">{propertyTitle(property)}</strong>
            <span className="df-sales-muted">{propertyAddress(property) || "No address"}</span>
          </span>
        );
    }
  }, []);

  const filterValue = useCallback((property: Property, key: string) => filterValueOf(property, key), []);

  const selected = selectedId ? (properties.find((property) => property.id === selectedId) ?? null) : null;

  async function changeStatus(property: Property, next: PropertyStatus) {
    if (next === property.status) return;
    setStatusSaving(true);
    setStatusMessage("");
    try {
      const updated = await propertiesApi.updateStatus(property.id, next);
      setProperties((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setNotice(`Property availability updated to ${enumLabel(next)}.`);
      setNoticeTone("success");
    } catch (error) {
      setStatusMessage(errorText(error));
    } finally {
      setStatusSaving(false);
    }
  }

  return (
    <div className="df-sales-page">
      <h1 className="df-visually-hidden">Properties</h1>

      {notice ? (
        <p className={noticeTone === "error" ? "df-sales-form-message df-sales-form-message--error" : "df-sales-notice"} role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<Property>
        gridId="properties"
        ariaLabel="Properties"
        columns={COLUMNS}
        rows={rows}
        rowKey={(property) => property.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void reload()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search properties"
        searchPlaceholder="Search address, locality or city"
        emptyTitle="Your property inventory starts here"
        emptyMessage="Add a property to start tracking listings, pricing and availability."
        noMatchTitle="No properties match this search or filter"
        noMatchMessage="Try another search, or clear the filters."
        createLabel="Add property"
        onCreate={() => setCreateOpen(true)}
        onOpenRow={(property) => {
          setSelectedId(property.id);
          setStatusMessage("");
          setHistoryOpen(false);
        }}
        totalCount={properties.length}
        rangeLabel={search ? "Filtered" : "All properties shown"}
        filterFields={FILTER_FIELDS}
        filterValue={filterValue}
      />

      {selected ? (
        <RecordDialog
          open
          onClose={() => setSelectedId(null)}
          eyebrow="Property"
          title={propertyTitle(selected)}
          closeLabel="Close property"
          status={<Badge tone={propertyStatusTone(selected.status)}>{selected.status ? enumLabel(selected.status) : "Unspecified"}</Badge>}
          main={
            <dl className="df-sales-properties">
              <RecordProperty label="Address">{propertyAddress(selected) || "—"}</RecordProperty>
              <RecordProperty label="Transaction">{selected.transaction_type ? enumLabel(selected.transaction_type) : "—"}</RecordProperty>
              <RecordProperty label="Price">{propertyPriceLabel(selected)}</RecordProperty>
              <RecordProperty label="Security deposit">{formatAmount(selected.security_deposit, selected.currency)}</RecordProperty>
              <RecordProperty label="Maintenance">{formatAmount(selected.maintenance_charge, selected.currency)}</RecordProperty>
              <RecordProperty label="Built-up area">{selected.built_up_area ? `${selected.built_up_area} sq. ft.` : "—"}</RecordProperty>
              <RecordProperty label="Carpet area">{selected.carpet_area ? `${selected.carpet_area} sq. ft.` : "—"}</RecordProperty>
              <RecordProperty label="Floor">
                {selected.floor_number !== null ? `${selected.floor_number}${selected.total_floors !== null ? ` of ${selected.total_floors}` : ""}` : "—"}
              </RecordProperty>
            </dl>
          }
          aside={
            <>
              <dl className="df-sales-properties">
                <RecordProperty label="Listed">{formatShortDate(selected.created_at)}</RecordProperty>
                <RecordProperty label="Last updated">{formatShortDate(selected.updated_at)}</RecordProperty>
              </dl>
              <div className="df-sales-aside-actions">
                <SelectField
                  label="Availability"
                  value={selected.status ?? ""}
                  disabled={statusSaving}
                  error={statusMessage || undefined}
                  options={PROPERTY_STATUSES.map((value) => ({ value, label: enumLabel(value) }))}
                  onChange={(event) => void changeStatus(selected, event.target.value as PropertyStatus)}
                />
                <Button variant="secondary" size="sm" onClick={() => setHistoryOpen(true)}>
                  View visit history
                </Button>
              </div>
            </>
          }
        />
      ) : null}

      {selected && historyOpen ? (
        <Dialog open onClose={() => setHistoryOpen(false)} title="Visit history" closeLabel="Close visit history" description={propertyTitle(selected)} size="lg" footer={<Button variant="secondary" onClick={() => setHistoryOpen(false)}>Close</Button>}>
          <SiteVisitHistory propertyId={selected.id} title="Property site visits" />
        </Dialog>
      ) : null}

      {createOpen ? (
        <PropertyCreateDialog
          onClose={() => setCreateOpen(false)}
          onCreated={(message) => {
            setCreateOpen(false);
            setNotice(message);
            setNoticeTone("success");
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}


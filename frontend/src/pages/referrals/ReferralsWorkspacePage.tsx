import { useCallback, useEffect, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import type { GridFilterField } from "../../components/grid/gridFilters";
import { Badge } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { contactsApi, type Contact } from "../../services/contactApi";
import { customerProfilesApi, type CustomerProfile } from "../../services/customerProfileApi";
import { dealsApi, type Deal } from "../../services/dealApi";
import { referralsApi, type Referral } from "../../services/referralApi";
import { fetchAllPages, formatShortDate, personName, SALES_PAGE_SIZE } from "../sales/sales-shared";
import "../sales/sales.css";
import ReferralRecordDialog from "./ReferralRecordDialog";
import { REFERRAL_STATUSES, customerLabel, referralStatusLabel, referralStatusTone } from "./referral-workflow";

const COLUMNS: GridColumnDef[] = [
  { key: "referral", label: "Referral", defaultWidth: 260, primary: true },
  { key: "referrer", label: "Referrer", defaultWidth: 190 },
  { key: "customer", label: "Customer", defaultWidth: 190 },
  { key: "deal", label: "Related deal", defaultWidth: 160 },
  { key: "status", label: "Status", defaultWidth: 150 },
  { key: "referred", label: "Referral date", defaultWidth: 140 },
  { key: "updated", label: "Last updated", defaultWidth: 140, defaultVisible: false },
];

const FILTER_FIELDS: readonly GridFilterField[] = [
  {
    key: "status",
    label: "Status",
    type: "select",
    options: REFERRAL_STATUSES.map((item) => ({ value: item.value, label: item.label })),
  },
  { key: "name", label: "Referral", type: "text" },
  { key: "referrer", label: "Referrer", type: "text" },
  { key: "customer", label: "Customer", type: "text" },
  { key: "referred", label: "Referral date", type: "date" },
];

interface ReferralLookupData {
  customers: CustomerProfile[];
  contacts: Contact[];
  deals: Deal[];
}

function errorText(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Check your connection and try again.";
}

/**
 * Referrals on the shared EnterpriseDataGrid. Rows open the referral record, which creates, shows and edits the same fields.
 * Commission and referral value are not part of the referral record, so no value column is shown.
 */
export default function ReferralsWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [referrals, setReferrals] = useState<Referral[]>([]);
  const [lookups, setLookups] = useState<ReferralLookupData>({ customers: [], contacts: [], deals: [] });
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    const [items, customers, contacts, deals] = await Promise.all([
      fetchAllPages(async (page) => {
        // The referral list reports a total rather than a page count, so derive the page count from it.
        const result = await referralsApi.list({ page, page_size: SALES_PAGE_SIZE });
        return { items: result.items, total_pages: Math.ceil(result.total / SALES_PAGE_SIZE) };
      }),
      fetchAllPages((page) => customerProfilesApi.list({ page, page_size: SALES_PAGE_SIZE })),
      fetchAllPages((page) => contactsApi.list({ page, page_size: SALES_PAGE_SIZE })),
      fetchAllPages((page) => dealsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    ]);
    return { items, lookups: { customers, contacts, deals } };
  }, []);

  const reload = useCallback(async () => {
    try {
      const result = await load();
      setReferrals(result.items);
      setLookups(result.lookups);
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
      .then((result) => {
        if (cancelled) return;
        setReferrals(result.items);
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
  }, [load]);

  const customerById = useMemo(() => new Map(lookups.customers.map((item) => [item.id, item])), [lookups.customers]);
  const contactById = useMemo(() => new Map(lookups.contacts.map((item) => [item.id, item])), [lookups.contacts]);
  const dealById = useMemo(() => new Map(lookups.deals.map((item) => [item.id, item])), [lookups.deals]);

  const customerName = useCallback(
    (referral: Referral) => {
      const customer = referral.customer_profile_id ? customerById.get(referral.customer_profile_id) : undefined;
      return customer ? customerLabel(customer) : null;
    },
    [customerById],
  );

  const referrerName = useCallback(
    (referral: Referral) => {
      const contact = referral.referrer_contact_id ? contactById.get(referral.referrer_contact_id) : undefined;
      return contact ? personName(contact) || "Unnamed contact" : null;
    },
    [contactById],
  );

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return referrals;
    return referrals.filter((referral) =>
      [referral.referral_name, referral.referral_phone ?? "", referral.referral_email ?? "", referrerName(referral) ?? "", customerName(referral) ?? ""].some((value) =>
        value.toLowerCase().includes(needle),
      ),
    );
  }, [referrals, search, referrerName, customerName]);

  const sortValue = useCallback(
    (referral: Referral, key: string): string | number | null => {
      switch (key) {
        case "referrer":
          return referrerName(referral);
        case "customer":
          return customerName(referral);
        case "deal":
          return referral.deal_id ? (dealById.get(referral.deal_id)?.stage ?? "Linked") : null;
        case "status":
          return referralStatusLabel(referral.status);
        case "referred":
          return new Date(referral.created_at).getTime();
        case "updated":
          return new Date(referral.updated_at).getTime();
        default:
          return referral.referral_name;
      }
    },
    [customerName, referrerName, dealById],
  );

  const renderCell = useCallback(
    (referral: Referral, key: string) => {
      switch (key) {
        case "referrer":
          return referrerName(referral) ?? "—";
        case "customer":
          return customerName(referral) ?? (referral.customer_profile_id ? "Linked" : "—");
        case "deal": {
          if (!referral.deal_id) return "—";
          const deal = dealById.get(referral.deal_id);
          return deal ? deal.stage.replace(/_/g, " ").toLowerCase() : "Linked";
        }
        case "status":
          return <Badge tone={referralStatusTone(referral.status)}>{referralStatusLabel(referral.status)}</Badge>;
        case "referred":
          return formatShortDate(referral.created_at);
        case "updated":
          return formatShortDate(referral.updated_at);
        default:
          return (
            <span className="df-sales-stack">
              <strong className="df-sales-primary">{referral.referral_name}</strong>
              <span className="df-sales-muted">{referral.referral_phone || referral.referral_email || "No contact details"}</span>
            </span>
          );
      }
    },
    [referrerName, customerName, dealById],
  );

  const filterValue = useCallback(
    (referral: Referral, key: string): string | null => {
      switch (key) {
        case "status":
          return referral.status;
        case "name":
          return referral.referral_name;
        case "referrer":
          return referrerName(referral);
        case "customer":
          return customerName(referral);
        case "referred":
          return referral.created_at;
        default:
          return null;
      }
    },
    [referrerName, customerName],
  );

  const selected = selectedId ? (referrals.find((referral) => referral.id === selectedId) ?? null) : null;

  return (
    <div className="df-sales-page">
      <h1 className="df-visually-hidden">Referrals</h1>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<Referral>
        gridId="referrals"
        ariaLabel="Referrals"
        columns={COLUMNS}
        rows={rows}
        rowKey={(referral) => referral.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void reload()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search referrals"
        searchPlaceholder="Search referral name, email, phone or referrer"
        emptyTitle="No referrals yet"
        emptyMessage="Record a referral to link it to a referrer, a customer or a deal."
        noMatchTitle="No referrals match this search or filter"
        noMatchMessage="Try another search, or clear the filters."
        createLabel="New referral"
        onCreate={() => setCreateOpen(true)}
        onOpenRow={(referral) => setSelectedId(referral.id)}
        totalCount={referrals.length}
        rangeLabel={search ? "Filtered" : "All referrals shown"}
        filterFields={FILTER_FIELDS}
        filterValue={filterValue}
      />

      {selected ? (
        <ReferralRecordDialog
          key={selected.id}
          referral={selected}
          lookups={lookups}
          onClose={() => setSelectedId(null)}
          onSaved={(message) => {
            setSelectedId(null);
            setNotice(message);
            void reload();
          }}
        />
      ) : null}

      {createOpen ? (
        <ReferralRecordDialog
          lookups={lookups}
          onClose={() => setCreateOpen(false)}
          onSaved={(message) => {
            setCreateOpen(false);
            setNotice(message);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
}

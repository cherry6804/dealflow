import { useCallback, useEffect, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import type { GridFilterField, GridFilterOption } from "../../components/grid/gridFilters";
import SiteVisitHistory from "../../components/SiteVisitHistory";
import { RecordDetailDialog, RecordProperty } from "../../components/record/RecordDetailDialog";
import { Badge, Button, Dialog } from "../../components/ui";
import { contactsApi, type Contact } from "../../services/contactApi";
import { customerProfilesApi, type CustomerProfile } from "../../services/customerProfileApi";
import { leadsApi, type Lead } from "../../services/leadApi";
import { propertiesApi, type Property } from "../../services/propertyApi";
import { siteVisitsApi, type SiteVisit } from "../../services/siteVisitApi";
import { teamApi, type TeamMember } from "../../services/teamApi";
import LeadDetailDialog from "./leads/LeadDetailDialog";
import { contactDisplayName, fetchAllPages, formatShortDate, messageFrom, SALES_PAGE_SIZE } from "./sales-shared";
import { AttendanceDialog, ScheduleVisitDialog, VisitFollowUpDialog } from "./site-visits/SiteVisitForms";
import {
  SITE_VISIT_OUTCOMES,
  SITE_VISIT_STATUSES,
  propertyLabel,
  siteVisitOutcomeLabel,
  siteVisitStatusLabel,
  visitDateLabel,
  visitPersonLabel,
} from "./site-visits/site-visit-labels";
import "./sales.css";

const COLUMNS: GridColumnDef[] = [
  { key: "scheduled", label: "Visit date & time", defaultWidth: 210, primary: true },
  { key: "property", label: "Property", defaultWidth: 260 },
  { key: "person", label: "Lead / customer", defaultWidth: 200 },
  { key: "agent", label: "Assigned agent", defaultWidth: 170 },
  { key: "status", label: "Status", defaultWidth: 140 },
  { key: "outcome", label: "Outcome", defaultWidth: 170 },
  { key: "followUp", label: "Follow-up", defaultWidth: 120 },
  { key: "notes", label: "Notes", defaultWidth: 240, defaultVisible: false },
  { key: "updated", label: "Last updated", defaultWidth: 140, defaultVisible: false },
];

/**
 * Site visits on the shared EnterpriseDataGrid. Scheduling, attendance, follow-ups and history use the existing endpoints. The
 * visit contract has no reference number and no reschedule action, so neither is shown.
 */
export default function SiteVisitsWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [visits, setVisits] = useState<SiteVisit[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [customers, setCustomers] = useState<CustomerProfile[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [dialog, setDialog] = useState<"schedule" | "attendance" | "followUp" | null>(null);
  const [dialogVisitId, setDialogVisitId] = useState<string | null>(null);
  const [leadOpenId, setLeadOpenId] = useState<string | null>(null);


  const loadAll = useCallback(async () => {
    const [allVisits, allProperties, allLeads, allCustomers, allContacts] = await Promise.all([
      fetchAllPages((page) => siteVisitsApi.list({ page, page_size: SALES_PAGE_SIZE })),
      fetchAllPages((page) => propertiesApi.search({ page, page_size: SALES_PAGE_SIZE })),
      fetchAllPages((page) => leadsApi.list({ page, page_size: SALES_PAGE_SIZE })),
      fetchAllPages((page) => customerProfilesApi.list({ page, page_size: SALES_PAGE_SIZE })),
      fetchAllPages((page) => contactsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    ]);
    const team = await teamApi.listMembers().catch(() => [] as TeamMember[]);
    return { allVisits, allProperties, allLeads, allCustomers, allContacts, team };
  }, []);

  const applyLoaded = useCallback((result: Awaited<ReturnType<typeof loadAll>>) => {
    setVisits(result.allVisits);
    setProperties(result.allProperties);
    setLeads(result.allLeads);
    setCustomers(result.allCustomers);
    setContacts(result.allContacts);
    setMembers(result.team);
    setLoadError("");
    setStatus("ready");
  }, []);

  const reload = useCallback(async () => {
    try {
      applyLoaded(await loadAll());
    } catch (error) {
      setLoadError(messageFrom(error, "Check your connection and try again."));
      setStatus("error");
    }
  }, [applyLoaded, loadAll]);

  // Initial load. State is set only inside the request callbacks, never synchronously in the effect body.
  useEffect(() => {
    let cancelled = false;
    loadAll()
      .then((result) => {
        if (!cancelled) applyLoaded(result);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(messageFrom(error, "Check your connection and try again."));
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [applyLoaded, loadAll]);

  const propertyById = useMemo(() => new Map(properties.map((property) => [property.id, property])), [properties]);
  const leadById = useMemo(() => new Map(leads.map((lead) => [lead.id, lead])), [leads]);
  const customerById = useMemo(() => new Map(customers.map((customer) => [customer.id, customer])), [customers]);
  const contactById = useMemo(() => new Map(contacts.map((contact) => [contact.id, contact])), [contacts]);
  const ownerName = useMemo(() => new Map(members.map((member) => [member.user_id, member.display_name])), [members]);

  const leadNameOf = useCallback((lead: Lead) => contactDisplayName(contactById.get(lead.contact_id)), [contactById]);
  const personOf = useCallback(
    (visit: SiteVisit) => visitPersonLabel(visit, leadById, customerById, leadNameOf),
    [leadById, customerById, leadNameOf],
  );

  const propertyOptions = useMemo<GridFilterOption[]>(() => {
    const used = new Set(visits.map((visit) => visit.property_id));
    return properties
      .filter((property) => used.has(property.id))
      .map((property) => ({ value: property.id, label: propertyLabel(property, property.id) }));
  }, [properties, visits]);

  const agentOptions = useMemo<GridFilterOption[]>(() => {
    const used = new Set(visits.map((visit) => visit.owner_user_id));
    return members.filter((member) => used.has(member.user_id)).map((member) => ({ value: member.user_id, label: member.display_name }));
  }, [members, visits]);

  const filterFields = useMemo<GridFilterField[]>(() => {
    const fields: GridFilterField[] = [
      {
        key: "status",
        label: "Status",
        type: "select",
        options: SITE_VISIT_STATUSES.map((item) => ({ value: item.value, label: item.label })),
      },
      {
        key: "outcome",
        label: "Outcome",
        type: "select",
        options: SITE_VISIT_OUTCOMES.map((item) => ({ value: item.value, label: item.label })),
      },
    ];
    if (propertyOptions.length > 0) fields.push({ key: "property", label: "Property", type: "select", options: propertyOptions });
    fields.push({ key: "person", label: "Lead / customer", type: "text" });
    if (agentOptions.length > 0) fields.push({ key: "agent", label: "Assigned agent", type: "select", options: agentOptions });
    fields.push(
      { key: "scheduled", label: "Visit date", type: "date" },
      {
        key: "followUp",
        label: "Follow-up",
        type: "select",
        options: [
          { value: "yes", label: "Has follow-up" },
          { value: "no", label: "No follow-up" },
        ],
      },
    );
    return fields;
  }, [propertyOptions, agentOptions]);

  const readFilterValue = useCallback(
    (visit: SiteVisit, key: string): string | null => {
      switch (key) {
        case "status":
          return visit.status;
        case "outcome":
          return visit.outcome;
        case "property":
          return visit.property_id;
        case "person": {
          const label = personOf(visit);
          return label === "Not linked" ? null : label;
        }
        case "agent":
          return visit.owner_user_id;
        case "scheduled":
          return visit.scheduled_at;
        case "followUp":
          return visit.has_follow_up ? "yes" : "no";
        default:
          return null;
      }
    },
    [personOf],
  );

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return visits;
    return visits.filter((visit) => {
      const property = propertyById.get(visit.property_id);
      return [propertyLabel(property, visit.property_id), personOf(visit), siteVisitStatusLabel(visit.status), visit.notes ?? ""].some((value) =>
        value.toLowerCase().includes(needle),
      );
    });
  }, [visits, search, propertyById, personOf]);

  const sortValue = useCallback(
    (visit: SiteVisit, key: string): string | number | null => {
      switch (key) {
        case "property":
          return propertyLabel(propertyById.get(visit.property_id), visit.property_id);
        case "person":
          return personOf(visit);
        case "agent":
          return ownerName.get(visit.owner_user_id) ?? null;
        case "status":
          return siteVisitStatusLabel(visit.status);
        case "outcome":
          return visit.outcome ? siteVisitOutcomeLabel(visit.outcome) : null;
        case "followUp":
          return visit.has_follow_up ? 1 : 0;
        case "notes":
          return visit.notes?.trim() || null;
        case "updated":
          return new Date(visit.updated_at).getTime();
        default:
          return new Date(visit.scheduled_at).getTime();
      }
    },
    [propertyById, personOf, ownerName],
  );

  const renderCell = useCallback(
    (visit: SiteVisit, key: string) => {
      switch (key) {
        case "property":
          return propertyLabel(propertyById.get(visit.property_id), visit.property_id);
        case "person":
          return personOf(visit);
        case "agent":
          return ownerName.get(visit.owner_user_id) ?? "—";
        case "status":
          return (
            <Badge tone={visit.status === "COMPLETED" ? "success" : visit.status === "SCHEDULED" ? "active" : visit.status === "NO_SHOW" ? "pending" : "danger"}>
              {siteVisitStatusLabel(visit.status)}
            </Badge>
          );
        case "outcome":
          return siteVisitOutcomeLabel(visit.outcome);
        case "followUp":
          return visit.has_follow_up ? "Scheduled" : "—";
        case "notes":
          return visit.notes?.trim() || "—";
        case "updated":
          return formatShortDate(visit.updated_at);
        default:
          return <strong className="df-sales-primary">{visitDateLabel(visit.scheduled_at)}</strong>;
      }
    },
    [propertyById, personOf, ownerName],
  );

  const selected = selectedId ? (visits.find((visit) => visit.id === selectedId) ?? null) : null;
  const selectedLead = leadOpenId ? (leadById.get(leadOpenId) ?? null) : null;
  const dialogVisit = dialogVisitId ? (visits.find((visit) => visit.id === dialogVisitId) ?? null) : null;

  function openVisitDialog(kind: "attendance" | "followUp", visit: SiteVisit) {
    setDialogVisitId(visit.id);
    setDialog(kind);
  }

  function closeDialog() {
    setDialog(null);
    setDialogVisitId(null);
  }

  function afterSave(message: string) {
    closeDialog();
    setNotice(message);
    void reload();
  }

  return (
    <div className="df-sales-page">
      <h1 className="df-visually-hidden">Site visits</h1>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<SiteVisit>
        gridId="site-visits"
        ariaLabel="Site visits"
        columns={COLUMNS}
        rows={rows}
        rowKey={(visit) => visit.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void reload()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search site visits"
        searchPlaceholder="Search property, lead, customer or notes"
        emptyTitle="No site visits yet"
        emptyMessage="Schedule a visit for a property with a lead or customer."
        noMatchTitle="No site visits match this search or filter"
        noMatchMessage="Try another search, or clear the filters."
        createLabel="Schedule visit"
        onCreate={() => setDialog("schedule")}
        onOpenRow={(visit) => {
          setSelectedId(visit.id);
          setHistoryOpen(false);
        }}
        totalCount={visits.length}
        rangeLabel={search ? "Filtered" : "All visits shown"}
        filterFields={filterFields}
        filterValue={readFilterValue}
      />

      {selected ? (
        <RecordDetailDialog
          open
          onClose={() => setSelectedId(null)}
          eyebrow="Site visit"
          title={visitDateLabel(selected.scheduled_at)}
          closeLabel="Close site visit"
          main={
            <dl className="df-sales-properties">
              <RecordProperty label="Property">{propertyLabel(propertyById.get(selected.property_id), selected.property_id)}</RecordProperty>
              <RecordProperty label="Lead / customer">
                {selected.lead_id ? (
                  <Button variant="tertiary" size="sm" onClick={() => setLeadOpenId(selected.lead_id)}>
                    {personOf(selected)}
                  </Button>
                ) : (
                  personOf(selected)
                )}
              </RecordProperty>
              <RecordProperty label="Assigned agent">{ownerName.get(selected.owner_user_id) ?? "—"}</RecordProperty>
              <RecordProperty label="Ends">{selected.ends_at ? visitDateLabel(selected.ends_at) : "Not set"}</RecordProperty>
              <RecordProperty label="Notes">{selected.notes?.trim() || "—"}</RecordProperty>
              <RecordProperty label="Feedback">{selected.feedback?.trim() || "—"}</RecordProperty>
            </dl>
          }
          aside={
            <>
              <dl className="df-sales-properties">
                <RecordProperty label="Status">
                  <Badge tone={selected.status === "COMPLETED" ? "success" : "active"}>{siteVisitStatusLabel(selected.status)}</Badge>
                </RecordProperty>
                <RecordProperty label="Outcome">{siteVisitOutcomeLabel(selected.outcome)}</RecordProperty>
                <RecordProperty label="Follow-up">{selected.has_follow_up ? "Scheduled" : "None"}</RecordProperty>
                <RecordProperty label="Last updated">{formatShortDate(selected.updated_at)}</RecordProperty>
              </dl>
              <div className="df-sales-aside-actions">
                <Button variant="primary" size="sm" onClick={() => openVisitDialog("attendance", selected)}>
                  Record attendance
                </Button>
                <Button variant="secondary" size="sm" onClick={() => openVisitDialog("followUp", selected)} disabled={!selected.lead_id}>
                  Create follow-up
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setHistoryOpen(true)} disabled={!selected.lead_id && !selected.customer_profile_id}>
                  View visit history
                </Button>
              </div>
            </>
          }
        />
      ) : null}

      {selected && historyOpen ? (
        <Dialog open onClose={() => setHistoryOpen(false)} title="Visit history" closeLabel="Close visit history" size="lg">
          <SiteVisitHistory
            leadId={selected.lead_id ?? undefined}
            customerProfileId={selected.customer_profile_id ?? undefined}
            title="Site visit history"
          />
        </Dialog>
      ) : null}

      {selectedLead ? (
        <LeadDetailDialog
          key={selectedLead.id}
          lead={selectedLead}
          contact={contactById.get(selectedLead.contact_id)}
          ownerName={selectedLead.owner_user_id ? (ownerName.get(selectedLead.owner_user_id) ?? null) : null}
          onClose={() => setLeadOpenId(null)}
          onLeadChanged={(updated) => setLeads((current) => current.map((item) => (item.id === updated.id ? updated : item)))}
          onNotice={setNotice}
          onFollowUpsChanged={() => void reload()}
        />
      ) : null}

      {dialog === "schedule" ? (
        <ScheduleVisitDialog
          properties={properties}
          leads={leads}
          customers={customers}
          leadLabel={leadNameOf}
          onClose={closeDialog}
          onSaved={afterSave}
        />
      ) : null}
      {dialog === "attendance" && dialogVisit ? <AttendanceDialog visit={dialogVisit} onClose={closeDialog} onSaved={afterSave} /> : null}
      {dialog === "followUp" && dialogVisit ? <VisitFollowUpDialog visit={dialogVisit} onClose={closeDialog} onSaved={afterSave} /> : null}
    </div>
  );
}

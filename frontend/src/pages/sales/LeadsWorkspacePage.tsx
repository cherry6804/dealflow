import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import type { GridFilterOption } from "../../components/grid/gridFilters";
import { Badge, Button, Dialog, SelectField, TextField } from "../../components/ui";
import { toIsoDateTime, toLocalDateTimeInput } from "../../lib/dateTimeInput";
import { contactsApi, type Contact } from "../../services/contactApi";
import { leadsApi, type Lead, type LeadInterest } from "../../services/leadApi";
import { teamApi, type TeamMember } from "../../services/teamApi";
import LeadDetailDialog from "./leads/LeadDetailDialog";
import { buildLeadFilterFields, leadFilterValue } from "./leads/lead-filters";
import { LEAD_INTERESTS, formatStageLabel, stageTone } from "./leads/lead-workflow";
import { contactDisplayName, fetchAllPages, formatDateTime, formatShortDate, messageFrom, personName, SALES_PAGE_SIZE } from "./sales-shared";
import "./sales.css";

const COLUMNS: GridColumnDef[] = [
  { key: "lead", label: "Lead", defaultWidth: 240, primary: true },
  { key: "email", label: "Email address", defaultWidth: 230 },
  { key: "phone", label: "Phone", defaultWidth: 160 },
  { key: "status", label: "Stage", defaultWidth: 150 },
  { key: "interest", label: "Interest", defaultWidth: 120 },
  { key: "next", label: "Next follow-up", defaultWidth: 260 },
  { key: "owner", label: "Owner", defaultWidth: 170 },
  { key: "created", label: "Created", defaultWidth: 130 },
  { key: "updated", label: "Last updated", defaultWidth: 140, defaultVisible: false },
];

/**
 * Leads on the shared EnterpriseDataGrid. Rows open the lead record, where stage, interest, next action, follow-ups and the
 * timeline keep their existing rules. Source is not part of the lead contract, so it is not shown.
 */
export default function LeadsWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [createContacts, setCreateContacts] = useState<Contact[]>([]);
  const [createContactId, setCreateContactId] = useState("");
  const [createInterest, setCreateInterest] = useState<"" | LeadInterest>("");
  const [createAction, setCreateAction] = useState("");
  const [createDate, setCreateDate] = useState("");
  const [createError, setCreateError] = useState("");
  const [createSaving, setCreateSaving] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);

  const loadAll = useCallback(async () => {
    const [allLeads, allContacts] = await Promise.all([
      fetchAllPages((page) => leadsApi.list({ page, page_size: SALES_PAGE_SIZE })),
      fetchAllPages((page) => contactsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    ]);
    // Owner names come from the team list. If the list is not available to this user, owners show as unnamed rather than failing.
    const team = await teamApi.listMembers().catch(() => [] as TeamMember[]);
    return { allLeads, allContacts, team };
  }, []);

  const applyLoaded = useCallback((result: { allLeads: Lead[]; allContacts: Contact[]; team: TeamMember[] }) => {
    setLeads(result.allLeads);
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

  const contactById = useMemo(() => new Map(contacts.map((contact) => [contact.id, contact])), [contacts]);
  const ownerName = useMemo(() => new Map(members.map((member) => [member.user_id, member.display_name])), [members]);
  const ownerOptions = useMemo<GridFilterOption[]>(
    () => members.map((member) => ({ value: member.user_id, label: member.display_name })),
    [members],
  );
  const filterFields = useMemo(() => buildLeadFilterFields(ownerOptions), [ownerOptions]);
  const readFilterValue = useCallback((lead: Lead, key: string) => leadFilterValue(lead, key, (id) => contactById.get(id)), [contactById]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return leads;
    return leads.filter((lead) => {
      const contact = contactById.get(lead.contact_id);
      return [contactDisplayName(contact), contact?.email ?? "", contact?.phone ?? "", lead.next_action ?? "", formatStageLabel(lead.status)].some((value) =>
        value.toLowerCase().includes(needle),
      );
    });
  }, [leads, search, contactById]);

  const sortValue = useCallback(
    (lead: Lead, key: string): string | number | null => {
      const contact = contactById.get(lead.contact_id);
      switch (key) {
        case "email":
          return contact?.email ?? null;
        case "phone":
          return contact?.phone ?? null;
        case "status":
          return formatStageLabel(lead.status);
        case "interest":
          return lead.interest ? formatStageLabel(lead.interest) : null;
        case "next":
          return lead.next_action_at ? new Date(lead.next_action_at).getTime() : null;
        case "owner":
          return lead.owner_user_id ? (ownerName.get(lead.owner_user_id) ?? null) : null;
        case "created":
          return new Date(lead.created_at).getTime();
        case "updated":
          return new Date(lead.updated_at).getTime();
        default:
          return contact ? personName(contact) : null;
      }
    },
    [contactById, ownerName],
  );

  const renderCell = useCallback(
    (lead: Lead, key: string) => {
      const contact = contactById.get(lead.contact_id);
      switch (key) {
        case "email":
          return contact?.email ?? "—";
        case "phone":
          return contact?.phone ?? "—";
        case "status":
          return (
            <Badge tone={stageTone(lead.status)}>
              {formatStageLabel(lead.status)}
              {lead.is_active ? "" : " · Inactive"}
            </Badge>
          );
        case "interest":
          return lead.interest ? formatStageLabel(lead.interest) : "Not set";
        case "next":
          return lead.next_action ? (
            <span>
              <strong>{lead.next_action}</strong>
              <span className="df-sales-muted">{lead.next_action_at ? ` · ${formatDateTime(lead.next_action_at)}` : ""}</span>
            </span>
          ) : (
            <span className="df-sales-muted">No next action</span>
          );
        case "owner":
          return lead.owner_user_id ? (ownerName.get(lead.owner_user_id) ?? "—") : "Unassigned";
        case "created":
          return formatShortDate(lead.created_at);
        case "updated":
          return formatShortDate(lead.updated_at);
        default:
          return <strong className="df-sales-primary">{contactDisplayName(contact)}</strong>;
      }
    },
    [contactById, ownerName],
  );

  async function openCreate() {
    setCreateOpen(true);
    setCreateContactId("");
    setCreateInterest("");
    setCreateAction("");
    setCreateDate(toLocalDateTimeInput(new Date().toISOString()));
    setCreateError("");
    setCreateLoading(true);
    try {
      setCreateContacts(await fetchAllPages((page) => contactsApi.list({ page, page_size: SALES_PAGE_SIZE, is_active: true })));
    } catch (error) {
      setCreateError(messageFrom(error, "Contacts could not be loaded. Try again."));
    } finally {
      setCreateLoading(false);
    }
  }

  async function submitCreate(event: FormEvent) {
    event.preventDefault();
    if (!createContactId) {
      setCreateError("Choose a contact before creating the lead.");
      return;
    }
    const action = createAction.trim();
    if (createDate && !action) {
      setCreateError("Enter a next action when scheduling a date.");
      return;
    }
    setCreateSaving(true);
    setCreateError("");
    try {
      await leadsApi.create({
        contact_id: createContactId,
        interest: createInterest || null,
        next_action: action || null,
        next_action_at: toIsoDateTime(createDate),
      });
      setCreateOpen(false);
      setNotice("Lead created successfully.");
      await reload();
    } catch (error) {
      setCreateError(messageFrom(error, "The lead could not be created. Try again."));
    } finally {
      setCreateSaving(false);
    }
  }

  const selected = selectedId ? (leads.find((lead) => lead.id === selectedId) ?? null) : null;

  return (
    <div className="df-sales-page">
      <h1 className="df-visually-hidden">Leads</h1>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<Lead>
        gridId="leads"
        ariaLabel="Leads"
        columns={COLUMNS}
        rows={rows}
        rowKey={(lead) => lead.id}
        sortValue={sortValue}
        renderCell={renderCell}
        status={status}
        errorMessage={loadError}
        onRetry={() => void reload()}
        searchValue={search}
        onSearchChange={setSearch}
        searchLabel="Search leads"
        searchPlaceholder="Search name, email, phone or next action"
        emptyTitle="No leads yet"
        emptyMessage="Create a lead from an existing contact to start tracking it through the pipeline."
        noMatchTitle="No leads match this search or filter"
        noMatchMessage="Try another search, or clear the filters."
        createLabel="New lead"
        onCreate={() => void openCreate()}
        onOpenRow={(lead) => setSelectedId(lead.id)}
        totalCount={leads.length}
        rangeLabel={search ? "Filtered" : "All leads shown"}
        filterFields={filterFields}
        filterValue={readFilterValue}
      />

      {selected ? (
        <LeadDetailDialog
          key={selected.id}
          lead={selected}
          contact={contactById.get(selected.contact_id)}
          ownerName={selected.owner_user_id ? (ownerName.get(selected.owner_user_id) ?? null) : null}
          onClose={() => setSelectedId(null)}
          onLeadChanged={(updated) => setLeads((current) => current.map((item) => (item.id === updated.id ? updated : item)))}
          onNotice={setNotice}
          onFollowUpsChanged={() => void reload()}
        />
      ) : null}

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New lead" closeLabel="Close new lead" description="Create a lead from an existing active contact.">
        <form className="df-sales-form" onSubmit={submitCreate} noValidate>
          {createLoading ? (
            <p className="df-sales-form-message" role="status">
              Loading contacts…
            </p>
          ) : (
            <div className="df-sales-form-grid">
              <SelectField
                label="Contact"
                required
                value={createContactId}
                disabled={createSaving || createContacts.length === 0}
                helper={createContacts.length === 0 ? "There are no active contacts to create a lead from." : undefined}
                options={[
                  { value: "", label: "Select a contact" },
                  ...createContacts.map((contact) => ({
                    value: contact.id,
                    label: [contactDisplayName(contact), contact.email, contact.phone].filter(Boolean).join(" · "),
                  })),
                ]}
                onChange={(event) => setCreateContactId(event.target.value)}
              />
              <SelectField
                label="Interest"
                value={createInterest}
                disabled={createSaving}
                options={[{ value: "", label: "Not set" }, ...LEAD_INTERESTS.map((level) => ({ value: level, label: formatStageLabel(level) }))]}
                onChange={(event) => setCreateInterest(event.target.value as "" | LeadInterest)}
              />
              <TextField label="Next action" value={createAction} disabled={createSaving} onChange={(event) => setCreateAction(event.target.value)} />
              <TextField label="Next action date" type="datetime-local" value={createDate} disabled={createSaving} onChange={(event) => setCreateDate(event.target.value)} />
            </div>
          )}
          <div className="df-sales-form-actions">
            {createError ? (
              <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                {createError}
              </p>
            ) : null}
            <Button variant="secondary" onClick={() => setCreateOpen(false)} disabled={createSaving}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={createSaving} disabled={createLoading || !createContactId}>
              Create lead
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}

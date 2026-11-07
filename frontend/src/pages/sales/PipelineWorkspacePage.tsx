import { useCallback, useEffect, useMemo, useState } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import LeadTimeline from "../../components/LeadTimeline";
import { RecordDetailDialog, RecordProperty } from "../../components/record/RecordDetailDialog";
import { Badge, Button, SelectField, TextField } from "../../components/ui";
import { contactsApi, type Contact } from "../../services/contactApi";
import { leadsApi, type Lead, type LeadStatus } from "../../services/leadApi";
import { teamApi, type TeamMember } from "../../services/teamApi";
import PipelinePage from "../PipelinePage";
import LeadFollowUpsDialog from "./leads/LeadFollowUpsDialog";
import { ALLOWED_STATUS_TRANSITIONS, LEAD_STATUSES, formatStageLabel, outcomeForStatusChange, stageTone } from "./leads/lead-workflow";
import { fetchAllPages, formatDateTime, formatShortDate, messageFrom, personName, SALES_PAGE_SIZE } from "./sales-shared";
import "./sales.css";

type Visibility = "active" | "inactive" | "all";
type View = "list" | "board";

const COLUMNS: GridColumnDef[] = [
  { key: "lead", label: "Lead", defaultWidth: 240, primary: true },
  { key: "status", label: "Stage", defaultWidth: 150 },
  { key: "email", label: "Email address", defaultWidth: 230 },
  { key: "phone", label: "Phone", defaultWidth: 160 },
  { key: "interest", label: "Interest", defaultWidth: 120 },
  { key: "next", label: "Next action", defaultWidth: 240 },
  { key: "due", label: "Follow-up due", defaultWidth: 170 },
  { key: "owner", label: "Owner", defaultWidth: 170 },
  { key: "updated", label: "Last updated", defaultWidth: 140, defaultVisible: false },
];

function contactLabel(contact: Contact | undefined): string {
  return contact ? personName(contact) || "Unnamed contact" : "Contact unavailable";
}

function isOverdue(lead: Lead, now: number): boolean {
  if (!lead.is_active || !lead.next_action_at || lead.status === "WON" || lead.status === "LOST") return false;
  const due = new Date(lead.next_action_at).getTime();
  return Number.isFinite(due) && due < now;
}

/**
 * The sales pipeline on the shared EnterpriseDataGrid. Rows are the existing leads, grouped by stage in the stage column.
 * Stage moves follow the same allowed transitions as the board. The board view stays available for drag-and-drop stage moves.
 * Expected value and closing date are not part of the lead contract, so they are not shown.
 */
export default function PipelineWorkspacePage() {
  const [view, setView] = useState<View>("list");
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [search, setSearch] = useState("");
  const [visibility, setVisibility] = useState<Visibility>("active");
  const [stageFilter, setStageFilter] = useState<"" | LeadStatus>("");
  const [notice, setNotice] = useState("");
  const [now] = useState(() => Date.now());

  const [selected, setSelected] = useState<Lead | null>(null);
  const [stageSaving, setStageSaving] = useState(false);
  const [stageMessage, setStageMessage] = useState("");
  const [followUpsOpen, setFollowUpsOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);

  const loadAll = useCallback(async () => {
    const [allLeads, allContacts] = await Promise.all([
      fetchAllPages((page) => leadsApi.list({ page, page_size: SALES_PAGE_SIZE })),
      fetchAllPages((page) => contactsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    ]);
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
      setLoadError(messageFrom(error, "The pipeline could not be loaded. Check your connection and try again."));
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
        setLoadError(messageFrom(error, "The pipeline could not be loaded. Check your connection and try again."));
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [applyLoaded, loadAll]);

  const contactById = useMemo(() => new Map(contacts.map((contact) => [contact.id, contact])), [contacts]);
  const ownerName = useMemo(() => new Map(members.map((member) => [member.user_id, member.display_name])), [members]);

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return leads.filter((lead) => {
      if (visibility === "active" && !lead.is_active) return false;
      if (visibility === "inactive" && lead.is_active) return false;
      if (stageFilter && lead.status !== stageFilter) return false;
      if (!needle) return true;
      const contact = contactById.get(lead.contact_id);
      return [contactLabel(contact), contact?.email ?? "", contact?.phone ?? "", lead.next_action ?? ""].some((value) =>
        value.toLowerCase().includes(needle),
      );
    });
  }, [leads, search, visibility, stageFilter, contactById]);

  const sortValue = useCallback(
    (lead: Lead, key: string): string | number | null => {
      const contact = contactById.get(lead.contact_id);
      switch (key) {
        case "status":
          return LEAD_STATUSES.indexOf(lead.status);
        case "email":
          return contact?.email ?? null;
        case "phone":
          return contact?.phone ?? null;
        case "interest":
          return lead.interest ?? null;
        case "next":
          return lead.next_action?.trim() || null;
        case "due":
          return lead.next_action_at ? new Date(lead.next_action_at).getTime() : null;
        case "owner":
          return lead.owner_user_id ? (ownerName.get(lead.owner_user_id) ?? null) : null;
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
        case "status":
          return <Badge tone={stageTone(lead.status)}>{formatStageLabel(lead.status)}</Badge>;
        case "email":
          return contact?.email ?? "—";
        case "phone":
          return contact?.phone ?? "—";
        case "interest":
          return lead.interest ? formatStageLabel(lead.interest) : "Not set";
        case "next":
          return lead.next_action?.trim() ? lead.next_action : <span className="df-sales-muted">No action planned</span>;
        case "due":
          return lead.next_action_at ? (
            <span className={isOverdue(lead, now) ? "df-sales-overdue" : undefined}>{formatDateTime(lead.next_action_at)}</span>
          ) : (
            <span className="df-sales-muted">Not scheduled</span>
          );
        case "owner":
          return lead.owner_user_id ? (ownerName.get(lead.owner_user_id) ?? "—") : "Unassigned";
        case "updated":
          return formatShortDate(lead.updated_at);
        default:
          return <strong className="df-sales-primary">{contactLabel(contact)}</strong>;
      }
    },
    [contactById, ownerName, now],
  );

  async function changeStage(lead: Lead, next: LeadStatus) {
    if (next === lead.status || !ALLOWED_STATUS_TRANSITIONS[lead.status].includes(next)) return;
    setStageSaving(true);
    setStageMessage("");
    try {
      const outcome = outcomeForStatusChange(lead.status, next);
      const updated = await leadsApi.update(lead.id, outcome === undefined ? { status: next } : { status: next, outcome });
      setLeads((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setSelected(updated);
      setNotice(`Lead moved to ${formatStageLabel(next)}.`);
    } catch (error) {
      setStageMessage(messageFrom(error, "The stage could not be changed. Try again."));
    } finally {
      setStageSaving(false);
    }
  }

  const selectedContact = selected ? contactById.get(selected.contact_id) : undefined;
  const selectedName = contactLabel(selectedContact);

  const viewToggle = (
    <div className="df-sales-view-toggle" role="group" aria-label="Pipeline view">
      <Button variant={view === "list" ? "primary" : "secondary"} size="sm" aria-pressed={view === "list"} onClick={() => setView("list")}>
        List
      </Button>
      <Button variant={view === "board" ? "primary" : "secondary"} size="sm" aria-pressed={view === "board"} onClick={() => setView("board")}>
        Board
      </Button>
    </div>
  );

  if (view === "board") {
    return (
      <div className="df-sales-page">
        <h1 className="df-visually-hidden">Pipeline</h1>
        <div className="df-sales-view-bar">{viewToggle}</div>
        <PipelinePage />
      </div>
    );
  }

  return (
    <div className="df-sales-page">
      <h1 className="df-visually-hidden">Pipeline</h1>

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}

      <EnterpriseDataGrid<Lead>
        gridId="pipeline"
        ariaLabel="Pipeline"
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
        searchLabel="Search pipeline"
        searchPlaceholder="Search name, email, phone or next action"
        emptyTitle="No leads in the pipeline"
        emptyMessage="Leads appear here as they are created. Create a lead from the Leads page."
        noMatchTitle="No leads match this search or filter"
        noMatchMessage="Try another search, or change the visibility and stage filters."
        onOpenRow={(lead) => {
          setSelected(lead);
          setStageMessage("");
          setTimelineOpen(false);
          setFollowUpsOpen(false);
        }}
        totalCount={leads.length}
        rangeLabel={search || stageFilter || visibility !== "active" ? "Filtered" : "Active leads shown"}
        toolbarFilters={
          <>
            {viewToggle}
            <select
              className="df-input df-sales-status-select"
              aria-label="Lead visibility"
              value={visibility}
              onChange={(event) => setVisibility(event.target.value as Visibility)}
            >
              <option value="active">Active leads</option>
              <option value="inactive">Inactive leads</option>
              <option value="all">All leads</option>
            </select>
            <select
              className="df-input df-sales-status-select"
              aria-label="Filter by stage"
              value={stageFilter}
              onChange={(event) => setStageFilter(event.target.value as "" | LeadStatus)}
            >
              <option value="">All stages</option>
              {LEAD_STATUSES.map((stage) => (
                <option key={stage} value={stage}>
                  {formatStageLabel(stage)}
                </option>
              ))}
            </select>
          </>
        }
      />

      <RecordDetailDialog
        open={selected !== null}
        onClose={() => setSelected(null)}
        eyebrow="Pipeline"
        title={selectedName}
        closeLabel="Close pipeline lead"
        main={
          selected ? (
            <div className="df-sales-form">
              <div className="df-sales-form-grid">
                <TextField label="Email address" value={selectedContact?.email ?? ""} readOnly />
                <TextField label="Phone" value={selectedContact?.phone ?? ""} readOnly />
                <TextField label="Next action" value={selected.next_action ?? ""} readOnly helper="Edit next actions on the Leads page." />
                <TextField label="Follow-up due" value={formatDateTime(selected.next_action_at)} readOnly />
                <SelectField
                  label="Stage"
                  value={selected.status}
                  disabled={stageSaving || ALLOWED_STATUS_TRANSITIONS[selected.status].length === 0}
                  options={[selected.status, ...ALLOWED_STATUS_TRANSITIONS[selected.status]].map((stage) => ({
                    value: stage,
                    label: formatStageLabel(stage),
                  }))}
                  onChange={(event) => void changeStage(selected, event.target.value as LeadStatus)}
                />
              </div>
              {stageMessage ? (
                <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                  {stageMessage}
                </p>
              ) : null}
            </div>
          ) : null
        }
        aside={
          selected ? (
            <>
              <dl className="df-sales-properties">
                <RecordProperty label="Stage">
                  <Badge tone={stageTone(selected.status)}>{formatStageLabel(selected.status)}</Badge>
                </RecordProperty>
                <RecordProperty label="Active">{selected.is_active ? "Yes" : "No"}</RecordProperty>
                <RecordProperty label="Owner">{selected.owner_user_id ? (ownerName.get(selected.owner_user_id) ?? "Unnamed owner") : "Unassigned"}</RecordProperty>
                <RecordProperty label="Last updated">{formatShortDate(selected.updated_at)}</RecordProperty>
              </dl>
              <div className="df-sales-aside-actions">
                <Button variant="secondary" size="sm" onClick={() => setFollowUpsOpen(true)} disabled={!selected.is_active}>
                  Manage follow-ups
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setTimelineOpen(true)}>
                  View timeline
                </Button>
              </div>
            </>
          ) : null
        }
      />

      {selected && followUpsOpen ? (
        <LeadFollowUpsDialog
          open={followUpsOpen}
          leadId={selected.id}
          leadName={selectedName}
          onClose={() => setFollowUpsOpen(false)}
          onChanged={() => void reload()}
        />
      ) : null}

      {selected && timelineOpen ? (
        <LeadTimeline leadId={selected.id} contactName={selectedName} onClose={() => setTimelineOpen(false)} />
      ) : null}
    </div>
  );
}

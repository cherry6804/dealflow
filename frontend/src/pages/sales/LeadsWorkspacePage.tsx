import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { EnterpriseDataGrid } from "../../components/grid/EnterpriseDataGrid";
import type { GridColumnDef } from "../../components/grid/gridLayout";
import LeadTimeline from "../../components/LeadTimeline";
import { RecordDetailDialog, RecordProperty } from "../../components/record/RecordDetailDialog";
import { Badge, Button, Dialog, SelectField, TextField } from "../../components/ui";
import { toIsoDateTime, toLocalDateTimeInput } from "../../lib/dateTimeInput";
import { contactsApi, type Contact } from "../../services/contactApi";
import { leadsApi, type Lead, type LeadInterest, type LeadStatus } from "../../services/leadApi";
import { teamApi, type TeamMember } from "../../services/teamApi";
import LeadFollowUpsDialog from "./leads/LeadFollowUpsDialog";
import {
  LEAD_INTERESTS,
  LEAD_STATUSES,
  availableStatuses,
  formatStageLabel,
  needsNextActionPrompt,
  outcomeForStatusChange,
  stageTone,
} from "./leads/lead-workflow";
import { fetchAllPages, formatDateTime, formatShortDate, messageFrom, personName, SALES_PAGE_SIZE } from "./sales-shared";
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

interface PendingStatus {
  lead: Lead;
  next: LeadStatus;
}

function interestLabel(value: LeadInterest | null): string {
  if (!value) return "Not set";
  return formatStageLabel(value);
}

function contactLabel(contact: Contact | undefined): string {
  return contact ? personName(contact) || "Unnamed contact" : "Contact unavailable";
}

/**
 * Leads on the shared EnterpriseDataGrid. Stage moves, interest, next action, follow-ups, timeline and activation keep their
 * existing rules and endpoints. Source is not part of the lead contract, so it is not shown.
 */
export default function LeadsWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState<"" | LeadStatus>("");
  const [interestFilter, setInterestFilter] = useState<"" | LeadInterest>("");
  const [notice, setNotice] = useState("");

  const [selected, setSelected] = useState<Lead | null>(null);
  const [detailSaving, setDetailSaving] = useState(false);
  const [detailMessage, setDetailMessage] = useState("");
  const [pendingStatus, setPendingStatus] = useState<PendingStatus | null>(null);
  const [promptAction, setPromptAction] = useState("");
  const [promptDate, setPromptDate] = useState("");
  const [promptError, setPromptError] = useState("");
  const [nextAction, setNextAction] = useState("");
  const [nextActionDate, setNextActionDate] = useState("");
  const [nextActionError, setNextActionError] = useState("");
  const [followUpsOpen, setFollowUpsOpen] = useState(false);
  const [timelineOpen, setTimelineOpen] = useState(false);

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

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return leads.filter((lead) => {
      if (stageFilter && lead.status !== stageFilter) return false;
      if (interestFilter && lead.interest !== interestFilter) return false;
      if (!needle) return true;
      const contact = contactById.get(lead.contact_id);
      return [contactLabel(contact), contact?.email ?? "", contact?.phone ?? "", lead.next_action ?? "", formatStageLabel(lead.status)].some((value) =>
        value.toLowerCase().includes(needle),
      );
    });
  }, [leads, search, stageFilter, interestFilter, contactById]);

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
          return interestLabel(lead.interest);
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
          return <strong className="df-sales-primary">{contactLabel(contact)}</strong>;
      }
    },
    [contactById, ownerName],
  );

  function openDetail(lead: Lead) {
    setSelected(lead);
    setDetailMessage("");
    setPendingStatus(null);
    setPromptError("");
    setNextAction(lead.next_action ?? "");
    setNextActionDate(toLocalDateTimeInput(lead.next_action_at));
    setNextActionError("");
    setTimelineOpen(false);
    setFollowUpsOpen(false);
  }

  async function applyLeadUpdate(lead: Lead, payload: Parameters<typeof leadsApi.update>[1], message: string) {
    setDetailSaving(true);
    setDetailMessage("");
    try {
      const updated = await leadsApi.update(lead.id, payload);
      setLeads((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setSelected(updated);
      setNextAction(updated.next_action ?? "");
      setNextActionDate(toLocalDateTimeInput(updated.next_action_at));
      setNotice(message);
      return updated;
    } catch (error) {
      setDetailMessage(messageFrom(error, "The lead could not be updated. Try again."));
      return null;
    } finally {
      setDetailSaving(false);
    }
  }

  function chooseStage(lead: Lead, next: LeadStatus) {
    if (next === lead.status) return;
    if (needsNextActionPrompt(lead, next)) {
      // Ask for the next action before moving the lead into a key stage, as the legacy page does.
      setPendingStatus({ lead, next });
      setPromptAction("");
      setPromptDate("");
      setPromptError("");
      return;
    }
    const outcome = outcomeForStatusChange(lead.status, next);
    void applyLeadUpdate(lead, outcome === undefined ? { status: next } : { status: next, outcome }, `Stage updated to ${formatStageLabel(next)}.`);
  }

  async function submitStagePrompt(event: FormEvent) {
    event.preventDefault();
    if (!pendingStatus) return;
    const action = promptAction.trim();
    if (!action) {
      setPromptError("Enter the next action before continuing.");
      return;
    }
    if (promptDate && !toIsoDateTime(promptDate)) {
      setPromptError("Enter a valid next-action date and time.");
      return;
    }
    const outcome = outcomeForStatusChange(pendingStatus.lead.status, pendingStatus.next);
    setDetailSaving(true);
    setPromptError("");
    try {
      const updated = await leadsApi.update(pendingStatus.lead.id, {
        status: pendingStatus.next,
        next_action: action,
        next_action_at: toIsoDateTime(promptDate),
        ...(outcome === undefined ? {} : { outcome }),
      });
      setLeads((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setSelected(updated);
      setNextAction(updated.next_action ?? "");
      setNextActionDate(toLocalDateTimeInput(updated.next_action_at));
      setPendingStatus(null);
      setNotice(`Stage updated to ${formatStageLabel(pendingStatus.next)} and next action saved.`);
    } catch (error) {
      setPromptError(messageFrom(error, "The lead could not be updated. Try again."));
    } finally {
      setDetailSaving(false);
    }
  }

  async function saveNextAction(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const action = nextAction.trim();
    if (nextActionDate && !action) {
      setNextActionError("Enter a next action when scheduling a date.");
      return;
    }
    setNextActionError("");
    await applyLeadUpdate(
      selected,
      { next_action: action || null, next_action_at: toIsoDateTime(nextActionDate) },
      "Next action and follow-up updated successfully.",
    );
  }

  async function toggleActive() {
    if (!selected) return;
    await applyLeadUpdate(selected, { is_active: !selected.is_active }, selected.is_active ? "Lead marked inactive." : "Lead reactivated successfully.");
  }

  async function changeInterest(value: string) {
    if (!selected) return;
    const interest = value ? (value as LeadInterest) : null;
    if (interest === selected.interest) return;
    await applyLeadUpdate(selected, { interest }, "Lead interest updated successfully.");
  }

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

  const selectedContact = selected ? contactById.get(selected.contact_id) : undefined;
  const selectedName = contactLabel(selectedContact);
  const nextActionDirty = selected
    ? nextAction.trim() !== (selected.next_action ?? "").trim() || nextActionDate !== toLocalDateTimeInput(selected.next_action_at)
    : false;

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
        rows={filtered}
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
        noMatchMessage="Try another search, or clear the stage and interest filters."
        createLabel="New lead"
        onCreate={() => void openCreate()}
        onOpenRow={openDetail}
        totalCount={leads.length}
        rangeLabel={search || stageFilter || interestFilter ? "Filtered" : "All leads shown"}
        toolbarFilters={
          <>
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
            <select
              className="df-input df-sales-status-select"
              aria-label="Filter by interest"
              value={interestFilter}
              onChange={(event) => setInterestFilter(event.target.value as "" | LeadInterest)}
            >
              <option value="">All interest levels</option>
              {LEAD_INTERESTS.map((level) => (
                <option key={level} value={level}>
                  {formatStageLabel(level)}
                </option>
              ))}
            </select>
          </>
        }
      />

      <RecordDetailDialog
        open={selected !== null}
        onClose={() => setSelected(null)}
        eyebrow="Lead"
        title={selectedName}
        closeLabel="Close lead"
        main={
          selected ? (
            <div className="df-sales-form">
              <div className="df-sales-form-grid">
                <TextField label="Name" value={selectedName} readOnly helper="Edit the name on the contact record." />
                <TextField label="Email address" value={selectedContact?.email ?? ""} readOnly />
                <TextField label="Phone" value={selectedContact?.phone ?? ""} readOnly />
                <SelectField
                  label="Stage"
                  value={selected.status}
                  disabled={detailSaving || !selected.is_active}
                  options={availableStatuses(selected.status).map((stage) => ({ value: stage, label: formatStageLabel(stage) }))}
                  onChange={(event) => chooseStage(selected, event.target.value as LeadStatus)}
                />
                <SelectField
                  label="Interest"
                  value={selected.interest ?? ""}
                  disabled={detailSaving || !selected.is_active}
                  options={[
                    { value: "", label: "Not set" },
                    ...LEAD_INTERESTS.map((level) => ({ value: level, label: formatStageLabel(level) })),
                  ]}
                  onChange={(event) => void changeInterest(event.target.value)}
                />
              </div>

              {pendingStatus && pendingStatus.lead.id === selected.id ? (
                <form className="df-sales-section" onSubmit={submitStagePrompt} noValidate aria-label="Next action required">
                  <h3 className="df-sales-section-title">Add a next action to move to {formatStageLabel(pendingStatus.next)}</h3>
                  <div className="df-sales-form-grid">
                    <TextField label="Next action" required value={promptAction} onChange={(event) => setPromptAction(event.target.value)} />
                    <TextField label="Next action date" type="datetime-local" value={promptDate} onChange={(event) => setPromptDate(event.target.value)} />
                  </div>
                  {promptError ? (
                    <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                      {promptError}
                    </p>
                  ) : null}
                  <div className="df-sales-form-actions">
                    <Button variant="secondary" onClick={() => setPendingStatus(null)} disabled={detailSaving}>
                      Cancel
                    </Button>
                    <Button type="submit" variant="primary" loading={detailSaving}>
                      Save and move stage
                    </Button>
                  </div>
                </form>
              ) : null}

              <form className="df-sales-section" onSubmit={saveNextAction} noValidate>
                <h3 className="df-sales-section-title">Next follow-up</h3>
                <div className="df-sales-form-grid">
                  <TextField
                    label="Next action"
                    value={nextAction}
                    disabled={!selected.is_active}
                    error={nextActionError || undefined}
                    onChange={(event) => setNextAction(event.target.value)}
                  />
                  <TextField
                    label="Next action date"
                    type="datetime-local"
                    value={nextActionDate}
                    disabled={!selected.is_active}
                    onChange={(event) => setNextActionDate(event.target.value)}
                  />
                </div>
                <div className="df-sales-form-actions">
                  {detailMessage ? (
                    <p className="df-sales-form-message df-sales-form-message--error" role="alert">
                      {detailMessage}
                    </p>
                  ) : null}
                  <Button type="submit" variant="primary" disabled={!selected.is_active || !nextActionDirty} loading={detailSaving}>
                    Save next action
                  </Button>
                </div>
              </form>
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
                <RecordProperty label="Created">{formatShortDate(selected.created_at)}</RecordProperty>
                <RecordProperty label="Last updated">{formatShortDate(selected.updated_at)}</RecordProperty>
              </dl>
              <div className="df-sales-aside-actions">
                <Button variant="secondary" size="sm" onClick={() => setFollowUpsOpen(true)} disabled={!selected.is_active}>
                  Manage follow-ups
                </Button>
                <Button variant="secondary" size="sm" onClick={() => setTimelineOpen(true)}>
                  View timeline
                </Button>
                <Button variant="secondary" size="sm" onClick={() => void toggleActive()} disabled={detailSaving}>
                  {selected.is_active ? "Mark lead inactive" : "Reactivate lead"}
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
                    label: [contactLabel(contact), contact.email, contact.phone].filter(Boolean).join(" · "),
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

import { useCallback, useEffect, useMemo, useState, type DragEvent } from "react";

import { GridFilterButton, GridFilterChips } from "../../components/grid/GridFilterControls";
import { useGridFilters } from "../../components/grid/useGridFilters";
import { applyGridFilters, type GridFilterField, type GridFilterOption } from "../../components/grid/gridFilters";
import { Badge, Button } from "../../components/ui";
import { ErrorState, LoadingState } from "../../components/shell/RouteStates";
import { contactsApi, type Contact } from "../../services/contactApi";
import { leadsApi, type Lead, type LeadStatus } from "../../services/leadApi";
import { teamApi, type TeamMember } from "../../services/teamApi";
import LeadDetailDialog from "./leads/LeadDetailDialog";
import { buildLeadFilterFields, leadFilterValue } from "./leads/lead-filters";
import { ALLOWED_STATUS_TRANSITIONS, formatStageLabel, needsNextActionPrompt, outcomeForStatusChange } from "./leads/lead-workflow";
import { PIPELINE_STAGES } from "./pipeline/pipeline-stages";
import { contactDisplayName, fetchAllPages, formatDateTime, messageFrom, SALES_PAGE_SIZE } from "./sales-shared";
import "./sales.css";
import "./pipeline/pipeline-board.css";

const PIPELINE_FILTER_KEY = "pipeline";

/**
 * Pipeline as a Kanban board only. Each stage is a column and each lead is a card in its stage. Cards open the lead record.
 * Stage moves use the existing transition table; a move that needs a next action opens the record at that step. Drag and drop
 * only offers moves the transition table allows, and the stage select on each card gives the same choice without a pointer.
 */
export default function PipelineWorkspacePage() {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const [moveError, setMoveError] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingStage, setPendingStage] = useState<LeadStatus | null>(null);
  const [movingId, setMovingId] = useState<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<LeadStatus | null>(null);
  const [now] = useState(() => Date.now());

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
  const ownerOptions = useMemo<GridFilterOption[]>(
    () => members.map((member) => ({ value: member.user_id, label: member.display_name })),
    [members],
  );

  // Stage is the column itself, so the board's filters cover everything except stage, plus lead activity.
  const filterFields = useMemo<GridFilterField[]>(() => {
    const base = buildLeadFilterFields(ownerOptions).filter((field) => field.key !== "stage");
    return [
      ...base,
      {
        key: "active",
        label: "Lead activity",
        type: "select",
        options: [
          { value: "active", label: "Active" },
          { value: "inactive", label: "Inactive" },
        ],
      },
    ];
  }, [ownerOptions]);

  const readFilterValue = useCallback(
    (lead: Lead, key: string) => (key === "active" ? (lead.is_active ? "active" : "inactive") : leadFilterValue(lead, key, (id) => contactById.get(id))),
    [contactById],
  );

  const { conditions, apply: applyFilters } = useGridFilters(PIPELINE_FILTER_KEY, filterFields);

  const visibleLeads = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const searched = needle
      ? leads.filter((lead) => {
          const contact = contactById.get(lead.contact_id);
          return [contactDisplayName(contact), contact?.email ?? "", contact?.phone ?? "", lead.next_action ?? ""].some((value) =>
            value.toLowerCase().includes(needle),
          );
        })
      : leads;
    return applyGridFilters(searched, conditions, filterFields, readFilterValue);
  }, [leads, search, contactById, conditions, filterFields, readFilterValue]);

  const byStage = useMemo(() => {
    const grouped = new Map<LeadStatus, Lead[]>(PIPELINE_STAGES.map((stage) => [stage.status, []]));
    for (const lead of visibleLeads) grouped.get(lead.status)?.push(lead);
    return grouped;
  }, [visibleLeads]);

  function openRecord(lead: Lead, stage?: LeadStatus) {
    setSelectedId(lead.id);
    setPendingStage(stage ?? null);
  }

  /** Moves a lead to a stage. Disallowed moves are refused; moves that need a next action open the record at that step. */
  async function moveLead(lead: Lead, next: LeadStatus) {
    if (next === lead.status) return;
    if (!ALLOWED_STATUS_TRANSITIONS[lead.status].includes(next)) {
      setMoveError(`A lead cannot move directly from ${formatStageLabel(lead.status)} to ${formatStageLabel(next)}. Choose one of its allowed next stages.`);
      return;
    }
    if (needsNextActionPrompt(lead, next)) {
      openRecord(lead, next);
      return;
    }
    setMovingId(lead.id);
    setMoveError("");
    setNotice("");
    try {
      const outcome = outcomeForStatusChange(lead.status, next);
      const updated = await leadsApi.update(lead.id, outcome === undefined ? { status: next } : { status: next, outcome });
      setLeads((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setNotice(`${contactDisplayName(contactById.get(lead.contact_id))} moved to ${formatStageLabel(next)}.`);
    } catch (error) {
      setMoveError(messageFrom(error, "The lead could not be moved. Try again."));
    } finally {
      setMovingId(null);
    }
  }

  function onDrop(event: DragEvent<HTMLElement>, target: LeadStatus) {
    event.preventDefault();
    setDropTarget(null);
    const id = event.dataTransfer.getData("text/plain") || draggingId;
    setDraggingId(null);
    const lead = id ? leads.find((item) => item.id === id) : undefined;
    if (lead) void moveLead(lead, target);
  }

  function canDropOn(stage: LeadStatus): boolean {
    const lead = draggingId ? leads.find((item) => item.id === draggingId) : undefined;
    return Boolean(lead && (lead.status === stage || ALLOWED_STATUS_TRANSITIONS[lead.status].includes(stage)));
  }

  const selected = selectedId ? (leads.find((lead) => lead.id === selectedId) ?? null) : null;
  const totalShown = visibleLeads.length;

  return (
    <div className="df-sales-page df-pipeline">
      <h1 className="df-visually-hidden">Pipeline</h1>

      <div className="df-grid-toolbar df-pipeline-toolbar">
        <label className="df-grid-search">
          <span className="df-visually-hidden">Search pipeline</span>
          <input
            type="search"
            className="df-input"
            value={search}
            placeholder="Search name, email, phone or next action"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <div className="df-grid-toolbar-actions">
          <GridFilterButton fields={filterFields} conditions={conditions} onApply={applyFilters} />
        </div>
      </div>

      <GridFilterChips fields={filterFields} conditions={conditions} onApply={applyFilters} />

      {notice ? (
        <p className="df-sales-notice" role="status">
          {notice}
        </p>
      ) : null}
      {moveError ? (
        <p className="df-sales-form-message df-sales-form-message--error" role="alert">
          {moveError}
        </p>
      ) : null}

      {status === "loading" ? <LoadingState title="Loading pipeline" message="Fetching the latest leads." /> : null}
      {status === "error" ? (
        <ErrorState title="The pipeline could not be loaded" message={loadError} retryLabel="Try again" onRetry={() => void reload()} />
      ) : null}

      {status === "ready" ? (
        <section className="df-pipeline-board-frame" aria-label="Pipeline stages">
          <div className="df-pipeline-board" role="list">
            {PIPELINE_STAGES.map((stage) => {
              const stageLeads = byStage.get(stage.status) ?? [];
              const droppable = draggingId !== null && canDropOn(stage.status);
              return (
                <section
                  key={stage.status}
                  role="listitem"
                  className={`df-pipeline-column${dropTarget === stage.status && droppable ? " df-pipeline-column--drop" : ""}`}
                  aria-label={`${stage.label}: ${stageLeads.length} ${stageLeads.length === 1 ? "lead" : "leads"}`}
                  onDragOver={(event) => {
                    if (!droppable) return;
                    event.preventDefault();
                    event.dataTransfer.dropEffect = "move";
                    setDropTarget(stage.status);
                  }}
                  onDragLeave={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropTarget(null);
                  }}
                  onDrop={(event) => onDrop(event, stage.status)}
                >
                  <header className="df-pipeline-column-header">
                    <div className="df-pipeline-column-title">
                      <h2>{stage.label}</h2>
                      <Badge tone="neutral">{stageLeads.length}</Badge>
                    </div>
                    <p className="df-sales-muted">{stage.description}</p>
                  </header>

                  <div className="df-pipeline-cards">
                    {stageLeads.length === 0 ? (
                      <div className="df-pipeline-empty">
                        {draggingId && droppable ? `Drop here to move to ${stage.label}` : "No leads in this stage"}
                      </div>
                    ) : (
                      stageLeads.map((lead) => {
                        const contact = contactById.get(lead.contact_id);
                        const name = contactDisplayName(contact);
                        const overdue =
                          lead.is_active && lead.next_action_at && lead.status !== "WON" && lead.status !== "LOST" && new Date(lead.next_action_at).getTime() < now;
                        const allowed = [lead.status, ...ALLOWED_STATUS_TRANSITIONS[lead.status]];
                        const busy = movingId === lead.id;
                        return (
                          <article
                            key={lead.id}
                            className={[
                              "df-pipeline-card",
                              lead.is_active ? "" : "df-pipeline-card--inactive",
                              draggingId === lead.id ? "df-pipeline-card--dragging" : "",
                            ]
                              .filter(Boolean)
                              .join(" ")}
                            draggable={!busy && ALLOWED_STATUS_TRANSITIONS[lead.status].length > 0}
                            onDragStart={(event) => {
                              setDraggingId(lead.id);
                              event.dataTransfer.effectAllowed = "move";
                              event.dataTransfer.setData("text/plain", lead.id);
                            }}
                            onDragEnd={() => {
                              setDraggingId(null);
                              setDropTarget(null);
                            }}
                          >
                            <div className="df-pipeline-card-top">
                              <Badge tone={lead.is_active ? "active" : "neutral"}>{lead.is_active ? (lead.interest ? formatStageLabel(lead.interest) : "Interest not set") : "Inactive"}</Badge>
                            </div>
                            <h3 className="df-pipeline-card-title">
                              <button type="button" className="df-pipeline-card-open" onClick={() => openRecord(lead)}>
                                {name}
                                <span className="df-visually-hidden"> — open lead record</span>
                              </button>
                            </h3>
                            {contact?.email ? <p className="df-pipeline-card-line">{contact.email}</p> : null}
                            {contact?.phone ? <p className="df-pipeline-card-line">{contact.phone}</p> : null}
                            <dl className="df-pipeline-card-facts">
                              <div>
                                <dt>Next action</dt>
                                <dd>{lead.next_action?.trim() || "No action planned"}</dd>
                              </div>
                              <div>
                                <dt>Follow-up</dt>
                                <dd className={overdue ? "df-sales-overdue" : undefined}>
                                  {lead.next_action_at ? formatDateTime(lead.next_action_at) : "Not scheduled"}
                                </dd>
                              </div>
                              <div>
                                <dt>Owner</dt>
                                <dd>{lead.owner_user_id ? (ownerName.get(lead.owner_user_id) ?? "Assigned") : "Unassigned"}</dd>
                              </div>
                            </dl>
                            <label className="df-pipeline-card-stage">
                              <span className="df-visually-hidden">Move {name} to stage</span>
                              <select
                                className="df-input"
                                value={lead.status}
                                disabled={busy || allowed.length <= 1}
                                onChange={(event) => void moveLead(lead, event.target.value as LeadStatus)}
                              >
                                {allowed.map((option) => (
                                  <option key={option} value={option}>
                                    {formatStageLabel(option)}
                                  </option>
                                ))}
                              </select>
                            </label>
                          </article>
                        );
                      })
                    )}
                  </div>
                </section>
              );
            })}
          </div>
          <footer className="df-pipeline-footer">
            <span>
              <strong>{totalShown}</strong> {totalShown === 1 ? "lead" : "leads"} across {PIPELINE_STAGES.length} stages
              {conditions.length > 0 || search.trim() ? ` · filtered from ${leads.length}` : ""}
            </span>
            <Button variant="tertiary" size="sm" onClick={() => void reload()}>
              Refresh
            </Button>
          </footer>
        </section>
      ) : null}

      {selected ? (
        <LeadDetailDialog
          key={`${selected.id}-${pendingStage ?? ""}`}
          lead={selected}
          contact={contactById.get(selected.contact_id)}
          ownerName={selected.owner_user_id ? (ownerName.get(selected.owner_user_id) ?? null) : null}
          initialStage={pendingStage ?? undefined}
          onClose={() => {
            setSelectedId(null);
            setPendingStage(null);
          }}
          onLeadChanged={(updated) => setLeads((current) => current.map((item) => (item.id === updated.id ? updated : item)))}
          onNotice={setNotice}
          onFollowUpsChanged={() => void reload()}
        />
      ) : null}
    </div>
  );
}

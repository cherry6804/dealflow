import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";

import { ApiError } from "../lib/api";
import { contactsApi, type Contact } from "../services/contactApi";
import {
  leadsApi,
  type Lead,
  type LeadListParams,
  type LeadStatus,
} from "../services/leadApi";

import "./PipelinePage.css";

const PAGE_SIZE = 100;

const PIPELINE_STAGES: {
  status: LeadStatus;
  label: string;
  description: string;
}[] = [
  { status: "NEW", label: "New", description: "Recently captured" },
  {
    status: "CONTACTED",
    label: "Contacted",
    description: "First contact made",
  },
  {
    status: "QUALIFIED",
    label: "Qualified",
    description: "Potential confirmed",
  },
  {
    status: "MATCHING",
    label: "Matching",
    description: "Finding suitable options",
  },
  { status: "VISIT", label: "Visit", description: "Property visits" },
  {
    status: "NEGOTIATION",
    label: "Negotiation",
    description: "Discussing terms",
  },
  { status: "WON", label: "Won", description: "Successful opportunities" },
  {
    status: "LOST",
    label: "Lost",
    description: "Unsuccessful opportunities",
  },
  {
    status: "ON_HOLD",
    label: "On hold",
    description: "Temporarily paused",
  },
];

const ALLOWED_STATUS_TRANSITIONS: Record<LeadStatus, LeadStatus[]> = {
  NEW: ["CONTACTED", "QUALIFIED", "ON_HOLD"],
  CONTACTED: ["QUALIFIED", "MATCHING", "ON_HOLD"],
  QUALIFIED: ["MATCHING", "VISIT", "ON_HOLD"],
  MATCHING: ["VISIT", "QUALIFIED", "ON_HOLD"],
  VISIT: ["MATCHING", "NEGOTIATION", "QUALIFIED", "ON_HOLD"],
  NEGOTIATION: ["WON", "LOST", "VISIT", "ON_HOLD"],
  WON: [],
  LOST: [],
  ON_HOLD: [
    "CONTACTED",
    "QUALIFIED",
    "MATCHING",
    "VISIT",
    "NEGOTIATION",
  ],
};

type ActivityFilter = "all" | "active" | "inactive";

function formatLabel(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDate(value: string | null): string {
  if (!value) return "Not scheduled";

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "Not scheduled";

  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function getContactName(contact: Contact | undefined): string {
  if (!contact) return "Contact unavailable";

  return (
    [contact.first_name, contact.last_name]
      .filter(Boolean)
      .join(" ")
      .trim() || "Unnamed contact"
  );
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;

  return "Something went wrong while loading the pipeline.";
}

async function loadAllLeads(
  params: Omit<LeadListParams, "page" | "page_size">,
): Promise<Lead[]> {
  const firstPage = await leadsApi.list({
    ...params,
    page: 1,
    page_size: PAGE_SIZE,
  });

  const leads = [...firstPage.items];

  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const result = await leadsApi.list({
      ...params,
      page,
      page_size: PAGE_SIZE,
    });

    leads.push(...result.items);
  }

  if (leads.length !== firstPage.total) {
    throw new Error(
      "The pipeline could not load every matching lead. Please refresh and try again.",
    );
  }

  return leads;
}

async function loadAllContacts(): Promise<Contact[]> {
  const firstPage = await contactsApi.list({
    page: 1,
    page_size: PAGE_SIZE,
  });

  const contacts = [...firstPage.items];

  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const result = await contactsApi.list({
      page,
      page_size: PAGE_SIZE,
    });

    contacts.push(...result.items);
  }

  if (contacts.length !== firstPage.total) {
    throw new Error(
      "The pipeline could not load every contact. Please refresh and try again.",
    );
  }

  return contacts;
}

export default function PipelinePage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [activityFilter, setActivityFilter] =
    useState<ActivityFilter>("active");
  const [loading, setLoading] = useState(true);
  const [updatingLeadId, setUpdatingLeadId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [currentTime, setCurrentTime] = useState<number | null>(null);

  const refresh = useCallback(() => {
    setRefreshKey((current) => current + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadPipeline() {
      setLoading(true);
      setError(null);
      setNotice(null);

      try {
        const isActive =
          activityFilter === "all"
            ? undefined
            : activityFilter === "active";

        const [loadedLeads, loadedContacts] = await Promise.all([
          loadAllLeads({
            search: search || undefined,
            is_active: isActive,
          }),
          loadAllContacts(),
        ]);

        if (cancelled) return;

        setLeads(loadedLeads);
        setContacts(loadedContacts);
        setCurrentTime(Date.now());
      } catch (loadError) {
        if (cancelled) return;

        setError(getErrorMessage(loadError));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadPipeline();

    return () => {
      cancelled = true;
    };
  }, [activityFilter, search, refreshKey]);

  const contactsById = useMemo(
    () => new Map(contacts.map((contact) => [contact.id, contact])),
    [contacts],
  );

  const leadsByStatus = useMemo(() => {
    const grouped = new Map<LeadStatus, Lead[]>(
      PIPELINE_STAGES.map((stage) => [stage.status, []]),
    );

    for (const lead of leads) {
      grouped.get(lead.status)?.push(lead);
    }

    return grouped;
  }, [leads]);

  const totalLeads = leads.length;

  const openLeads = leads.filter(
    (lead) =>
      lead.is_active && lead.status !== "WON" && lead.status !== "LOST",
  ).length;

  const wonLeads = leads.filter((lead) => lead.status === "WON").length;

  const overdueFollowUps = leads.filter((lead) => {
    if (!lead.is_active || !lead.next_action_at || currentTime === null) {
      return false;
    }

    const followUpTime = new Date(lead.next_action_at).getTime();

    return (
      Number.isFinite(followUpTime) &&
      followUpTime < currentTime &&
      lead.status !== "WON" &&
      lead.status !== "LOST"
    );
  }).length;

  async function handleStatusChange(
    lead: Lead,
    nextStatus: LeadStatus,
  ): Promise<void> {
    if (
      nextStatus === lead.status ||
      !ALLOWED_STATUS_TRANSITIONS[lead.status].includes(nextStatus)
    ) {
      return;
    }

    setUpdatingLeadId(lead.id);
    setError(null);
    setNotice(null);

    try {
      const outcome =
        nextStatus === "WON"
          ? "SUCCESSFUL"
          : nextStatus === "LOST"
            ? "UNSUCCESSFUL"
            : lead.status === "WON" || lead.status === "LOST"
              ? null
              : lead.outcome;

      await leadsApi.update(lead.id, {
        status: nextStatus,
        outcome,
      });

      setNotice(`Lead moved to ${formatLabel(nextStatus)}.`);
      refresh();
    } catch (updateError) {
      setError(getErrorMessage(updateError));
    } finally {
      setUpdatingLeadId(null);
    }
  }

  function applySearch(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setSearch(searchInput.trim());
  }

  function clearSearch(): void {
    setSearchInput("");
    setSearch("");
  }

  return (
    <section className="pipeline-page">
      <header className="pipeline-header">
        <div>
          <span className="pipeline-eyebrow">LEAD OPERATIONS</span>
          <h1>Operational pipeline</h1>
          <p className="pipeline-subtitle">
            Track every opportunity from first contact to outcome, and see
            what needs attention next.
          </p>
        </div>

        <button
          className="pipeline-secondary-button"
          type="button"
          onClick={refresh}
          disabled={loading || updatingLeadId !== null}
        >
          <span aria-hidden="true">↻</span> Refresh
        </button>
      </header>

      <section className="pipeline-summary" aria-label="Pipeline summary">
        <article className="pipeline-summary-card">
          <span className="pipeline-summary-label">Matching leads</span>
          <strong>{loading ? "—" : totalLeads}</strong>
          <span className="pipeline-summary-hint">
            Based on current filters
          </span>
        </article>

        <article className="pipeline-summary-card">
          <span className="pipeline-summary-label">Open opportunities</span>
          <strong>{loading ? "—" : openLeads}</strong>
          <span className="pipeline-summary-hint">
            Active, excluding won and lost
          </span>
        </article>

        <article className="pipeline-summary-card">
          <span className="pipeline-summary-label">Won</span>
          <strong>{loading ? "—" : wonLeads}</strong>
          <span className="pipeline-summary-hint">
            In the current result set
          </span>
        </article>

        <article className="pipeline-summary-card pipeline-summary-attention">
          <span className="pipeline-summary-label">Overdue follow-ups</span>
          <strong>{loading ? "—" : overdueFollowUps}</strong>
          <span className="pipeline-summary-hint">
            Active leads past their follow-up date
          </span>
        </article>
      </section>

      <section className="pipeline-board-panel">
        <div className="pipeline-toolbar">
          <form className="pipeline-search" onSubmit={applySearch}>
            <label
              className="pipeline-visually-hidden"
              htmlFor="pipeline-search"
            >
              Search leads
            </label>

            <input
              id="pipeline-search"
              type="search"
              placeholder="Search contact, phone, email or next action"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />

            <button type="submit" className="pipeline-primary-button">
              Search
            </button>
          </form>

          <label className="pipeline-filter">
            <span>Lead visibility</span>
            <select
              value={activityFilter}
              onChange={(event) =>
                setActivityFilter(event.target.value as ActivityFilter)
              }
              disabled={loading}
            >
              <option value="active">Active leads</option>
              <option value="inactive">Inactive leads</option>
              <option value="all">All leads</option>
            </select>
          </label>
        </div>

        {error && (
          <div className="pipeline-alert pipeline-alert-error" role="alert">
            <span>{error}</span>
            <button type="button" onClick={refresh}>
              Try again
            </button>
          </div>
        )}

        {notice && !error && (
          <div
            className="pipeline-alert pipeline-alert-success"
            role="status"
          >
            {notice}
            <button
              type="button"
              aria-label="Dismiss notification"
              onClick={() => setNotice(null)}
            >
              ×
            </button>
          </div>
        )}

        {loading ? (
          <div className="pipeline-state" role="status" aria-live="polite">
            <span className="pipeline-spinner" aria-hidden="true" />
            <strong>Loading pipeline</strong>
            <p>Retrieving matching leads and contact details.</p>
          </div>
        ) : error && leads.length === 0 ? (
          <div className="pipeline-state">
            <strong>Pipeline unavailable</strong>
            <p>Resolve the error above and try loading the pipeline again.</p>
          </div>
        ) : leads.length === 0 ? (
          <div className="pipeline-state">
            <span className="pipeline-empty-icon" aria-hidden="true">
              ◇
            </span>
            <strong>No matching leads</strong>
            <p>
              Try a different search or visibility filter. Leads will appear
              here as they are created.
            </p>

            {(search || activityFilter !== "active") && (
              <button
                className="pipeline-secondary-button"
                type="button"
                onClick={() => {
                  clearSearch();
                  setActivityFilter("active");
                }}
              >
                Clear filters
              </button>
            )}
          </div>
        ) : (
          <div className="pipeline-board" aria-label="Lead lifecycle stages">
            {PIPELINE_STAGES.map((stage) => {
              const stageLeads = leadsByStatus.get(stage.status) ?? [];

              return (
                <section
                  className={`pipeline-column pipeline-column-${stage.status.toLowerCase()}`}
                  key={stage.status}
                  aria-label={`${stage.label}: ${stageLeads.length} leads`}
                >
                  <header className="pipeline-column-header">
                    <div className="pipeline-column-title-row">
                      <h2>{stage.label}</h2>
                      <span className="pipeline-column-count">
                        {stageLeads.length}
                      </span>
                    </div>
                    <p>{stage.description}</p>
                  </header>

                  <div className="pipeline-column-cards">
                    {stageLeads.length === 0 ? (
                      <div className="pipeline-column-empty">
                        No leads in this stage
                      </div>
                    ) : (
                      stageLeads.map((lead) => {
                        const contact = contactsById.get(lead.contact_id);

                        const availableStatuses = [
                          lead.status,
                          ...ALLOWED_STATUS_TRANSITIONS[lead.status],
                        ];

                        const followUpTime = lead.next_action_at
                          ? new Date(lead.next_action_at).getTime()
                          : Number.NaN;

                        const isOverdue =
                          currentTime !== null &&
                          lead.is_active &&
                          Number.isFinite(followUpTime) &&
                          followUpTime < currentTime &&
                          lead.status !== "WON" &&
                          lead.status !== "LOST";

                        return (
                          <article
                            className="pipeline-lead-card"
                            key={lead.id}
                          >
                            <div className="pipeline-card-topline">
                              <span
                                className={`pipeline-interest pipeline-interest-${(
                                  lead.interest ?? "none"
                                ).toLowerCase()}`}
                              >
                                {lead.interest
                                  ? `${formatLabel(lead.interest)} interest`
                                  : "Interest not set"}
                              </span>

                              {!lead.is_active && (
                                <span className="pipeline-inactive-badge">
                                  Inactive
                                </span>
                              )}
                            </div>

                            <h3>{getContactName(contact)}</h3>

                            {contact?.phone && (
                              <p className="pipeline-contact-detail">
                                {contact.phone}
                              </p>
                            )}

                            {contact?.email && (
                              <p className="pipeline-contact-detail pipeline-email">
                                {contact.email}
                              </p>
                            )}

                            <div className="pipeline-card-divider" />

                            <div className="pipeline-card-detail">
                              <span>Next action</span>
                              <strong>
                                {lead.next_action?.trim() ||
                                  "No action planned"}
                              </strong>
                            </div>

                            <div className="pipeline-card-detail">
                              <span>Follow-up</span>
                              <strong
                                className={
                                  isOverdue ? "pipeline-overdue" : ""
                                }
                              >
                                {formatDate(lead.next_action_at)}
                              </strong>
                            </div>

                            <div className="pipeline-owner">
                              <span
                                className="pipeline-owner-avatar"
                                aria-hidden="true"
                              >
                                {lead.owner_user_id ? "✓" : "—"}
                              </span>
                              <span>
                                {lead.owner_user_id
                                  ? "Assigned owner"
                                  : "Unassigned"}
                              </span>
                            </div>

                            <label className="pipeline-stage-control">
                              <span>Move to stage</span>
                              <select
                                aria-label={`Change stage for ${getContactName(contact)}`}
                                value={lead.status}
                                disabled={
                                  updatingLeadId !== null ||
                                  ALLOWED_STATUS_TRANSITIONS[lead.status]
                                    .length === 0
                                }
                                onChange={(event) => {
                                  void handleStatusChange(
                                    lead,
                                    event.target.value as LeadStatus,
                                  );
                                }}
                              >
                                {availableStatuses.map((status) => (
                                  <option value={status} key={status}>
                                    {formatLabel(status)}
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
        )}

        <footer className="pipeline-board-footer">
          <span>
            {loading
              ? "Loading records…"
              : `${totalLeads} matching lead${totalLeads === 1 ? "" : "s"} across ${PIPELINE_STAGES.length} stages`}
          </span>
          <span>Status changes are recorded in lead activity.</span>
        </footer>
      </section>
    </section>
  );
}

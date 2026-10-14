
import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { followUpsApi } from "../services/followUpApi";
import type { FollowUp } from "../services/followUpApi";
import { ApiError } from "../lib/api";
import { contactsApi } from "../services/contactApi";
import type { Contact } from "../services/contactApi";
import { leadsApi } from "../services/leadApi";
import type { Lead, LeadStatus } from "../services/leadApi";
import { propertiesApi } from "../services/propertyApi";
import {
  activityApi,
  type LeadActivity,
} from "../services/activityApi";

type MetricKey = "contacts" | "leads" | "properties";
type AttentionCategory = "overdue" | "today";

interface DashboardMetric {
  value: number | null;
  loading: boolean;
  error: string | null;
}

interface DashboardMetrics {
  contacts: DashboardMetric;
  leads: DashboardMetric;
  properties: DashboardMetric;
}

interface OverviewCard {
  key: MetricKey | "followups";
  label: string;
  detail: string;
  icon: string;
}

interface AttentionItem {
  id: string;
  source: "lead" | "follow-up";
  lead: Lead;
  contactName: string;
  action: string;
  dueAt: Date;
  category: AttentionCategory;
  statusLabel: string;
}

const INITIAL_METRIC: DashboardMetric = {
  value: null,
  loading: true,
  error: null,
};

const INITIAL_METRICS: DashboardMetrics = {
  contacts: { ...INITIAL_METRIC },
  leads: { ...INITIAL_METRIC },
  properties: { ...INITIAL_METRIC },
};

const PAGE_SIZE = 100;

const CLOSED_STATUSES: LeadStatus[] = ["WON", "LOST"];

const overviewCards: OverviewCard[] = [
  {
    key: "contacts",
    label: "Total contacts",
    detail: "Your contact database",
    icon: "contacts",
  },
  {
    key: "leads",
    label: "Active leads",
    detail: "Active opportunities in progress",
    icon: "leads",
  },
  {
    key: "properties",
    label: "Properties",
    detail: "Your property inventory",
    icon: "properties",
  },
  {
    key: "followups",
    label: "Follow-ups",
    detail: "Actions requiring attention",
    icon: "followups",
  },
];

const quickActions = [
  {
    title: "Add a contact",
    description: "Save a buyer, seller, owner, or broker.",
    path: "/contacts",
    symbol: "+",
  },
  {
    title: "Manage leads",
    description: "Review opportunities and follow-up progress.",
    path: "/leads",
    symbol: "↗",
  },
  {
    title: "Browse properties",
    description: "View and organize your property inventory.",
    path: "/properties",
    symbol: "⌂",
  },
] as const;

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return "You don't have permission to view this data.";
    }

    return error.message;
  }

  return "The data could not be loaded. Check your connection and try again.";
}

function getContactName(contact: Contact | undefined): string {
  if (!contact) {
    return "Contact unavailable";
  }

  const name = [contact.first_name, contact.last_name]
    .filter((part): part is string => Boolean(part?.trim()))
    .join(" ")
    .trim();

  return name || "Unnamed contact";
}

function formatDueDate(date: Date): string {
  return date.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function OverviewIcon({ name }: { name: string }) {
  const common = {
    width: 21,
    height: 21,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true as const,
  };

  switch (name) {
    case "contacts":
      return (
        <svg {...common}>
          <circle cx="9" cy="8" r="3.2" />
          <path d="M3.5 19v-1.4a5.5 5.5 0 0 1 11 0V19" />
          <path d="M16 5.2a3.2 3.2 0 0 1 0 6.1" />
          <path d="M17 14a4.5 4.5 0 0 1 3.5 4.4V19" />
        </svg>
      );

    case "leads":
      return (
        <svg {...common}>
          <path d="M4 19V5" />
          <path d="M4 19h16" />
          <path d="m7 15 4-4 3 2 5-6" />
          <path d="M14.5 7H19v4.5" />
        </svg>
      );

    case "properties":
      return (
        <svg {...common}>
          <path d="m3 10 9-7 9 7" />
          <path d="M5.5 9v12h13V9" />
          <path d="M9 21v-7h6v7" />
        </svg>
      );

    default:
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
      );
  }
}

async function fetchAllLeads(): Promise<Lead[]> {
  const firstPage = await leadsApi.list({
    page: 1,
    page_size: PAGE_SIZE,
    is_active: true,
  });

  const allLeads = [...firstPage.items];

  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const result = await leadsApi.list({
      page,
      page_size: PAGE_SIZE,
      is_active: true,
    });

    allLeads.push(...result.items);
  }

  return allLeads;
}

async function fetchAllContacts(): Promise<Contact[]> {
  const firstPage = await contactsApi.list({
    page: 1,
    page_size: PAGE_SIZE,
  });

  const allContacts = [...firstPage.items];

  for (let page = 2; page <= firstPage.total_pages; page += 1) {
    const result = await contactsApi.list({
      page,
      page_size: PAGE_SIZE,
    });

    allContacts.push(...result.items);
  }

  return allContacts;
}

function buildAttentionItems(
  leads: Lead[],
  contacts: Contact[],
  followUps: FollowUp[],
  now: Date,
): AttentionItem[] {
  const contactsById = new Map(
    contacts.map((contact) => [contact.id, contact]),
  );

  const leadsById = new Map(
    leads.map((lead) => [lead.id, lead]),
  );

  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  );

  const startOfTomorrow = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate() + 1,
  );

  const items: AttentionItem[] = [];

  // Preserve existing lead-level next actions.
  for (const lead of leads) {
    if (!lead.is_active || CLOSED_STATUSES.includes(lead.status)) {
      continue;
    }

    if (!lead.next_action?.trim() || !lead.next_action_at) {
      continue;
    }

    const dueAt = new Date(lead.next_action_at);

    if (Number.isNaN(dueAt.getTime())) {
      continue;
    }

    let category: AttentionCategory;

    if (dueAt < startOfToday) {
      category = "overdue";
    } else if (dueAt < startOfTomorrow) {
      category = "today";
    } else {
      continue;
    }

    items.push({
      id: `lead-${lead.id}`,
      source: "lead",
      lead,
      contactName: getContactName(
        contactsById.get(lead.contact_id),
      ),
      action: lead.next_action.trim(),
      dueAt,
      category,
      statusLabel: lead.status.replaceAll("_", " "),
    });
  }

  // Add individual pending follow-up records.
  for (const followUp of followUps) {
    const lead = leadsById.get(followUp.lead_id);

    // Only show follow-ups associated with active, open leads.
    if (
      !lead ||
      !lead.is_active ||
      CLOSED_STATUSES.includes(lead.status)
    ) {
      continue;
    }

    const dueAt = new Date(followUp.due_at);

    if (Number.isNaN(dueAt.getTime())) {
      continue;
    }

    let category: AttentionCategory;

    if (dueAt < now) {
      category = "overdue";
    } else if (dueAt < startOfTomorrow) {
      category = "today";
    } else {
      continue;
    }

    items.push({
      id: `follow-up-${followUp.id}`,
      source: "follow-up",
      lead,
      contactName: getContactName(
        contactsById.get(lead.contact_id),
      ),
      action: followUp.title,
      dueAt,
      category,
      statusLabel: followUp.follow_up_type.replaceAll("_", " "),
    });
  }

  return items.sort((a, b) => {
    if (a.category !== b.category) {
      return a.category === "overdue" ? -1 : 1;
    }

    return a.dueAt.getTime() - b.dueAt.getTime();
  });
}

function AttentionList({
  title,
  items,
  category,
}: {
  title: string;
  items: AttentionItem[];
  category: AttentionCategory;
}) {
  return (
    <section
      className="attention-group"
      aria-labelledby={`attention-${category}-heading`}
    >
      <div className="attention-group-heading">
        <h3 id={`attention-${category}-heading`}>{title}</h3>
        <span
          className={`attention-count attention-count-${category}`}
          aria-label={`${items.length} ${category} follow-ups`}
        >
          {items.length}
        </span>
      </div>

      {items.length === 0 ? (
        <p className="attention-empty">
          {category === "overdue"
            ? "No overdue follow-ups. You're caught up."
            : "No remaining follow-ups due today."}
        </p>
      ) : (
        <ul className="attention-list">
          {items.map((item) => (
            <li
              className="attention-item"
              key={item.id}
            >
              <div className="attention-item-main">
                <div className="attention-item-copy">
                  <p className="attention-contact">
                    {item.contactName}
                  </p>
                  <p className="attention-action">
                    {item.action}
                  </p>
                  <p className="attention-due">
                    {category === "overdue" ? "Was due " : "Due "}
                    {formatDueDate(item.dueAt)}
                  </p>
                </div>

                <span className="attention-status">
                  {item.statusLabel}
                </span>
              </div>

              <Link
                className="text-link attention-open-link"
                to="/leads"
                aria-label={`Open leads to manage ${item.contactName}`}
              >
                Open leads <span aria-hidden="true">→</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function TodayPage() {
  const [metrics, setMetrics] =
    useState<DashboardMetrics>(INITIAL_METRICS);

  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");
const [recentActivities, setRecentActivities] = useState<LeadActivity[]>([]);
const [activityLoading, setActivityLoading] = useState(true);
const [activityError, setActivityError] = useState("");
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);
  const [attentionLoading, setAttentionLoading] = useState(true);
  const [attentionError, setAttentionError] = useState("");

  const loadDashboard = useCallback(async () => {
    setRefreshing(true);
    setRefreshError("");

    setMetrics({
      contacts: { ...INITIAL_METRIC },
      leads: { ...INITIAL_METRIC },
      properties: { ...INITIAL_METRIC },
    });

    try {
      const results = await Promise.allSettled([
        contactsApi.list({ page: 1, page_size: 1 }),
        leadsApi.list({
          page: 1,
          page_size: 1,
          is_active: true,
        }),
        propertiesApi.search({ page: 1, page_size: 1 }),
      ]);

      const nextMetrics: DashboardMetrics = {
        contacts: { value: null, loading: false, error: null },
        leads: { value: null, loading: false, error: null },
        properties: { value: null, loading: false, error: null },
      };

      const keys: MetricKey[] = ["contacts", "leads", "properties"];

      results.forEach((result, index) => {
        const key = keys[index];

        if (result.status === "fulfilled") {
          nextMetrics[key].value = result.value.total;
        } else {
          nextMetrics[key].error = getErrorMessage(result.reason);
        }
      });

      setMetrics(nextMetrics);

      if (results.every((result) => result.status === "rejected")) {
        setRefreshError(
          "Dashboard data could not be loaded. Check your connection and permissions.",
        );
      }
    } catch {
      setRefreshError(
        "Dashboard data could not be loaded. Check your connection and permissions.",
      );
    } finally {
      setRefreshing(false);
    }
  }, []);

  const loadAttention = useCallback(async () => {
    setAttentionLoading(true);
    setAttentionError("");

    try {
      const [leads, contacts, followUps] = await Promise.all([
        fetchAllLeads(),
        fetchAllContacts(),
        followUpsApi.list(),
      ]);

      setAttentionItems(
        buildAttentionItems(leads, contacts, followUps, new Date()),
      );
    } catch (error) {
      setAttentionError(getErrorMessage(error));
      setAttentionItems([]);
    } finally {
      setAttentionLoading(false);
    }
  }, []);
const loadRecentActivity = useCallback(async () => {
  setActivityLoading(true);
  setActivityError("");

  try {
    const response = await activityApi.listRecent(10);
    setRecentActivities(response.items);
  } catch (error) {
    setActivityError(getErrorMessage(error));
    setRecentActivities([]);
  } finally {
    setActivityLoading(false);
  }
}, []);
  const refreshAll = useCallback(async () => {
  await Promise.all([
    loadDashboard(),
    loadAttention(),
    loadRecentActivity(),
  ]);
}, [loadDashboard, loadAttention, loadRecentActivity]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  function displayMetric(key: MetricKey): string {
    const metric = metrics[key];

    if (metric.loading) return "…";
    if (metric.error || metric.value === null) return "—";

    return metric.value.toLocaleString("en-IN");
  }

  function metricDescription(
    key: MetricKey,
    defaultDescription: string,
  ): string {
    const metric = metrics[key];

    if (metric.loading) {
      return "Loading your workspace data…";
    }

    if (metric.error) {
      return metric.error;
    }

    if (metric.value === 0) {
      if (key === "contacts") {
        return "Add your first contact to get started.";
      }

      if (key === "leads") {
        return "No active leads yet.";
      }

      return "No properties recorded yet.";
    }

    return defaultDescription;
  }

  const overdueItems = attentionItems.filter(
    (item) => item.category === "overdue",
  );

  const dueTodayItems = attentionItems.filter(
    (item) => item.category === "today",
  );

  const attentionCount = attentionItems.length;

  return (
    <section className="today-page">
      <header className="page-heading today-heading">
        <div className="today-introduction">
          <span className="page-eyebrow">YOUR WORKSPACE</span>
          <h1>Today</h1>
          <p>
            Your real estate business, organized in one place. Start with
            what needs your attention.
          </p>
        </div>

        <Link
          className="button button-primary today-primary-action"
          to="/contacts"
        >
          <span aria-hidden="true">+</span>
          Add a contact
        </Link>
      </header>

      <section
        className="dashboard-overview"
        aria-labelledby="overview-heading"
      >
        <div className="dashboard-section-heading">
          <div>
            <h2 id="overview-heading">Business overview</h2>
            <p>Your workspace at a glance.</p>
          </div>

          <button
            className="button button-secondary button-sm"
            type="button"
            onClick={() => void refreshAll()}
            disabled={refreshing || attentionLoading}
          >
            {refreshing || attentionLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {refreshError && (
          <div className="dashboard-data-error" role="alert">
            <p>{refreshError}</p>
            <button
              className="button button-secondary button-sm"
              type="button"
              onClick={() => void refreshAll()}
              disabled={refreshing || attentionLoading}
            >
              Try again
            </button>
          </div>
        )}

        <div className="overview-grid">
          {overviewCards.map((card, index) => {
            const metricKey =
              card.key === "followups" ? null : card.key;
            const metric =
              metricKey === null ? null : metrics[metricKey];

            let value = "—";
            let description = "Follow-up data is loading…";
            let unavailable = false;
            let busy = false;

            if (metricKey !== null) {
              value = displayMetric(metricKey);
              description = metricDescription(metricKey, card.detail);
              unavailable = Boolean(metric?.error);
              busy = metric?.loading ?? false;
            } else if (attentionLoading) {
              value = "…";
              description = "Checking overdue and due-today actions.";
              busy = true;
            } else if (attentionError) {
              value = "—";
              description = "Follow-ups could not be loaded.";
              unavailable = true;
            } else {
              value = attentionCount.toLocaleString("en-IN");
              description = `${overdueItems.length} overdue · ${dueTodayItems.length} due today`;
            }

            return (
              <article
                className="overview-card"
                key={card.key}
                style={{ "--card-index": index } as CSSProperties}
              >
                <div className="overview-card-top">
                  <span className="overview-icon">
                    <OverviewIcon name={card.icon} />
                  </span>

                  <span className="overview-indicator">
                    {unavailable ? "Unavailable" : "Overview"}
                  </span>
                </div>

                <p className="overview-label">{card.label}</p>

                <p
                  className="overview-value"
                  aria-live="polite"
                  aria-busy={busy}
                >
                  {value}
                </p>

                <p className="overview-description">{description}</p>
              </article>
            );
          })}
        </div>
      </section>

      <section
        className="dashboard-section"
        aria-labelledby="actions-heading"
      >
        <div className="dashboard-section-heading">
          <div>
            <h2 id="actions-heading">Quick actions</h2>
            <p>Jump straight into the work that matters.</p>
          </div>
        </div>

        <div className="quick-actions-grid">
          {quickActions.map((action, index) => (
            <Link
              className="quick-action-card"
              key={action.title}
              to={action.path}
              style={{ "--card-index": index } as CSSProperties}
            >
              <span className="quick-action-symbol" aria-hidden="true">
                {action.symbol}
              </span>

              <span className="quick-action-copy">
                <span className="quick-action-title">
                  {action.title}
                </span>

                <span className="quick-action-description">
                  {action.description}
                </span>
              </span>

              <span className="quick-action-arrow" aria-hidden="true">
                →
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section
        className="dashboard-bottom-grid"
        aria-label="Workspace activity"
      >
        <article className="surface dashboard-panel">
          <div className="section-heading">
            <div>
              <h2>Today’s attention</h2>
              <p>Prioritize overdue actions and today's follow-ups.</p>
            </div>

            <button
              className="button button-secondary button-sm"
              type="button"
              onClick={() => void loadAttention()}
              disabled={attentionLoading}
            >
              {attentionLoading ? "Loading…" : "Refresh"}
            </button>
          </div>

          {attentionError && (
            <div className="dashboard-data-error" role="alert">
              <p>{attentionError}</p>
              <button
                className="button button-secondary button-sm"
                type="button"
                onClick={() => void loadAttention()}
                disabled={attentionLoading}
              >
                Try again
              </button>
            </div>
          )}

          {attentionLoading ? (
            <div
              className="dashboard-empty-state attention-loading"
              role="status"
            >
              <span className="empty-state-icon" aria-hidden="true">
                <OverviewIcon name="followups" />
              </span>
              <h3>Loading today's attention</h3>
              <p>
                Checking lead actions and individual scheduled follow-ups.
              </p>
            </div>
          ) : attentionError ? (
            <div className="dashboard-empty-state">
              <span className="empty-state-icon" aria-hidden="true">
                <OverviewIcon name="followups" />
              </span>
              <h3>Attention items are unavailable</h3>
              <p>
                Retry the request. Your follow-up data has not been changed.
              </p>
            </div>
          ) : (
            <div className="attention-content">
              <AttentionList
                title="Overdue"
                items={overdueItems}
                category="overdue"
              />

              <AttentionList
                title="Due today"
                items={dueTodayItems}
                category="today"
              />

              <Link className="text-link attention-all-link" to="/leads">
                View all leads <span aria-hidden="true">→</span>
              </Link>
            </div>
          )}
        </article>


        <article className="surface dashboard-panel">
          <div className="section-heading">
            <div>
              <h2>Recent activity</h2>
              <p>Stay informed about changes in your workspace.</p>
            </div>

            <span className="panel-count">
              {recentActivities.length.toString().padStart(2, "0")}
            </span>
          </div>

          {activityError && (
            <div className="dashboard-data-error" role="alert">
              <p>{activityError}</p>
              <button
                className="button button-secondary button-sm"
                type="button"
                onClick={() => void loadRecentActivity()}
                disabled={activityLoading}
              >
                Try again
              </button>
            </div>
          )}

          {activityLoading ? (
            <div className="dashboard-empty-state activity-empty-state" role="status">
              <span className="empty-state-icon" aria-hidden="true">
                <OverviewIcon name="followups" />
              </span>
              <h3>Loading recent activity</h3>
              <p>Fetching the latest recorded lead activities.</p>
            </div>
          ) : activityError ? (
            <div className="dashboard-empty-state activity-empty-state">
              <span className="empty-state-icon" aria-hidden="true">
                <OverviewIcon name="followups" />
              </span>
              <h3>Activity is temporarily unavailable</h3>
              <p>Retry to load the latest recorded activities.</p>
            </div>
          ) : recentActivities.length === 0 ? (
            <div className="dashboard-empty-state activity-empty-state">
              <span className="empty-state-icon" aria-hidden="true">
                <OverviewIcon name="followups" />
              </span>
              <h3>No activity recorded yet</h3>
              <p>
                Activities recorded against leads will appear here.
              </p>
              <Link className="text-link" to="/leads">
                View leads <span aria-hidden="true">→</span>
              </Link>
            </div>
          ) : (
            <ul className="recent-activity-list">
              {recentActivities.map((activity) => (
                <li className="recent-activity-item" key={activity.id}>
                  <div className="recent-activity-main">
                    <span className="recent-activity-type">
                      {activity.activity_type.replaceAll("_", " ")}
                    </span>

                    <p className="recent-activity-title">{activity.title}</p>

                    {activity.description && (
                      <p className="recent-activity-description">
                        {activity.description}
                      </p>
                    )}

                    <p className="recent-activity-meta">
                      {activity.actor_display_name?.trim() || "Workspace member"}
                      {" · "}
                      {new Date(activity.occurred_at).toLocaleString("en-IN", {
                        day: "numeric",
                        month: "short",
                        hour: "numeric",
                        minute: "2-digit",
                      })}
                    </p>
                  </div>

                  <Link
                    className="text-link recent-activity-link"
                    to="/leads"
                    aria-label={`View leads related to ${activity.title}`}
                  >
                    View <span aria-hidden="true">→</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </article>
      </section>
    </section>
  );
}

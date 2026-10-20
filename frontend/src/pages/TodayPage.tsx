import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../lib/api";
import { activityApi, type LeadActivity } from "../services/activityApi";
import { contactsApi } from "../services/contactApi";
import type { Contact } from "../services/contactApi";
import { followUpsApi } from "../services/followUpApi";
import type { FollowUp } from "../services/followUpApi";
import { leadsApi } from "../services/leadApi";
import type { Lead, LeadStatus } from "../services/leadApi";
import { propertiesApi } from "../services/propertyApi";
import "./TodayPage.css";

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
  icon: "contacts" | "leads" | "properties" | "followups";
  tone: "violet" | "teal" | "blue" | "coral";
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
    detail: "People in your database",
    icon: "contacts",
    tone: "violet",
  },
  {
    key: "leads",
    label: "Active leads",
    detail: "Opportunities in progress",
    icon: "leads",
    tone: "teal",
  },
  {
    key: "properties",
    label: "Properties",
    detail: "Your current inventory",
    icon: "properties",
    tone: "blue",
  },
  {
    key: "followups",
    label: "Follow-ups",
    detail: "Actions needing attention",
    icon: "followups",
    tone: "coral",
  },
];

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

function formatActivityDate(value: string): string {
  return new Date(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

function DashboardIcon({
  name,
  size = 20,
}: {
  name: "contacts" | "leads" | "properties" | "followups" | "contact" | "property" | "arrow" | "refresh" | "clock" | "activity" | "alert";
  size?: number;
}) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true as const,
  };

  switch (name) {
    case "contacts":
    case "contact":
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
    case "property":
      return (
        <svg {...common}>
          <path d="m3 10 9-7 9 7" />
          <path d="M5.5 9v12h13V9" />
          <path d="M9 21v-7h6v7" />
        </svg>
      );
    case "followups":
    case "clock":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
      );
    case "refresh":
      return (
        <svg {...common}>
          <path d="M20 7v5h-5" />
          <path d="M4.8 9a7.5 7.5 0 0 1 12.7-2L20 12" />
          <path d="M4 17v-5h5" />
          <path d="M19.2 15a7.5 7.5 0 0 1-12.7 2L4 12" />
        </svg>
      );
    case "activity":
      return (
        <svg {...common}>
          <path d="M3 12h4l3-7 4 14 3-7h4" />
        </svg>
      );
    case "alert":
      return (
        <svg {...common}>
          <path d="m12 3 9 16H3L12 3Z" />
          <path d="M12 9v4M12 16.5h.01" />
        </svg>
      );
    case "arrow":
      return (
        <svg {...common}>
          <path d="M5 12h14M13 6l6 6-6 6" />
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
  const leadsById = new Map(leads.map((lead) => [lead.id, lead]));

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

  // Preserve the existing lead-level next-action behavior.
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
      contactName: getContactName(contactsById.get(lead.contact_id)),
      action: lead.next_action.trim(),
      dueAt,
      category,
      statusLabel: lead.status.replaceAll("_", " "),
    });
  }

  // Preserve the existing individual pending follow-up behavior.
  for (const followUp of followUps) {
    const lead = leadsById.get(followUp.lead_id);

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
      contactName: getContactName(contactsById.get(lead.contact_id)),
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

    const dueTimeDifference = a.dueAt.getTime() - b.dueAt.getTime();

    if (dueTimeDifference !== 0) {
      return dueTimeDifference;
    }

    const interestRank: Record<"HIGH" | "MEDIUM" | "LOW", number> = {
      HIGH: 3,
      MEDIUM: 2,
      LOW: 1,
    };

    const aRank = a.lead.interest ? interestRank[a.lead.interest] : 0;
    const bRank = b.lead.interest ? interestRank[b.lead.interest] : 0;

    if (aRank !== bRank) {
      return bRank - aRank;
    }

    return a.id.localeCompare(b.id);
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
      className={`today-attention-group today-attention-group-${category}`}
      aria-labelledby={`attention-${category}-heading`}
    >
      <div className="today-attention-group-heading">
        <h3 id={`attention-${category}-heading`}>{title}</h3>
        <span
          className={`today-count today-count-${category}`}
          aria-label={`${items.length} ${category} follow-ups`}
        >
          {items.length}
        </span>
      </div>

      {items.length === 0 ? (
        <div className="today-attention-empty">
          <span className="today-empty-check" aria-hidden="true">✓</span>
          <p>
            {category === "overdue"
              ? "No overdue follow-ups. You're caught up."
              : "No remaining follow-ups due today."}
          </p>
        </div>
      ) : (
        <ul className="today-attention-list">
          {items.map((item) => (
            <li className="today-attention-item" key={item.id}>
              <span className="today-attention-marker" aria-hidden="true">
                <DashboardIcon name={category === "overdue" ? "alert" : "clock"} size={16} />
              </span>

              <div className="today-attention-item-content">
                <div className="today-attention-item-heading">
                  <p className="today-attention-contact">{item.contactName}</p>
                  <span className="today-attention-status">{item.statusLabel}</span>
                </div>
                <p className="today-attention-action">{item.action}</p>
                <p className="today-attention-due">
                  {category === "overdue" ? "Was due " : "Due "}
                  {formatDueDate(item.dueAt)}
                </p>
                <Link
                  className="today-text-link today-attention-open-link"
                  to="/leads"
                  aria-label={`Open leads to manage ${item.contactName}`}
                >
                  Open lead <DashboardIcon name="arrow" size={14} />
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function TodayPage() {
  const [metrics, setMetrics] = useState<DashboardMetrics>(INITIAL_METRICS);
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
        leadsApi.list({ page: 1, page_size: 1, is_active: true }),
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

  const overdueItems = attentionItems.filter(
    (item) => item.category === "overdue",
  );
  const dueTodayItems = attentionItems.filter(
    (item) => item.category === "today",
  );
  const attentionCount = attentionItems.length;

  const today = new Date();
  const greeting = today.getHours() < 12 ? "Good morning" : today.getHours() < 18 ? "Good afternoon" : "Good evening";
  const dateLabel = today.toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  return (
    <main className="today-page" aria-labelledby="today-page-title">
      <header className="today-header">
        <div className="today-header-copy">
          <p className="today-date">{dateLabel}</p>
          <h1 id="today-page-title">{greeting}</h1>
          <p className="today-subtitle">Let’s move your business forward.</p>
        </div>
        <div className="today-header-actions">
          <button
            className="today-icon-button"
            type="button"
            onClick={() => void refreshAll()}
            disabled={refreshing || attentionLoading}
            aria-label="Refresh dashboard"
            title="Refresh dashboard"
          >
            <DashboardIcon name="refresh" size={17} />
          </button>
        </div>
      </header>

      {refreshError && (
        <div className="today-alert" role="alert">
          <DashboardIcon name="alert" size={17} />
          <p>{refreshError}</p>
          <button type="button" onClick={() => void refreshAll()} disabled={refreshing || attentionLoading}>Retry</button>
        </div>
      )}

      <section className="today-overview-section" aria-labelledby="today-overview-title">
        <div className="today-section-header compact">
          <div><p className="today-overline">AT A GLANCE</p><h2 id="today-overview-title">Business overview</h2></div>
        </div>
        <div className="today-metrics-grid">
          {overviewCards.filter((card) => card.key !== "followups").map((card) => {
            const metricKey = card.key as MetricKey;
            const metric = metrics[metricKey];
            const value = displayMetric(metricKey);
            const busy = metric?.loading ?? false;
            const unavailable = Boolean(metric?.error);
            return (
              <Link className={`today-metric-card ${metricKey}`} key={card.key} to={metricKey === "contacts" ? "/contacts" : metricKey === "leads" ? "/leads" : "/properties"}>
                <span className={`today-metric-icon ${metricKey}`}><DashboardIcon name={card.icon} size={19} /></span>
                <span className="today-metric-content">
                  <span className="today-metric-label">{card.label}</span>
                  <strong className="today-metric-value" aria-live="polite" aria-busy={busy}>{value}</strong>
                  <span className="today-metric-description">{unavailable ? "Data unavailable" : busy ? "Updating…" : card.detail}</span>
                </span>
                <span className="today-metric-arrow" aria-hidden="true"><DashboardIcon name="arrow" size={15} /></span>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="today-work-section" aria-labelledby="today-priorities-title">
        <div className="today-section-header">
          <div>
            <p className="today-overline">YOUR WORKSPACE</p>
            <h2 id="today-priorities-title">What needs your attention</h2>
            <p className="today-section-description">Start with overdue follow-ups, then work through what’s due today.</p>
          </div>
          <Link className="today-subtle-link" to="/leads">Open leads <DashboardIcon name="arrow" size={14} /></Link>
        </div>

        <article className="today-priority-card">
          <div className="today-priority-summary">
            <div className="today-priority-title">
              <span className="today-priority-symbol"><DashboardIcon name="clock" size={19} /></span>
              <div>
                <h3>Follow-up queue</h3>
                <p>Keep conversations moving. Every follow-up is an opportunity.</p>
              </div>
            </div>
            <div className="today-priority-counts" aria-label="Follow-up summary">
              <span className="today-count-pill overdue"><strong>{overdueItems.length}</strong> overdue</span>
              <span className="today-count-pill due"><strong>{dueTodayItems.length}</strong> due today</span>
            </div>
          </div>

          {attentionError && (
            <div className="today-alert today-alert-inline" role="alert">
              <DashboardIcon name="alert" size={17} />
              <p>{attentionError}</p>
              <button type="button" onClick={() => void loadAttention()} disabled={attentionLoading}>Retry</button>
            </div>
          )}

          {attentionLoading ? (
            <div className="today-state" role="status">
              <span className="today-spinner" aria-hidden="true" />
              <div><strong>Loading your follow-ups</strong><p>Gathering actions from leads and scheduled follow-ups.</p></div>
            </div>
          ) : attentionError ? (
            <div className="today-state"><span className="today-state-icon"><DashboardIcon name="alert" size={19} /></span><div><strong>Follow-ups couldn’t be loaded</strong><p>Try again to see the latest priorities.</p></div></div>
          ) : attentionCount === 0 ? (
            <div className="today-state today-state-success">
              <span className="today-state-icon" aria-hidden="true">✓</span>
              <div><strong>You’re all caught up</strong><p>No overdue or due-today actions were found for active leads.</p></div>
            </div>
          ) : (
            <div className="today-attention-content">
              <AttentionList title="Overdue" items={overdueItems} category="overdue" />
              <AttentionList title="Due today" items={dueTodayItems} category="today" />
            </div>
          )}
          <div className="today-card-footer"><Link to="/leads">Manage follow-ups <DashboardIcon name="arrow" size={14} /></Link></div>
        </article>
      </section>

      <section className="today-bottom-grid" aria-label="Shortcuts and recent activity">
        <article className="today-secondary-card">
          <div className="today-secondary-heading"><div><p className="today-overline">GET THINGS DONE</p><h2>Quick access</h2></div></div>
          <nav className="today-shortcuts" aria-label="Quick access">
            <Link to="/contacts"><span className="today-shortcut-icon"><DashboardIcon name="contacts" size={18} /></span><span><strong>Contacts</strong><small>Add and manage relationships</small></span><DashboardIcon name="arrow" size={15} /></Link>
            <Link to="/leads"><span className="today-shortcut-icon"><DashboardIcon name="leads" size={18} /></span><span><strong>Leads</strong><small>Review active opportunities</small></span><DashboardIcon name="arrow" size={15} /></Link>
            <Link to="/properties"><span className="today-shortcut-icon"><DashboardIcon name="properties" size={18} /></span><span><strong>Properties</strong><small>Manage your inventory</small></span><DashboardIcon name="arrow" size={15} /></Link>
          </nav>
        </article>

        <article className="today-secondary-card">
          <div className="today-secondary-heading activity-heading">
            <div><p className="today-overline">LATEST UPDATES</p><h2>Recent activity</h2></div>
            <span className="today-activity-count">{recentActivities.length}</span>
          </div>
          {activityError && <div className="today-alert today-alert-inline" role="alert"><DashboardIcon name="alert" size={16} /><p>{activityError}</p><button type="button" onClick={() => void loadRecentActivity()} disabled={activityLoading}>Retry</button></div>}
          {activityLoading ? (
            <div className="today-activity-state" role="status"><span className="today-spinner" aria-hidden="true" />Loading activity…</div>
          ) : activityError ? (
            <div className="today-activity-state">Activity is temporarily unavailable.</div>
          ) : recentActivities.length === 0 ? (
            <div className="today-activity-state">New lead activity will appear here as your team works.</div>
          ) : (
            <ul className="today-activity-list">
              {recentActivities.map((activity) => (
                <li key={activity.id}>
                  <span className="today-activity-marker"><DashboardIcon name="activity" size={14} /></span>
                  <div className="today-activity-copy">
                    <strong>{activity.title}</strong>
                    {activity.description && <p>{activity.description}</p>}
                    <small>{activity.actor_display_name?.trim() || "Workspace member"} <span aria-hidden="true">·</span> <time dateTime={activity.occurred_at}>{formatActivityDate(activity.occurred_at)}</time></small>
                  </div>
                  <Link to="/leads" aria-label={`View leads related to ${activity.title}`} className="today-activity-link">View</Link>
                </li>
              ))}
            </ul>
          )}
          <div className="today-card-footer"><Link to="/leads">Explore lead activity <DashboardIcon name="arrow" size={14} /></Link></div>
        </article>
      </section>
    </main>
  );
}

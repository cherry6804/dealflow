import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../lib/api";
import { activityApi, type LeadActivity } from "../services/activityApi";
import { contactsApi } from "../services/contactApi";
import {
  dashboardApi,
  type DashboardSummary,
  type DealSummary,
} from "../services/dashboardApi";
import { leadsApi } from "../services/leadApi";
import { propertiesApi } from "../services/propertyApi";
import "./TodayPage.css";

type MetricKey = "contacts" | "leads" | "properties";
type AttentionCategory = "overdue" | "today" | "upcoming";

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
  interest: string | null;
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

const INTEREST_RANK: Record<string, number> = {
  HIGH: 3,
  MEDIUM: 2,
  LOW: 1,
};

const CATEGORY_RANK: Record<AttentionCategory, number> = {
  overdue: 0,
  today: 1,
  upcoming: 2,
};

const PIPELINE_STAGES: { key: string; label: string }[] = [
  { key: "NEW", label: "New" },
  { key: "QUALIFICATION", label: "Qualification" },
  { key: "NEGOTIATION", label: "Negotiation" },
  { key: "BOOKING", label: "Booking" },
  { key: "CLOSED_WON", label: "Closed won" },
  { key: "CLOSED_LOST", label: "Closed lost" },
];

function buildAttentionItems(summary: DashboardSummary): AttentionItem[] {
  const items: AttentionItem[] = [];

  if (summary.follow_ups) {
    for (const category of ["overdue", "today", "upcoming"] as const) {
      for (const followUp of summary.follow_ups[category]) {
        items.push({
          id: `follow-up-${followUp.id}`,
          source: "follow-up",
          interest: followUp.interest,
          contactName: followUp.contact_name,
          action: followUp.title,
          dueAt: new Date(followUp.due_at),
          category,
          statusLabel: followUp.follow_up_type.replaceAll("_", " "),
        });
      }
    }
  }

  if (summary.lead_actions) {
    for (const category of ["overdue", "today"] as const) {
      for (const leadAction of summary.lead_actions[category]) {
        items.push({
          id: `lead-${leadAction.lead_id}-${category}`,
          source: "lead",
          interest: leadAction.interest,
          contactName: leadAction.contact_name,
          action: leadAction.action,
          dueAt: new Date(leadAction.due_at),
          category,
          statusLabel: leadAction.status.replaceAll("_", " "),
        });
      }
    }
  }

  return items.sort((a, b) => {
    if (a.category !== b.category) {
      return CATEGORY_RANK[a.category] - CATEGORY_RANK[b.category];
    }

    const dueTimeDifference = a.dueAt.getTime() - b.dueAt.getTime();

    if (dueTimeDifference !== 0) {
      return dueTimeDifference;
    }

    const aRank = a.interest ? (INTEREST_RANK[a.interest] ?? 0) : 0;
    const bRank = b.interest ? (INTEREST_RANK[b.interest] ?? 0) : 0;

    return bRank - aRank;
  });
}

function PipelineSummary({ deals }: { deals: DealSummary }) {
  const totalDeals = Object.values(deals.by_stage).reduce((sum, count) => sum + count, 0);

  if (totalDeals === 0) {
    return (
      <div className="today-state">
        <span className="today-state-icon" aria-hidden="true">+</span>
        <div>
          <strong>No deals yet</strong>
          <p>Deals you create will be counted by stage here.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="today-pipeline">
      <ul className="today-pipeline-stages" aria-label="Deals by stage">
        {PIPELINE_STAGES.map((stage) => (
          <li className="today-pipeline-stage" key={stage.key}>
            <span>{stage.label}</span>
            <strong>{deals.by_stage[stage.key] ?? 0}</strong>
          </li>
        ))}
      </ul>

      {deals.open_value_by_currency.length === 0 ? (
        <p className="today-pipeline-note">No expected value recorded on open deals.</p>
      ) : (
        <ul className="today-pipeline-values" aria-label="Open pipeline value by currency">
          {deals.open_value_by_currency.map((value) => (
            <li key={value.currency}>
              <span>Open value · {value.currency}</span>
              <strong>
                {value.currency} {Number(value.total).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </strong>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AttentionList({
  title,
  items,
  total,
  category,
}: {
  title: string;
  items: AttentionItem[];
  total: number;
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
          aria-label={`${total} ${category} follow-ups`}
        >
          {total}
        </span>
      </div>

      {items.length === 0 ? (
        <div className="today-attention-empty">
          <span className="today-empty-check" aria-hidden="true">✓</span>
          <p>
            {category === "overdue"
              ? "No overdue follow-ups. You're caught up."
              : category === "today"
                ? "No remaining follow-ups due today."
                : "No upcoming follow-ups scheduled."}
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
          {total > items.length && (
            <li className="today-attention-more">Showing {items.length} of {total}.</li>
          )}
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
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
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
      const startOfToday = new Date();
      startOfToday.setHours(0, 0, 0, 0);
      const startOfTomorrow = new Date(startOfToday);
      startOfTomorrow.setDate(startOfTomorrow.getDate() + 1);

      setSummary(await dashboardApi.getSummary(startOfToday, startOfTomorrow));
    } catch (error) {
      setAttentionError(getErrorMessage(error));
      setSummary(null);
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

  const attentionItems = summary ? buildAttentionItems(summary) : [];
  const overdueItems = attentionItems.filter((item) => item.category === "overdue");
  const dueTodayItems = attentionItems.filter((item) => item.category === "today");
  const upcomingItems = attentionItems.filter((item) => item.category === "upcoming");
  const overdueTotal =
    (summary?.follow_ups?.overdue_count ?? 0) + (summary?.lead_actions?.overdue_count ?? 0);
  const dueTodayTotal =
    (summary?.follow_ups?.today_count ?? 0) + (summary?.lead_actions?.today_count ?? 0);
  const upcomingTotal = summary?.follow_ups?.upcoming_count ?? 0;
  const attentionCount = overdueTotal + dueTodayTotal + upcomingTotal;

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
              <span className="today-count-pill overdue"><strong>{overdueTotal}</strong> overdue</span>
              <span className="today-count-pill due"><strong>{dueTodayTotal}</strong> due today</span>
              <span className="today-count-pill"><strong>{upcomingTotal}</strong> upcoming</span>
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
              <AttentionList title="Overdue" items={overdueItems} total={overdueTotal} category="overdue" />
              <AttentionList title="Due today" items={dueTodayItems} total={dueTodayTotal} category="today" />
              <AttentionList title="Upcoming" items={upcomingItems} total={upcomingTotal} category="upcoming" />
            </div>
          )}
          <div className="today-card-footer"><Link to="/leads">Manage follow-ups <DashboardIcon name="arrow" size={14} /></Link></div>
        </article>
      </section>

      <section className="today-work-section" aria-labelledby="today-pipeline-title">
        <div className="today-section-header">
          <div>
            <p className="today-overline">DEALS</p>
            <h2 id="today-pipeline-title">Deal pipeline</h2>
            <p className="today-section-description">Open deals by stage. Expected value is totalled separately for each currency.</p>
          </div>
          <Link className="today-subtle-link" to="/deals">Open deals <DashboardIcon name="arrow" size={14} /></Link>
        </div>

        <article className="today-priority-card">
          {attentionLoading ? (
            <div className="today-state" role="status">
              <span className="today-spinner" aria-hidden="true" />
              <div><strong>Loading pipeline</strong><p>Counting deals by stage.</p></div>
            </div>
          ) : attentionError ? (
            <div className="today-state">
              <span className="today-state-icon"><DashboardIcon name="alert" size={19} /></span>
              <div><strong>Pipeline couldn’t be loaded</strong><p>Use Retry in the follow-up queue above to refresh the summary.</p></div>
            </div>
          ) : summary && summary.deals === null ? (
            <div className="today-state">
              <span className="today-state-icon" aria-hidden="true">!</span>
              <div><strong>Deal data isn’t available for your role</strong><p>Ask an administrator if you need access to deals.</p></div>
            </div>
          ) : summary?.deals ? (
            <PipelineSummary deals={summary.deals} />
          ) : null}
          <div className="today-card-footer"><Link to="/deals">Manage deals <DashboardIcon name="arrow" size={14} /></Link></div>
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

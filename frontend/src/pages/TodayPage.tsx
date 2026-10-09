import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../lib/api";
import { contactsApi } from "../services/contactApi";
import { leadsApi } from "../services/leadApi";
import { propertiesApi } from "../services/propertyApi";

type MetricKey = "contacts" | "leads" | "properties";

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
      return "You don't have permission to view this metric.";
    }

    return error.message;
  }

  return "This metric could not be loaded.";
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

export default function TodayPage() {
  const [metrics, setMetrics] =
    useState<DashboardMetrics>(INITIAL_METRICS);

  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");

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
        contactsApi.list({
          page: 1,
          page_size: 1,
        }),
        leadsApi.list({
          page: 1,
          page_size: 1,
          is_active: true,
        }),
        propertiesApi.search({
          page: 1,
          page_size: 1,
        }),
      ]);

      const nextMetrics: DashboardMetrics = {
        contacts: { value: null, loading: false, error: null },
        leads: { value: null, loading: false, error: null },
        properties: { value: null, loading: false, error: null },
      };

      const keys: MetricKey[] = [
        "contacts",
        "leads",
        "properties",
      ];

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
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function fetchDashboard() {
      setRefreshing(true);
      setRefreshError("");

      try {
        const results = await Promise.allSettled([
          contactsApi.list({
            page: 1,
            page_size: 1,
          }),
          leadsApi.list({
            page: 1,
            page_size: 1,
            is_active: true,
          }),
          propertiesApi.search({
            page: 1,
            page_size: 1,
          }),
        ]);

        if (cancelled) return;

        const nextMetrics: DashboardMetrics = {
          contacts: { value: null, loading: false, error: null },
          leads: { value: null, loading: false, error: null },
          properties: { value: null, loading: false, error: null },
        };

        const keys: MetricKey[] = [
          "contacts",
          "leads",
          "properties",
        ];

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
      } finally {
        if (!cancelled) {
          setRefreshing(false);
        }
      }
    }

    void fetchDashboard();

    return () => {
      cancelled = true;
    };
  }, []);

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
            onClick={() => void loadDashboard()}
            disabled={refreshing}
          >
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {refreshError && (
          <div className="dashboard-data-error" role="alert">
            <p>{refreshError}</p>

            <button
              className="button button-secondary button-sm"
              type="button"
              onClick={() => void loadDashboard()}
              disabled={refreshing}
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
            let description = "Follow-up tracking is not configured yet.";

            if (metricKey !== null) {
              value = displayMetric(metricKey);
              description = metricDescription(metricKey, card.detail);
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
                    {metric?.error ? "Unavailable" : "Overview"}
                  </span>
                </div>

                <p className="overview-label">{card.label}</p>

                <p
                  className="overview-value"
                  aria-live="polite"
                  aria-busy={metric?.loading ?? false}
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
              style={
                { "--card-index": index } as CSSProperties
              }
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
              <h2>Follow-up workspace</h2>
              <p>
                Keep conversations from slipping through the cracks.
              </p>
            </div>

            <span className="panel-count">01</span>
          </div>

          <div className="dashboard-empty-state">
            <span className="empty-state-icon" aria-hidden="true">
              <OverviewIcon name="followups" />
            </span>

            <h3>Follow-up tracking is coming next</h3>

            <p>
              Once follow-up dates and reminders are implemented, upcoming
              actions will appear here.
            </p>

            <Link className="text-link" to="/leads">
              Explore leads <span aria-hidden="true">→</span>
            </Link>
          </div>
        </article>

        <article className="surface dashboard-panel">
          <div className="section-heading">
            <div>
              <h2>Recent activity</h2>
              <p>Stay informed about changes in your workspace.</p>
            </div>

            <span className="panel-count">02</span>
          </div>

          <div className="dashboard-empty-state activity-empty-state">
            <span className="empty-state-icon" aria-hidden="true">
              <OverviewIcon name="followups" />
            </span>

            <h3>Activity tracking isn't connected yet</h3>

            <p>
              Recent contact, lead, and property updates will appear here
              after activity tracking is implemented.
            </p>
          </div>
        </article>
      </section>
    </section>
  );
}
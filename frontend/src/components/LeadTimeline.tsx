
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError } from "../lib/api";
import {
  activityApi,
  type LeadActivity,
} from "../services/activityApi";
import SiteVisitHistory from "./SiteVisitHistory";
import "./LeadTimeline.css";

interface LeadTimelineProps {
  leadId: string;
  contactName: string;
  onClose: () => void;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
}

function formatActivityType(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

function formatTimestamp(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Date unavailable";
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDateTimeValue(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    return "Not scheduled";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatActionValue(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    return "Not set";
  }

  return value;
}

function sortActivities(items: LeadActivity[]): LeadActivity[] {
  return [...items].sort((a, b) => {
    const timeDifference =
      new Date(b.occurred_at).getTime() -
      new Date(a.occurred_at).getTime();

    return timeDifference || b.id.localeCompare(a.id);
  });
}

function ActivityChangeDetails({
  activity,
}: {
  activity: LeadActivity;
}) {
  const details = activity.details;

  if (!details) {
    return null;
  }

  if (details.field === "next_action") {
    return (
      <div className="lead-timeline-change" aria-label="Next action changes">
        <div className="lead-timeline-change-row">
          <span>Previous action</span>
          <p>{formatActionValue(details.old_next_action)}</p>
        </div>

        <div className="lead-timeline-change-row">
          <span>Updated action</span>
          <p>{formatActionValue(details.new_next_action)}</p>
        </div>
      </div>
    );
  }

  if (details.field === "next_action_at") {
    return (
      <div
        className="lead-timeline-change"
        aria-label="Follow-up schedule changes"
      >
        <div className="lead-timeline-change-row">
          <span>Previous follow-up</span>
          <p>{formatDateTimeValue(details.old_next_action_at)}</p>
        </div>

        <div className="lead-timeline-change-row">
          <span>Updated follow-up</span>
          <p>{formatDateTimeValue(details.new_next_action_at)}</p>
        </div>
      </div>
    );
  }

  return null;
}

export default function LeadTimeline({
  leadId,
  contactName,
  onClose,
}: LeadTimelineProps) {
  const [activities, setActivities] = useState<LeadActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadTimeline = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const result = await activityApi.listForLead(leadId);
      setActivities(sortActivities(result.items));
    } catch (loadError) {
      setError(getErrorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    let cancelled = false;

    async function fetchTimeline() {
      setLoading(true);
      setError("");
      setActivities([]);

      try {
        const result = await activityApi.listForLead(leadId);

        if (!cancelled) {
          setActivities(sortActivities(result.items));
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(getErrorMessage(loadError));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void fetchTimeline();

    return () => {
      cancelled = true;
    };
  }, [leadId]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  return createPortal(
    <div
      className="lead-timeline-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        className="lead-timeline-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="lead-timeline-title"
      >
        <header className="leads-modal-header">
          <div>
            <span className="leads-eyebrow">LEAD ACTIVITY</span>
            <h2 id="lead-timeline-title">{contactName}</h2>
            <p>
              Review interactions, changes, and site visits recorded for this
              lead.
            </p>
          </div>

          <button
            className="leads-modal-close"
            type="button"
            onClick={onClose}
            aria-label="Close lead timeline"
          >
            ×
          </button>
        </header>

        <div className="lead-timeline-body leads-form-body">
          {loading ? (
            <div
              className="lead-timeline-state"
              role="status"
              aria-live="polite"
            >
              <span className="leads-spinner" aria-hidden="true" />
              <p>Loading activity history…</p>
            </div>
          ) : error ? (
            <div className="lead-timeline-state" role="alert">
              <p>{error}</p>

              <button
                className="leads-secondary-button"
                type="button"
                onClick={() => void loadTimeline()}
              >
                Try again
              </button>
            </div>
          ) : activities.length === 0 ? (
            <div className="lead-timeline-state">
              <div className="lead-timeline-empty-icon" aria-hidden="true">
                ◷
              </div>

              <h3>No activity recorded yet</h3>

              <p>
                Activities and changes will appear here when they are recorded
                for this lead.
              </p>
            </div>
          ) : (
            <ol className="lead-timeline-list">
              {activities.map((activity) => (
                <li className="lead-timeline-item" key={activity.id}>
                  <span
                    className="lead-timeline-marker"
                    aria-hidden="true"
                  />

                  <article className="lead-timeline-card">
                    <div className="lead-timeline-card-top">
                      <span className="lead-timeline-type">
                        {formatActivityType(activity.activity_type)}
                      </span>

                      <time dateTime={activity.occurred_at}>
                        {formatTimestamp(activity.occurred_at)}
                      </time>
                    </div>

                    <h3>{activity.title}</h3>

                    {activity.description && (
                      <p className="lead-timeline-description">
                        {activity.description}
                      </p>
                    )}

                    <ActivityChangeDetails activity={activity} />

                    <p className="lead-timeline-actor">
                      Performed by{" "}
                      <span>
                        {activity.actor_display_name?.trim() || "Unknown user"}
                      </span>
                    </p>
                  </article>
                </li>
              ))}
            </ol>
          )}

          <div className="lead-timeline-visits">
            <SiteVisitHistory
              leadId={leadId}
              title="Lead site-visit history"
            />
          </div>
        </div>

        <footer className="leads-form-actions lead-timeline-footer">
          <p>Activity and site-visit history</p>

          <button
            className="leads-secondary-button"
            type="button"
            onClick={onClose}
          >
            Close
          </button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}


import { useEffect, useState } from "react";
import {
  siteVisitsApi,
  type SiteVisit,
  type SiteVisitStatus,
} from "../services/siteVisitApi";
import "./SiteVisitHistory.css";

interface SiteVisitHistoryProps {
  leadId?: string;
  customerProfileId?: string;
  propertyId?: string;
  title?: string;
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "Date unavailable";
  }

  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function statusLabel(status: SiteVisitStatus): string {
  return status
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

function outcomeLabel(value: string | null): string {
  if (!value) return "Not recorded";

  return value
    .split("_")
    .map((part) => part.charAt(0) + part.slice(1).toLowerCase())
    .join(" ");
}

export default function SiteVisitHistory({
  leadId,
  customerProfileId,
  propertyId,
  title = "Site visit history",
}: SiteVisitHistoryProps) {
  const [visits, setVisits] = useState<SiteVisit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadVisits() {
      setLoading(true);
      setError("");

      try {
        const result = await siteVisitsApi.list({
          page: 1,
          page_size: 100,
          ...(leadId ? { lead_id: leadId } : {}),
          ...(customerProfileId
            ? { customer_profile_id: customerProfileId }
            : {}),
          ...(propertyId ? { property_id: propertyId } : {}),
        });

        if (!cancelled) {
          setVisits(result.items);
        }
      } catch {
        if (!cancelled) {
          setError("Unable to load visit history. Please try again.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadVisits();

    return () => {
      cancelled = true;
    };
  }, [leadId, customerProfileId, propertyId]);

  const now = Date.now();

  const upcomingVisits = visits
    .filter(
      (visit) =>
        visit.status === "SCHEDULED" &&
        new Date(visit.scheduled_at).getTime() >= now,
    )
    .sort(
      (a, b) =>
        new Date(a.scheduled_at).getTime() -
        new Date(b.scheduled_at).getTime(),
    );

  const pastVisits = visits
    .filter(
      (visit) =>
        visit.status !== "SCHEDULED" ||
        new Date(visit.scheduled_at).getTime() < now,
    )
    .sort(
      (a, b) =>
        new Date(b.scheduled_at).getTime() -
        new Date(a.scheduled_at).getTime(),
    );

  function renderVisit(visit: SiteVisit) {
    return (
      <article className="site-visit-history-card" key={visit.id}>
        <div className="site-visit-history-card-top">
          <div>
            <p className="site-visit-history-date">
              {formatDate(visit.scheduled_at)}
            </p>
            <span
              className={`site-visit-history-status status-${visit.status.toLowerCase()}`}
            >
              {statusLabel(visit.status)}
            </span>
          </div>
          {visit.has_follow_up && (
            <span className="site-visit-history-follow-up">
              Follow-up created
            </span>
          )}
        </div>

        {visit.ends_at && (
          <p className="site-visit-history-detail">
            <strong>Ends:</strong> {formatDate(visit.ends_at)}
          </p>
        )}

        <p className="site-visit-history-detail">
          <strong>Outcome:</strong> {outcomeLabel(visit.outcome)}
        </p>

        {visit.notes && (
          <p className="site-visit-history-detail">
            <strong>Notes:</strong> {visit.notes}
          </p>
        )}

        {visit.feedback && (
          <p className="site-visit-history-detail">
            <strong>Feedback:</strong> {visit.feedback}
          </p>
        )}
      </article>
    );
  }

  function renderSection(
    sectionTitle: string,
    sectionVisits: SiteVisit[],
    emptyMessage: string,
  ) {
    return (
      <section className="site-visit-history-section">
        <div className="site-visit-history-section-heading">
          <h3>{sectionTitle}</h3>
          <span>{sectionVisits.length}</span>
        </div>

        {sectionVisits.length === 0 ? (
          <p className="site-visit-history-empty">{emptyMessage}</p>
        ) : (
          <div className="site-visit-history-list">
            {sectionVisits.map(renderVisit)}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="site-visit-history" aria-label={title}>
      <header className="site-visit-history-header">
        <div>
          <p className="site-visit-history-eyebrow">VISITS & FOLLOW-UPS</p>
          <h2>{title}</h2>
        </div>
        <span className="site-visit-history-total">
          {visits.length} {visits.length === 1 ? "visit" : "visits"}
        </span>
      </header>

      {loading ? (
        <p className="site-visit-history-state" role="status">
          Loading visit history…
        </p>
      ) : error ? (
        <p className="site-visit-history-error" role="alert">
          {error}
        </p>
      ) : (
        <>
          {renderSection(
            "Upcoming visits",
            upcomingVisits,
            "No upcoming visits scheduled.",
          )}
          {renderSection(
            "Past visits",
            pastVisits,
            "No past visits recorded.",
          )}
        </>
      )}
    </section>
  );
}

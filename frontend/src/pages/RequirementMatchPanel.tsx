import { useCallback, useEffect, useState } from "react";

import { ApiError } from "../lib/api";
import {
  matchEvaluationApi,
  type MatchEvaluation,
  type MatchEvaluationResult,
  type NextBestAction,
  type TransactionType,
} from "../services/matchEvaluationApi";

interface RequirementMatchPanelProps {
  requirementId: string;
  transactionType: TransactionType | null | undefined;
}

const TRANSACTION_OPTIONS: Array<{ value: TransactionType | ""; label: string }> = [
  { value: "", label: "Not recorded" },
  { value: "SALE", label: "Buy (sale)" },
  { value: "RENT", label: "Rent" },
  { value: "LEASE", label: "Lease" },
];

const ELIGIBILITY_LABEL: Record<MatchEvaluationResult["eligibility"], string> = {
  eligible: "Eligible",
  excluded: "Excluded",
  insufficient_data: "Cannot be checked: data missing",
};

const CATEGORY_LABEL: Record<string, string> = {
  request_missing_information: "Request missing requirement details",
  review_property: "Review a potentially suitable property",
  arrange_site_visit: "Arrange a site visit",
  follow_up_lead: "Follow up with the lead",
  escalate_to_human: "Decide with a person",
};

const BASIS_LABEL: Record<NextBestAction["basis"], string> = {
  verified_fact: "Verified CRM fact",
  deterministic_match: "Deterministic matching finding",
  missing_information: "Missing information",
  ai_suggestion: "AI-generated suggestion",
};

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.details as { detail?: { reason?: string; problems?: string[] } | string } | undefined;
    const inner = detail?.detail;
    if (inner && typeof inner === "object") {
      const problems = inner.problems?.length ? ` ${inner.problems.join(" ")}` : "";
      return `${inner.reason ?? "The request was refused."}${problems}`;
    }
    if (typeof inner === "string") {
      return inner;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

function propertyTitle(result: MatchEvaluationResult): string {
  const { bhk, property_type: type, locality, city } = result.property;
  return [bhk ? `${bhk} BHK` : null, type, locality, city].filter(Boolean).join(", ") || "Property";
}

export default function RequirementMatchPanel({ requirementId, transactionType }: RequirementMatchPanelProps) {
  const [currentType, setCurrentType] = useState<TransactionType | null>(transactionType ?? null);
  const [evaluation, setEvaluation] = useState<MatchEvaluation | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setEvaluation(await matchEvaluationApi.latest(requirementId));
      setError(null);
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setLoaded(true);
    }
  }, [requirementId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      await load();
    } catch (caught) {
      setError(messageFor(caught));
    } finally {
      setBusy(false);
    }
  }

  async function changeTransactionType(value: string) {
    const next = value === "" ? null : (value as TransactionType);
    await run(async () => {
      await matchEvaluationApi.setTransactionType(requirementId, next);
      setCurrentType(next);
    }, "Transaction type saved. Evaluate again to apply it.");
  }

  const stale = evaluation?.stale ?? false;
  const eligible = (evaluation?.results ?? []).filter((item) => item.eligibility === "eligible");
  const others = (evaluation?.results ?? []).filter((item) => item.eligibility !== "eligible");

  return (
    <section className="requirements-card" aria-labelledby={`match-panel-${requirementId}`}>
      <h3 id={`match-panel-${requirementId}`}>Matching and next actions</h3>
      <p className="requirements-form-hint">
        Rule-based matching against recorded requirement and inventory facts. Eligibility is decided by the rules. Rank orders the
        eligible properties. Neither is a probability.
      </p>

      {error ? <p role="alert">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}

      <label>
        What the customer wants
        <select
          value={currentType ?? ""}
          disabled={busy}
          onChange={(event) => void changeTransactionType(event.target.value)}
        >
          {TRANSACTION_OPTIONS.map((option) => (
            <option key={option.value || "none"} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <div className="requirements-card-actions">
        <button className="requirements-primary-button" type="button" disabled={busy} onClick={() =>
          void run(() => matchEvaluationApi.evaluate(requirementId), "Matching evaluated.")}>
          {evaluation ? "Evaluate again" : "Evaluate matches"}
        </button>
      </div>

      {!loaded ? <p>Loading matches…</p> : null}
      {loaded && !evaluation ? <p>No evaluation has been run for this requirement yet.</p> : null}

      {evaluation ? (
        <>
          {stale ? (
            <p role="status">
              The requirement or the available inventory changed after this evaluation. Its results and recommendations are shown
              as stale and cannot be decided. Evaluate again.
            </p>
          ) : (
            <p>
              Evaluated {evaluation.evaluated_at ? new Date(evaluation.evaluated_at).toLocaleString() : "at an unknown time"} using
              rules {evaluation.ruleset_version ?? "unknown"}. {evaluation.eligible_count} of {evaluation.total_candidates} available
              properties are eligible.
            </p>
          )}

          <h4>Ranked eligible properties</h4>
          {eligible.length === 0 ? <p>No eligible property.</p> : (
            <ol>
              {eligible.map((result) => (
                <li key={result.property_id}>
                  <strong>{propertyTitle(result)}</strong> ({ELIGIBILITY_LABEL[result.eligibility]}, rank {result.rank})
                  <ul>
                    {result.matched_factors.map((factor) => (
                      <li key={factor.criterion}>Matched: {factor.explanation}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          )}

          {others.length > 0 ? (
            <>
              <h4>Not eligible or not checkable</h4>
              <ul>
                {others.map((result) => (
                  <li key={result.property_id}>
                    <strong>{propertyTitle(result)}</strong>: {ELIGIBILITY_LABEL[result.eligibility]}
                    <ul>
                      {result.exclusion_reasons.map((reason) => (
                        <li key={reason}>Excluded: {reason}</li>
                      ))}
                      {result.missing_information.map((item) => (
                        <li key={item.criterion}>Missing: {item.explanation}</li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          <h4>Next actions</h4>
          {evaluation.recommendations.length === 0 ? <p>No recommendation for this evaluation.</p> : (
            <ul>
              {evaluation.recommendations.map((item) => (
                <li key={item.id}>
                  <p>
                    <strong>{CATEGORY_LABEL[item.category] ?? item.category}</strong>
                    {" "}
                    <span>{BASIS_LABEL[item.basis]}</span>
                    {item.stale ? <span> · stale</span> : null}
                    {" "}· status {item.status}
                  </p>
                  <p>{item.summary}</p>
                  {item.status === "open" || item.status === "accepted" ? (
                    <div>
                      <label>
                        Reason (optional)
                        <input
                          value={reasons[item.id] ?? ""}
                          maxLength={500}
                          onChange={(event) => setReasons({ ...reasons, [item.id]: event.target.value })}
                        />
                      </label>
                      {item.status === "open" ? (
                        <button type="button" disabled={busy || stale}
                          onClick={() => void run(() => matchEvaluationApi.decide(item.id, "accepted", reasons[item.id]), "Recommendation accepted.")}>
                          Accept
                        </button>
                      ) : (
                        <button type="button" disabled={busy || stale}
                          onClick={() => void run(() => matchEvaluationApi.decide(item.id, "done", reasons[item.id]), "Recommendation marked done.")}>
                          Mark done
                        </button>
                      )}
                      <button type="button" disabled={busy || stale}
                        onClick={() => void run(() => matchEvaluationApi.decide(item.id, "dismissed", reasons[item.id]), "Recommendation dismissed.")}>
                        Dismiss
                      </button>
                    </div>
                  ) : null}
                  {item.history.length > 0 ? (
                    <p>History: {item.history.map((step) => `${step.from} to ${step.to}`).join("; ")}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          <p>{evaluation.disclaimer}</p>
        </>
      ) : null}
    </section>
  );
}

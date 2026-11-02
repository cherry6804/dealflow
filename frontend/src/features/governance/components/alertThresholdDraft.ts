/**
 * Client-side checks for the three AI usage alert thresholds. The server enforces the same rules and
 * is authoritative. These checks let the form explain a problem before a request is sent.
 */

export type ThresholdDraftResult =
  | { ok: true; values: [number, number, number] }
  | { ok: false; error: string };

export const ALERT_THRESHOLD_TOP = 100;

export function parseThresholdDraft(drafts: readonly string[]): ThresholdDraftResult {
  if (drafts.length !== 3) {
    return { ok: false, error: "Enter exactly three alert thresholds." };
  }
  const values: number[] = [];
  for (const draft of drafts) {
    const trimmed = draft.trim();
    if (!/^\d+$/.test(trimmed)) {
      return { ok: false, error: "Each alert threshold must be a whole number." };
    }
    const value = Number(trimmed);
    if (!Number.isSafeInteger(value) || value < 1 || value > ALERT_THRESHOLD_TOP) {
      return { ok: false, error: "Each alert threshold must be from 1 to 100." };
    }
    values.push(value);
  }
  const [low, mid, high] = values as [number, number, number];
  if (!(low < mid && mid < high)) {
    return { ok: false, error: "Alert thresholds must increase, with no duplicates." };
  }
  if (high !== ALERT_THRESHOLD_TOP) {
    return { ok: false, error: "The highest alert threshold must be 100." };
  }
  return { ok: true, values: [low, mid, high] };
}

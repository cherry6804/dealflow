/**
 * Formatting and totals for records nested inside a deal (payment milestones, commissions). Values come only from the API:
 * nothing here calculates a financial figure. Totals add amounts in whole minor units, and a total never hides a missing amount:
 * rows without a value are counted and reported.
 */

export const AMOUNT_UNAVAILABLE = "Not available";

export function formatMoney(amount: string | number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined || amount === "") return AMOUNT_UNAVAILABLE;

  const value = Number(amount);
  if (!Number.isFinite(value)) return AMOUNT_UNAVAILABLE;

  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${currency} ${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
  }
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

export function formatDateOnly(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

export interface CurrencyTotal {
  currency: string;
  /** Sum of the available amounts, in the row currency. */
  total: number;
  /** Rows in this currency whose amount the API did not provide. */
  unavailable: number;
  /** Number of rows that contributed. */
  count: number;
}

interface TotalableRow {
  amount: string | number | null | undefined;
  currency: string;
}

/** Totals grouped by currency, so amounts in different currencies are never added together. */
export function totalsByCurrency(rows: readonly TotalableRow[]): CurrencyTotal[] {
  const groups = new Map<string, { cents: number; unavailable: number; count: number }>();

  for (const row of rows) {
    const group = groups.get(row.currency) ?? { cents: 0, unavailable: 0, count: 0 };
    group.count += 1;
    const value = row.amount === null || row.amount === undefined || row.amount === "" ? Number.NaN : Number(row.amount);
    if (Number.isFinite(value)) group.cents += Math.round(value * 100);
    else group.unavailable += 1;
    groups.set(row.currency, group);
  }

  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([currency, group]) => ({ currency, total: group.cents / 100, unavailable: group.unavailable, count: group.count }));
}

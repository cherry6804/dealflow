import { ApiError } from "../../lib/api";
import type { Contact } from "../../services/contactApi";

export const SALES_PAGE_SIZE = 100;

/** Walks one paginated endpoint and returns every item. The page parameter starts at 1. */
export async function fetchAllPages<T>(fetchPage: (page: number) => Promise<{ items: T[]; total_pages: number }>): Promise<T[]> {
  const first = await fetchPage(1);
  const items = [...first.items];
  for (let page = 2; page <= first.total_pages; page += 1) {
    const next = await fetchPage(page);
    items.push(...next.items);
  }
  return items;
}

export function messageFrom(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export function formatShortDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Not scheduled";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export function personName(person: { first_name: string; last_name: string | null }): string {
  return [person.first_name, person.last_name].filter(Boolean).join(" ").trim();
}

/** Display name for a contact, or a fixed label when the contact is not loaded. */
export function contactDisplayName(contact: Contact | undefined): string {
  return contact ? personName(contact) || "Unnamed contact" : "Contact unavailable";
}

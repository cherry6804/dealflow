/**
 * Personal preference store. Every preference belongs to one user, inside one organization (or to no organization, for
 * interface preferences such as theme). It is saved in this browser only; it is not synchronized across devices.
 *
 * Key format: dealflow:<namespace>:<organizationId or "-">:<userId>[:<part>]
 * The format matches the keys already in use for workspace preferences and grid columns, so saved data keeps working.
 *
 * Rules:
 * - A preference is read and written only under the signed-in user's id. Without a user, nothing is read or written.
 * - A stored value must carry the current schema version and pass the caller's parser. Anything else is ignored and the
 *   caller's default is used, so an outdated or corrupted value never breaks a screen.
 * - Writes replace only the one key they target. Other preferences are not touched.
 * - Storage errors (blocked, full or missing) are reported to the caller through the return value, never thrown.
 */

export const PERSONAL_PREFERENCE_SCHEMA_VERSION = 1;
export const PERSONAL_PREFERENCE_CHANGED_EVENT = "dealflow:personal-preference-changed";

export interface PersonalScope {
  userId: string;
  organizationId: string | null;
}

interface StoredEnvelope {
  v: number;
  data: unknown;
}

/** Builds the storage key for one preference, or null when there is no signed-in user to own it. */
export function personalPreferenceKey(
  namespace: string,
  scope: PersonalScope | null,
  part?: string,
): string | null {
  if (!scope || !scope.userId) return null;
  const organization = scope.organizationId && scope.organizationId.length > 0 ? scope.organizationId : "-";
  const suffix = part ? `:${part}` : "";
  return `dealflow:${namespace}:${organization}:${scope.userId}${suffix}`;
}

function storage(): Storage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

/** Raw stored text for a key, or null. Never throws. */
export function readRawPreference(key: string | null): string | null {
  if (!key) return null;
  try {
    return storage()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export interface ParseOptions {
  /**
   * Accept values saved before the envelope existed (plain JSON objects). Their parser must tolerate missing fields, which
   * the workspace and grid parsers already do. Writes always use the envelope, so legacy values migrate on the next save.
   */
  acceptLegacy?: boolean;
}

/** Parses a stored value. Returns the fallback for missing, invalid, outdated or unparseable values. */
export function parsePersonalPreference<T>(
  raw: string | null,
  parse: (data: unknown) => T | null,
  fallback: T,
  options: ParseOptions = {},
): T {
  if (raw === null) return fallback;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return fallback;
    const envelope = parsed as Partial<StoredEnvelope>;
    if (envelope.v === undefined) {
      return options.acceptLegacy ? (parse(parsed) ?? fallback) : fallback;
    }
    if (envelope.v !== PERSONAL_PREFERENCE_SCHEMA_VERSION) return fallback;
    return parse(envelope.data) ?? fallback;
  } catch {
    return fallback;
  }
}

function notify(key: string) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(PERSONAL_PREFERENCE_CHANGED_EVENT, { detail: { key } }));
}

/** Saves a value under one key. Returns false when the browser refused to store it. */
export function writePersonalPreference<T>(key: string | null, value: T): boolean {
  if (!key) return false;
  try {
    const envelope: StoredEnvelope = { v: PERSONAL_PREFERENCE_SCHEMA_VERSION, data: value };
    storage()?.setItem(key, JSON.stringify(envelope));
    notify(key);
    return true;
  } catch {
    return false;
  }
}

/** Removes one key. Other keys, including other users' keys, are not affected. */
export function removePersonalPreference(key: string | null): void {
  if (!key) return;
  try {
    storage()?.removeItem(key);
  } catch {
    // Nothing to remove if storage is unavailable.
  }
  notify(key);
}

/** Subscribes to changes made in this tab (custom event) and in other tabs (storage event). Returns an unsubscribe. */
export function subscribePersonalPreferences(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const handleStorage = () => onChange();
  window.addEventListener(PERSONAL_PREFERENCE_CHANGED_EVENT, onChange);
  window.addEventListener("storage", handleStorage);
  return () => {
    window.removeEventListener(PERSONAL_PREFERENCE_CHANGED_EVENT, onChange);
    window.removeEventListener("storage", handleStorage);
  };
}

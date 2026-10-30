import { ApiError } from "../../lib/api";
import type { TeamMemberRemovalResponse } from "../../services/teamApi";

/** Message shown while the removal waits for SIBVO to confirm. */
export function removalPendingMessage(name: string): string {
  return `Removing ${name}. Waiting for SIBVO to confirm the seat release.`;
}

/**
 * Message for a confirmed removal. Each branch states what SIBVO confirmed,
 * so the user is never told a seat was released when it was not.
 */
export function removalSuccessMessage(
  name: string,
  result: TeamMemberRemovalResponse,
): string {
  if (result.already_removed) {
    return `${name} was already removed. SIBVO confirmed their seat is released.`;
  }
  switch (result.seat_outcome) {
    case "released":
    case "already_released":
      return `${name} was removed. SIBVO released their Dealsflo seat.`;
    case "not_held":
      return `${name} was removed. SIBVO held no Dealsflo seat for this account.`;
    case "not_linked":
      return `${name} was removed. This account is not linked to SIBVO, so no SIBVO seat was held.`;
  }
}

/**
 * Message for a removal that did not complete. A 503 means SIBVO did not confirm,
 * so the member is still active. The UI must not say they were removed.
 */
export function removalErrorMessage(name: string, error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 503) {
      return `SIBVO did not confirm the removal, so ${name} is still a member. Try again.`;
    }
    if (error.status === 403) {
      return "SIBVO did not authorize this removal. Sign in through SIBVO and try again.";
    }
    if (error.status === 409) {
      return error.message;
    }
  }
  return `${name} was not removed. Please try again.`;
}

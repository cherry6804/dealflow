import { describe, expect, it } from "vitest";
import { ApiError } from "../../lib/api";
import type { TeamMemberRemovalResponse } from "../../services/teamApi";
import {
  removalErrorMessage,
  removalPendingMessage,
  removalSuccessMessage,
} from "./teamRemoval";

function result(
  overrides: Partial<TeamMemberRemovalResponse>,
): TeamMemberRemovalResponse {
  return {
    membership_id: "00000000-0000-0000-0000-000000000001",
    is_active: false,
    seat_outcome: "released",
    already_removed: false,
    message: "",
    ...overrides,
  };
}

describe("removalSuccessMessage", () => {
  it("says SIBVO released the seat only when it did", () => {
    expect(removalSuccessMessage("Asha", result({ seat_outcome: "released" }))).toBe(
      "Asha was removed. SIBVO released their Dealsflo seat.",
    );
    expect(
      removalSuccessMessage("Asha", result({ seat_outcome: "already_released" })),
    ).toBe("Asha was removed. SIBVO released their Dealsflo seat.");
  });

  it("reports a repeat removal as already removed with SIBVO confirmation", () => {
    expect(
      removalSuccessMessage(
        "Asha",
        result({ already_removed: true, seat_outcome: "already_released" }),
      ),
    ).toBe("Asha was already removed. SIBVO confirmed their seat is released.");
  });

  it("explains an account with no SIBVO seat or link", () => {
    expect(removalSuccessMessage("Asha", result({ seat_outcome: "not_held" }))).toBe(
      "Asha was removed. SIBVO held no Dealsflo seat for this account.",
    );
    expect(removalSuccessMessage("Asha", result({ seat_outcome: "not_linked" }))).toBe(
      "Asha was removed. This account is not linked to SIBVO, so no SIBVO seat was held.",
    );
  });
});

describe("removalErrorMessage", () => {
  it("never reports a removal when SIBVO did not confirm it", () => {
    const message = removalErrorMessage("Asha", new ApiError("down", 503));

    expect(message).toBe("SIBVO did not confirm the removal, so Asha is still a member. Try again.");
    expect(message).not.toContain("was removed");
  });

  it("reports a SIBVO refusal as a refusal", () => {
    expect(removalErrorMessage("Asha", new ApiError("no", 403))).toBe(
      "SIBVO did not authorize this removal. Sign in through SIBVO and try again.",
    );
  });

  it("shows the server's reason for a conflict", () => {
    expect(
      removalErrorMessage("Asha", new ApiError("The last active organization owner cannot be removed.", 409)),
    ).toBe("The last active organization owner cannot be removed.");
  });

  it("falls back to a generic failure for anything else", () => {
    expect(removalErrorMessage("Asha", new Error("network"))).toBe(
      "Asha was not removed. Please try again.",
    );
  });
});

describe("removalPendingMessage", () => {
  it("tells the user the removal is waiting on SIBVO", () => {
    expect(removalPendingMessage("Asha")).toBe(
      "Removing Asha. Waiting for SIBVO to confirm the seat release.",
    );
  });
});

import { describe, expect, it } from "vitest";
import { ApiError } from "../../lib/api";
import {
  accessErrorMessage,
  formatEntitlement,
  seatErrorState,
  subscriptionStatusText,
  summarizeSeats,
} from "./billingAccess";

describe("accessErrorMessage", () => {
  it("explains when plan details need a SIBVO sign-in", () => {
    expect(accessErrorMessage(new ApiError("missing", 404))).toBe(
      "Plan details are available after you sign in through SIBVO.",
    );
  });

  it("tells the user access has ended when the session is no longer valid", () => {
    for (const status of [401, 403]) {
      expect(accessErrorMessage(new ApiError("ended", status))).toBe(
        "Your access to Dealsflo has ended. Sign in through SIBVO again to continue.",
      );
    }
  });

  it("falls back to a generic message for other failures", () => {
    expect(accessErrorMessage(new ApiError("boom", 500))).toBe(
      "Plan details could not be loaded. Please try again.",
    );
  });
});

describe("seatErrorState", () => {
  it("treats a SIBVO denial as denied and everything else as unavailable", () => {
    expect(seatErrorState(new ApiError("no", 403))).toBe("denied");
    expect(seatErrorState(new ApiError("down", 503))).toBe("unavailable");
    expect(seatErrorState(new Error("network"))).toBe("unavailable");
  });
});

describe("summarizeSeats", () => {
  it("reports capacity exactly as SIBVO returned it", () => {
    expect(
      summarizeSeats({
        seat_limit: 5,
        allocated: 3,
        reserved: 1,
        available: 1,
        unlimited: false,
      }),
    ).toEqual({
      inUse: 3,
      pending: 1,
      limitLabel: "5",
      availableLabel: "1",
      atLimit: false,
    });
  });

  it("flags the limit when no seat is available", () => {
    const summary = summarizeSeats({
      seat_limit: 2,
      allocated: 1,
      reserved: 1,
      available: 0,
      unlimited: false,
    });
    expect(summary.atLimit).toBe(true);
  });

  it("never reports a limit for an unlimited plan", () => {
    const summary = summarizeSeats({
      seat_limit: null,
      allocated: 9,
      reserved: 0,
      available: null,
      unlimited: true,
    });
    expect(summary.limitLabel).toBe("Unlimited");
    expect(summary.availableLabel).toBe("Unlimited");
    expect(summary.atLimit).toBe(false);
  });
});

describe("display helpers", () => {
  it("maps known subscription statuses and passes unknown ones through", () => {
    expect(subscriptionStatusText("trialing")).toBe("Free trial");
    expect(subscriptionStatusText("some_new_state")).toBe("some_new_state");
    expect(subscriptionStatusText(null)).toBe("Unknown");
  });

  it("formats an entitlement with its limit only when SIBVO sets one", () => {
    expect(
      formatEntitlement({
        feature_key: "workflow_automation",
        enabled: true,
        limit_value: null,
        limit_unit: null,
      }),
    ).toBe("workflow automation");
    expect(
      formatEntitlement({
        feature_key: "workflow_automation",
        enabled: true,
        limit_value: 10,
        limit_unit: "runs",
      }),
    ).toBe("workflow automation (SIBVO limit 10 runs; not enforced in Dealsflo)");
  });
});

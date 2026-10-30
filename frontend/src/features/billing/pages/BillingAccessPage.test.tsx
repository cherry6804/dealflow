import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../../../lib/api";
import BillingAccessPage from "./BillingAccessPage";

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api")>();
  return {
    ...actual,
    api: { get: vi.fn() },
  };
});

const get = vi.mocked(api.get);

const ownerAccess = {
  subscription_status: "active",
  plan_version_id: "00000000-0000-0000-0000-000000000001",
  product_role: "owner",
  entitlements: [
    { feature_key: "workflow_automation", enabled: true, limit_value: null, limit_unit: null },
  ],
};

const memberAccess = { ...ownerAccess, product_role: "member" };

/** Routes each API path to a response; a Error value simulates a failure. */
function respond(routes: Record<string, unknown>) {
  get.mockImplementation((path: string) => {
    const route = routes[path];
    if (route instanceof Error) {
      return Promise.reject(route);
    }
    return Promise.resolve(route);
  });
}

describe("BillingAccessPage", () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("shows seat capacity from SIBVO to a product owner", async () => {
    respond({
      "/auth/sibvo-access": ownerAccess,
      "/auth/sibvo-seats": {
        seat_limit: 5,
        allocated: 3,
        reserved: 1,
        available: 1,
        unlimited: false,
      },
    });

    render(<BillingAccessPage />);

    expect(await screen.findByText("Seats in use")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText("Pending invitations")).toBeTruthy();
    expect(screen.getByText("Seat limit")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/auth/sibvo-seats");
  });

  it("tells the user when every seat is in use and points to SIBVO", async () => {
    respond({
      "/auth/sibvo-access": ownerAccess,
      "/auth/sibvo-seats": {
        seat_limit: 2,
        allocated: 2,
        reserved: 0,
        available: 0,
        unlimited: false,
      },
    });

    render(<BillingAccessPage />);

    expect(
      await screen.findByText(/All seats are in use\. Upgrade your plan in SIBVO/),
    ).toBeTruthy();
  });

  it("shows unlimited seats without a numeric limit", async () => {
    respond({
      "/auth/sibvo-access": ownerAccess,
      "/auth/sibvo-seats": {
        seat_limit: null,
        allocated: 7,
        reserved: 0,
        available: null,
        unlimited: true,
      },
    });

    render(<BillingAccessPage />);

    expect(await screen.findByText("Seats in use")).toBeTruthy();
    expect(screen.getAllByText("Unlimited")).toHaveLength(2);
  });

  it("does not request seat capacity for a member", async () => {
    respond({ "/auth/sibvo-access": memberAccess });

    render(<BillingAccessPage />);

    expect(
      await screen.findByText("Seat capacity is shown to product owners."),
    ).toBeTruthy();
    expect(get).not.toHaveBeenCalledWith("/auth/sibvo-seats");
  });

  it("reports when SIBVO denies seat details for this session", async () => {
    respond({
      "/auth/sibvo-access": ownerAccess,
      "/auth/sibvo-seats": new ApiError("denied", 403),
    });

    render(<BillingAccessPage />);

    expect(
      await screen.findByText("Seat details are not available for this session."),
    ).toBeTruthy();
  });

  it("reports an outage instead of showing stale or invented numbers", async () => {
    respond({
      "/auth/sibvo-access": ownerAccess,
      "/auth/sibvo-seats": new ApiError("down", 503),
    });

    render(<BillingAccessPage />);

    expect(
      await screen.findByText(
        "Seat information is temporarily unavailable. Refresh the page to try again.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText("Seats in use")).toBeNull();
  });

  it("tells the user their access has ended when the session is no longer valid", async () => {
    respond({ "/auth/sibvo-access": new ApiError("ended", 401) });

    render(<BillingAccessPage />);

    expect(
      await screen.findByText(
        "Your access to Dealsflo has ended. Sign in through SIBVO again to continue.",
      ),
    ).toBeTruthy();
  });
});

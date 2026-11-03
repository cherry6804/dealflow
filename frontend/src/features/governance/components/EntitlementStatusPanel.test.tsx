import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { governanceApi, type EntitlementStatus } from "../../../services/governanceApi";
import EntitlementStatusPanel from "./EntitlementStatusPanel";

vi.mock("../../../services/governanceApi", () => ({
  governanceApi: {
    getEntitlementStatus: vi.fn(),
  },
}));

const BASE: EntitlementStatus = {
  state: "valid",
  product_key: "dealsflo",
  revalidation_interval_seconds: 30,
  fetched_at: "2026-11-03T10:00:00Z",
  expires_at: "2026-11-03T10:00:30Z",
  failure_count: 0,
  next_refresh_attempt_at: null,
  backoff_active: false,
  signing_key_configured: true,
};

describe("EntitlementStatusPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("shows a loading state while the status is fetched", () => {
    vi.mocked(governanceApi.getEntitlementStatus).mockReturnValue(new Promise(() => {}));

    render(<EntitlementStatusPanel />);

    expect(screen.getByRole("status").textContent).toContain("Checking plan verification");
  });

  it("states that a verified plan is usable, and that AI still needs its own checks", async () => {
    vi.mocked(governanceApi.getEntitlementStatus).mockResolvedValue(BASE);

    render(<EntitlementStatusPanel />);

    expect(await screen.findByText("Verified.")).toBeTruthy();
    expect(screen.getByText("Every 30 seconds while SIBVO is reachable")).toBeTruthy();
    expect(screen.getByText("Configured")).toBeTruthy();
    expect(screen.getByText(/necessary but not sufficient/)).toBeTruthy();
  });

  it("says AI stays off when the plan has expired", async () => {
    vi.mocked(governanceApi.getEntitlementStatus).mockResolvedValue({ ...BASE, state: "expired" });

    render(<EntitlementStatusPanel />);

    expect(await screen.findByText("Expired.")).toBeTruthy();
    expect(screen.getByText(/AI stays off until SIBVO verifies the plan again/)).toBeTruthy();
  });

  it("says AI stays off when the plan has never been verified", async () => {
    vi.mocked(governanceApi.getEntitlementStatus).mockResolvedValue({
      ...BASE,
      state: "missing",
      fetched_at: null,
      expires_at: null,
    });

    render(<EntitlementStatusPanel />);

    expect(await screen.findByText("Not verified.")).toBeTruthy();
    expect(screen.getAllByText("Never").length).toBeGreaterThan(0);
  });

  it("flags a missing signing key as a plain status, without any key material", async () => {
    vi.mocked(governanceApi.getEntitlementStatus).mockResolvedValue({
      ...BASE,
      state: "missing",
      signing_key_configured: false,
    });

    render(<EntitlementStatusPanel />);

    expect(await screen.findByText("Not configured. AI stays off.")).toBeTruthy();
  });

  it("explains that retries are paused and do not extend validity after a failed refresh", async () => {
    vi.mocked(governanceApi.getEntitlementStatus).mockResolvedValue({
      ...BASE,
      state: "due_for_revalidation",
      backoff_active: true,
      next_refresh_attempt_at: "2026-11-03T10:00:25Z",
      failure_count: 2,
    });

    render(<EntitlementStatusPanel />);

    expect(await screen.findByText(/Retries are paused until/)).toBeTruthy();
    expect(screen.getByText(/never extends the plan's validity/)).toBeTruthy();
  });

  it("shows a clear error when the status cannot be loaded", async () => {
    vi.mocked(governanceApi.getEntitlementStatus).mockRejectedValue(new Error("Network unavailable."));

    render(<EntitlementStatusPanel />);

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Network unavailable."));
  });

  it("falls back to a generic message when the error has no text", async () => {
    vi.mocked(governanceApi.getEntitlementStatus).mockRejectedValue("nope");

    render(<EntitlementStatusPanel />);

    expect((await screen.findByRole("alert")).textContent).toContain("Plan verification status could not be loaded.");
  });
});

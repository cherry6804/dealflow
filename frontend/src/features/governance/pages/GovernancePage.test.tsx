import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { governanceApi, type CapabilityState, type GovernanceAccess } from "../../../services/governanceApi";
import GovernancePage from "./GovernancePage";

vi.mock("../../../services/governanceApi", () => ({
  governanceApi: {
    getAccess: vi.fn(),
    listCapabilities: vi.fn(),
    setCapability: vi.fn(),
  },
}));

const NO_ACCESS: GovernanceAccess = {
  capabilities_read: false,
  capabilities_manage: false,
  usage_read: false,
  budgets_manage: false,
  privacy_read: false,
  privacy_manage: false,
};

const AUTOMATION_OFF: CapabilityState = {
  capability_key: "automation.master",
  category: "master",
  parent_key: null,
  is_enabled: false,
  policy_version: 0,
  updated_at: null,
  effective: {
    allowed: false,
    reason_code: "capability_disabled",
    explanation: "This capability is turned off for the organization.",
    policy_version: 0,
  },
};

describe("GovernancePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("explains when the caller has no governance permission", async () => {
    vi.mocked(governanceApi.getAccess).mockResolvedValue(NO_ACCESS);

    render(<GovernancePage />);

    expect(await screen.findByText(/do not have permission to view governance settings/i)).toBeTruthy();
    expect(screen.queryByRole("tablist")).toBeNull();
  });

  it("shows capabilities as off by default with the reason each one cannot run", async () => {
    vi.mocked(governanceApi.getAccess).mockResolvedValue({ ...NO_ACCESS, capabilities_read: true });
    vi.mocked(governanceApi.listCapabilities).mockResolvedValue({ items: [AUTOMATION_OFF] });

    render(<GovernancePage />);

    expect(await screen.findByText("Automation (master switch)")).toBeTruthy();
    expect(screen.getByText("Turned off")).toBeTruthy();
    expect(screen.getByText(/turned off for the organization/i)).toBeTruthy();
    // Read-only callers see the state, not a switch.
    expect(screen.queryByRole("button", { name: /Automation \(master switch\): off\. Change/ })).toBeNull();
  });

  it("asks for confirmation before turning a capability on", async () => {
    vi.mocked(governanceApi.getAccess).mockResolvedValue({
      ...NO_ACCESS,
      capabilities_read: true,
      capabilities_manage: true,
    });
    vi.mocked(governanceApi.listCapabilities).mockResolvedValue({ items: [AUTOMATION_OFF] });
    vi.mocked(governanceApi.setCapability).mockResolvedValue({ ...AUTOMATION_OFF, is_enabled: true });

    render(<GovernancePage />);
    const toggle = await screen.findByRole("button", {
      name: "Automation (master switch): off. Change",
    });

    fireEvent.click(toggle);
    const dialog = await screen.findByRole("dialog");
    expect(governanceApi.setCapability).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Turn on" }));

    await waitFor(() => {
      expect(governanceApi.setCapability).toHaveBeenCalledWith("automation.master", true);
    });
  });

  it("cancelling the confirmation changes nothing", async () => {
    vi.mocked(governanceApi.getAccess).mockResolvedValue({
      ...NO_ACCESS,
      capabilities_read: true,
      capabilities_manage: true,
    });
    vi.mocked(governanceApi.listCapabilities).mockResolvedValue({ items: [AUTOMATION_OFF] });

    render(<GovernancePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Automation (master switch): off. Change" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(governanceApi.setCapability).not.toHaveBeenCalled();
  });
});

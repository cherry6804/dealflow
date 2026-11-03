import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { governanceApi, type AlertThresholds } from "../../../services/governanceApi";
import AlertThresholdsPanel from "./AlertThresholdsPanel";

vi.mock("../../../services/governanceApi", () => ({
  governanceApi: {
    getAlertThresholds: vi.fn(),
    setAlertThresholds: vi.fn(),
  },
}));

const DEFAULTS: AlertThresholds = {
  thresholds: [70, 85, 100],
  is_default: true,
  version: 0,
  updated_at: null,
};

const CUSTOM: AlertThresholds = {
  thresholds: [50, 80, 100],
  is_default: false,
  version: 2,
  updated_at: "2026-10-15T12:00:00Z",
};

function section() {
  return screen.getByRole("region", { name: "Usage alert thresholds" });
}

describe("AlertThresholdsPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("shows the default thresholds and says alerts are in-app notifications", async () => {
    vi.mocked(governanceApi.getAlertThresholds).mockResolvedValue(DEFAULTS);

    render(<AlertThresholdsPanel canManage={false} />);

    await waitFor(() => expect(section().textContent).toContain("70%, 85% and 100%"));
    expect(section().textContent).toContain("in-app notification");
    expect(section().textContent).toContain("No email or other message is sent.");
    expect(section().textContent).toContain("default thresholds");
  });

  it("shows a stored custom set without the default note", async () => {
    vi.mocked(governanceApi.getAlertThresholds).mockResolvedValue(CUSTOM);

    render(<AlertThresholdsPanel canManage={false} />);

    await waitFor(() => expect(section().textContent).toContain("50%, 80% and 100%"));
    expect(section().textContent).not.toContain("default thresholds");
  });

  it("hides the change control from users who cannot manage budgets", async () => {
    vi.mocked(governanceApi.getAlertThresholds).mockResolvedValue(DEFAULTS);

    render(<AlertThresholdsPanel canManage={false} />);

    await waitFor(() => expect(section().textContent).toContain("70%"));
    expect(screen.queryByRole("button", { name: "Change alert thresholds" })).toBeNull();
  });

  it("saves a valid change and reloads the stored values", async () => {
    vi.mocked(governanceApi.getAlertThresholds)
      .mockResolvedValueOnce(DEFAULTS)
      .mockResolvedValueOnce(CUSTOM);
    vi.mocked(governanceApi.setAlertThresholds).mockResolvedValue(CUSTOM);

    render(<AlertThresholdsPanel canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Change alert thresholds" }));

    fireEvent.change(screen.getByLabelText(/First alert/), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText(/Second alert/), { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: "Save thresholds" }));

    await waitFor(() => expect(governanceApi.setAlertThresholds).toHaveBeenCalledWith([50, 80, 100]));
    await waitFor(() => expect(governanceApi.getAlertThresholds).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(section().textContent).toContain("50%, 80% and 100%"));
  });

  it("explains an invalid draft and sends nothing", async () => {
    vi.mocked(governanceApi.getAlertThresholds).mockResolvedValue(DEFAULTS);

    render(<AlertThresholdsPanel canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Change alert thresholds" }));

    fireEvent.change(screen.getByLabelText(/First alert/), { target: { value: "90" } });
    fireEvent.click(screen.getByRole("button", { name: "Save thresholds" }));

    const dialog = screen.getByRole("dialog", { name: "Change usage alert thresholds" });
    expect(within(dialog).getByRole("alert").textContent).toBe(
      "Alert thresholds must increase, with no duplicates.",
    );
    expect(governanceApi.setAlertThresholds).not.toHaveBeenCalled();
  });

  it("shows the server's message when a change is refused", async () => {
    vi.mocked(governanceApi.getAlertThresholds).mockResolvedValue(DEFAULTS);
    vi.mocked(governanceApi.setAlertThresholds).mockRejectedValue(
      new Error("The highest alert threshold must be 100."),
    );

    render(<AlertThresholdsPanel canManage />);
    fireEvent.click(await screen.findByRole("button", { name: "Change alert thresholds" }));
    fireEvent.click(screen.getByRole("button", { name: "Save thresholds" }));

    await waitFor(() =>
      expect(
        within(screen.getByRole("dialog")).getByRole("alert").textContent,
      ).toBe("The highest alert threshold must be 100."),
    );
  });

  it("shows a load error instead of a blank panel", async () => {
    vi.mocked(governanceApi.getAlertThresholds).mockRejectedValue(new Error("Service unavailable."));

    render(<AlertThresholdsPanel canManage={false} />);

    expect((await screen.findByRole("alert")).textContent).toBe("Service unavailable.");
  });
});

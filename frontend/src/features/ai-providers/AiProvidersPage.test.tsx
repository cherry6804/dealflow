import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  providerConnectionApi,
  type ProviderConnection,
  type ProviderConnectionList,
} from "../../services/providerConnectionApi";
import AiProvidersPage, { readinessText } from "./AiProvidersPage";

vi.mock("../../services/providerConnectionApi", () => ({
  providerConnectionApi: {
    listProviders: vi.fn(),
    listConnections: vi.fn(),
    createConnection: vi.fn(),
    verifyConnection: vi.fn(),
    rotateConnection: vi.fn(),
    disconnectConnection: vi.fn(),
    listAttempts: vi.fn(),
  },
}));

const OPENAI = {
  key: "openai",
  display_name: "OpenAI",
  category: "llm",
  declared_operations: ["text_generation", "embeddings"],
  adapter_implemented: true,
  executable: false,
};

function connection(overrides: Partial<ProviderConnection> = {}): ProviderConnection {
  return {
    id: "conn-1",
    provider_key: "openai",
    label: "Primary",
    status: "unverified",
    status_reason_code: "live_adapter_disabled",
    ready: false,
    readiness_code: "not_verified",
    credential_version: 1,
    verified_credential_version: null,
    last_verified_at: null,
    last_attempt_at: null,
    consecutive_failures: 0,
    next_verification_at: null,
    created_at: "2026-11-02T10:00:00Z",
    updated_at: "2026-11-02T10:00:00Z",
    ...overrides,
  };
}

function listing(items: ProviderConnection[], canManage: boolean): ProviderConnectionList {
  return { items, can_manage: canManage };
}

describe("readinessText", () => {
  it("describes only a ready connection as usable", () => {
    expect(readinessText(connection({ ready: true, readiness_code: "ready" }))).toMatch(/Verified and ready/);
  });

  it("never describes a non-ready connection as verified or connected", () => {
    for (const code of [
      "verifying",
      "not_verified",
      "degraded",
      "failed",
      "credential_changed",
      "credential_revoked",
      "stale",
      "not_connected",
      "disconnected",
    ] as const) {
      const text = readinessText(connection({ readiness_code: code, ready: false }));
      expect(text).not.toMatch(/Verified and ready/);
      expect(text).not.toMatch(/^Connected/);
    }
  });

  it("says live access is disabled when that is the reason", () => {
    expect(readinessText(connection())).toMatch(/Live provider access is disabled/);
  });
});

describe("AiProvidersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(providerConnectionApi.listProviders).mockResolvedValue({ items: [OPENAI] });
    vi.mocked(providerConnectionApi.listAttempts).mockResolvedValue({ items: [] });
  });

  it("shows a not-ready connection as not ready, even with a live adapter disabled", async () => {
    vi.mocked(providerConnectionApi.listConnections).mockResolvedValue(listing([connection()], true));

    render(<AiProvidersPage />);

    expect(await screen.findByText("Primary (openai)")).toBeTruthy();
    expect(screen.getByText("Not ready")).toBeTruthy();
    expect(screen.queryByText("Ready")).toBeNull();
  });

  it("states that saving a key does not connect the provider", async () => {
    vi.mocked(providerConnectionApi.listConnections).mockResolvedValue(listing([], true));

    render(<AiProvidersPage />);

    expect(await screen.findByText(/Saving a key does not connect the provider/)).toBeTruthy();
    expect(screen.getByText("No provider is connected.")).toBeTruthy();
  });

  it("hides every change control from callers who cannot manage connections", async () => {
    vi.mocked(providerConnectionApi.listConnections).mockResolvedValue(listing([connection()], false));

    render(<AiProvidersPage />);

    await screen.findByText("Primary (openai)");
    expect(screen.queryByRole("button", { name: "Verify now" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull();
    expect(screen.queryByLabelText("API key")).toBeNull();
    expect(screen.getByText(/Only the organization owner can add, replace or disconnect/)).toBeTruthy();
  });

  it("uses a password field for the key and clears it after it is sent", async () => {
    vi.mocked(providerConnectionApi.listConnections).mockResolvedValue(listing([], true));
    vi.mocked(providerConnectionApi.createConnection).mockResolvedValue(connection());

    render(<AiProvidersPage />);

    const key = await screen.findByLabelText("API key");
    expect(key.getAttribute("type")).toBe("password");
    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "Primary" } });
    fireEvent.change(key, { target: { value: "sk-ui-test-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save connection" }));

    await waitFor(() =>
      expect(providerConnectionApi.createConnection).toHaveBeenCalledWith("openai", "Primary", "sk-ui-test-value"),
    );
    await waitFor(() => expect((screen.getByLabelText("API key") as HTMLInputElement).value).toBe(""));
    expect((await screen.findByRole("status")).textContent).toMatch(/becomes usable only after verification succeeds/);
  });

  it("queues a verification and never shows the connection as ready", async () => {
    vi.mocked(providerConnectionApi.listConnections).mockResolvedValue(listing([connection()], true));
    vi.mocked(providerConnectionApi.verifyConnection).mockResolvedValue(connection({ status: "verifying" }));

    render(<AiProvidersPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Verify now" }));
    await waitFor(() => expect(providerConnectionApi.verifyConnection).toHaveBeenCalledWith("conn-1"));
    expect((await screen.findByRole("status")).textContent).toMatch("Verification queued.");
    expect(screen.queryByText("Ready")).toBeNull();
  });

  it("requires a second confirmation before disconnecting", async () => {
    vi.mocked(providerConnectionApi.listConnections).mockResolvedValue(listing([connection()], true));
    vi.mocked(providerConnectionApi.disconnectConnection).mockResolvedValue(connection({ status: "disconnected" }));

    render(<AiProvidersPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Disconnect" }));
    expect(providerConnectionApi.disconnectConnection).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm disconnect" }));
    await waitFor(() => expect(providerConnectionApi.disconnectConnection).toHaveBeenCalledWith("conn-1"));
  });

  it("clears a replacement secret after saving it", async () => {
    vi.mocked(providerConnectionApi.listConnections).mockResolvedValue(listing([connection()], true));
    vi.mocked(providerConnectionApi.rotateConnection).mockResolvedValue(connection());

    render(<AiProvidersPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Replace secret" }));
    const field = screen.getByLabelText("New API key");
    expect(field.getAttribute("type")).toBe("password");
    fireEvent.change(field, { target: { value: "sk-rotated-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new secret" }));

    await waitFor(() =>
      expect(providerConnectionApi.rotateConnection).toHaveBeenCalledWith("conn-1", "sk-rotated-value"),
    );
    expect(screen.queryByLabelText("New API key")).toBeNull();
  });

  it("reports a refused change in an alert and keeps the page usable", async () => {
    vi.mocked(providerConnectionApi.listConnections).mockResolvedValue(listing([connection()], true));
    vi.mocked(providerConnectionApi.verifyConnection).mockRejectedValue(
      new Error("This connection is disconnected. Create a new connection to verify again."),
    );

    render(<AiProvidersPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Verify now" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/disconnected/);
    expect((screen.getByRole("button", { name: "Verify now" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows a verification history without any secret", async () => {
    vi.mocked(providerConnectionApi.listConnections).mockResolvedValue(listing([connection()], true));
    vi.mocked(providerConnectionApi.listAttempts).mockResolvedValue({
      items: [
        {
          id: "a1",
          attempted_at: "2026-11-02T10:05:00Z",
          trigger: "created",
          outcome: "not_verified",
          reason_code: "live_adapter_disabled",
          latency_ms: 0,
          credential_version: 1,
          adapter_version: "openai-models-v1",
        },
      ],
    });

    render(<AiProvidersPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Show verification history" }));
    const history = await screen.findByRole("list", { name: /Verification history/ });
    expect(within(history).getByText(/not_verified \(live_adapter_disabled\), created/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/sk-/);
  });
});

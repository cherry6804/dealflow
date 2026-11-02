import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../lib/api";
import { providerConnectionApi } from "./providerConnectionApi";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
  };
});

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);

describe("providerConnectionApi", () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue(undefined as never);
    post.mockReset().mockResolvedValue(undefined as never);
  });

  it("calls the canonical AI namespace for every operation", async () => {
    await providerConnectionApi.listProviders();
    await providerConnectionApi.listConnections();
    await providerConnectionApi.createConnection("openai", "Primary", "sk-test");
    await providerConnectionApi.verifyConnection("c1");
    await providerConnectionApi.rotateConnection("c1", "sk-next");
    await providerConnectionApi.disconnectConnection("c1");
    await providerConnectionApi.listAttempts("c1");

    expect(get).toHaveBeenCalledWith("/ai/providers");
    expect(get).toHaveBeenCalledWith("/ai/provider-connections");
    expect(get).toHaveBeenCalledWith("/ai/provider-connections/c1/attempts");
    expect(post).toHaveBeenCalledWith("/ai/provider-connections", {
      provider_key: "openai",
      label: "Primary",
      secret: "sk-test",
    });
    expect(post).toHaveBeenCalledWith("/ai/provider-connections/c1/verify");
    expect(post).toHaveBeenCalledWith("/ai/provider-connections/c1/rotate", { secret: "sk-next" });
    expect(post).toHaveBeenCalledWith("/ai/provider-connections/c1/disconnect");
  });

  it("never calls the legacy credential paths", async () => {
    await providerConnectionApi.listConnections();
    await providerConnectionApi.createConnection("openai", "x", "sk-test");
    const paths = [...get.mock.calls.map(([path]) => path), ...post.mock.calls.map(([path]) => path)];
    expect(paths.every((path) => String(path).startsWith("/ai/"))).toBe(true);
  });
});

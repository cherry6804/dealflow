import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import { governanceApi } from "./governanceApi";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn() },
  };
});

const get = vi.mocked(api.get);
const post = vi.mocked(api.post);
const put = vi.mocked(api.put);
const patch = vi.mocked(api.patch);

describe("governanceApi", () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue(undefined as never);
    post.mockReset().mockResolvedValue(undefined as never);
    put.mockReset().mockResolvedValue(undefined as never);
    patch.mockReset().mockResolvedValue(undefined as never);
  });

  it("calls every governance route under the canonical AI namespace", async () => {
    await governanceApi.getAccess();
    await governanceApi.listCapabilities();
    await governanceApi.setCapability("automation.master", true);
    await governanceApi.getBudgets();
    await governanceApi.setBudget("tokens_input", 1000);
    await governanceApi.listDataCategories();
    await governanceApi.listRetention();
    await governanceApi.setRetention("crm.leads", 90);
    await governanceApi.listLegalHolds();
    await governanceApi.placeLegalHold("crm.leads", "Matter 42");
    await governanceApi.releaseLegalHold("hold-1");
    await governanceApi.listPrivacyRequests();
    await governanceApi.createPrivacyRequest("export", ["crm.leads"]);
    await governanceApi.cancelPrivacyRequest("request-1");

    const paths = [
      ...get.mock.calls.map(([path]) => path),
      ...post.mock.calls.map(([path]) => path),
      ...put.mock.calls.map(([path]) => path),
      ...patch.mock.calls.map(([path]) => path),
    ];

    expect(paths).toHaveLength(14);
    expect(paths.every((path) => path.startsWith("/ai/governance/"))).toBe(true);
    expect(paths).toContain("/ai/governance/access");
    expect(paths).toContain("/ai/governance/privacy/legal-holds/hold-1/release");
    expect(paths).toContain("/ai/governance/privacy/requests/request-1/cancel");
  });

  it("keeps each method and body on the matching route", async () => {
    await governanceApi.setCapability("automation.master", false);
    await governanceApi.setRetention("crm.leads", null);

    expect(patch).toHaveBeenCalledWith("/ai/governance/capabilities/automation.master", {
      is_enabled: false,
      confirm: true,
    });
    expect(put).toHaveBeenCalledWith("/ai/governance/privacy/retention/crm.leads", {
      retention_days: null,
      confirm: true,
    });
  });
});

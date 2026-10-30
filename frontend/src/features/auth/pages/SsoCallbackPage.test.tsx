import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../../lib/api";
import { organizationApi } from "../../../services/organizationApi";
import { resetSsoExchangesForTests } from "../ssoExchange";
import SsoCallbackPage from "./SsoCallbackPage";

const refreshSpy = vi.fn(async () => undefined);
const selectSpy = vi.fn();

// New function identities on every render, as the real app context produces on state updates.
vi.mock("../../../contexts/useAppContext", () => ({
  useAppContext: () => ({
    refreshSession: (...args: unknown[]) => refreshSpy(...(args as [])),
    selectOrganization: (id: string) => selectSpy(id),
  }),
}));

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api")>();
  return { ...actual, api: { post: vi.fn() } };
});

vi.mock("../../../services/organizationApi", () => ({
  organizationApi: { list: vi.fn() },
}));

const post = vi.mocked(api.post);
const list = vi.mocked(organizationApi.list);
const orgId = "00000000-0000-0000-0000-0000000000aa";

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/sso/callback" element={<SsoCallbackPage />} />
        <Route path="/access-required" element={<p>access page</p>} />
        <Route path="/" element={<p>home page</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SsoCallbackPage", () => {
  beforeEach(() => {
    post.mockReset();
    list.mockReset();
    refreshSpy.mockClear();
    selectSpy.mockClear();
    resetSsoExchangesForTests();
  });

  it("exchanges the code once and completes the session once, even when context functions change", async () => {
    post.mockResolvedValue({ user_id: "u", organization_id: orgId, return_to: null });
    list.mockResolvedValue([{ id: orgId }] as never);

    const view = renderAt("/sso/callback?code=code-1&state=state-1");

    await waitFor(() => expect(selectSpy).toHaveBeenCalledWith(orgId));
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/sso/callback", { code: "code-1", state: "state-1" });
    expect(refreshSpy).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("shows an accurate error when the exchange is refused, and does not retry the consumed code", async () => {
    const { ApiError } = await import("../../../lib/api");
    post.mockRejectedValue(new ApiError("consumed", 400));

    const view = renderAt("/sso/callback?code=code-2&state=state-2");

    // The page shows the server's own message for the refusal, not a generic success.
    expect(await view.findByText("consumed")).toBeTruthy();
    expect(post).toHaveBeenCalledTimes(1);
    expect(selectSpy).not.toHaveBeenCalled();
    view.unmount();
  });
});

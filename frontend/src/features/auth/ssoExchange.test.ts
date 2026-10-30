import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../../lib/api";
import { exchangeCodeOnce, resetSsoExchangesForTests } from "./ssoExchange";

vi.mock("../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/api")>();
  return { ...actual, api: { post: vi.fn() } };
});

const post = vi.mocked(api.post);
const result = {
  user_id: "00000000-0000-0000-0000-000000000001",
  organization_id: "00000000-0000-0000-0000-000000000002",
  return_to: null,
};

describe("exchangeCodeOnce", () => {
  beforeEach(() => {
    post.mockReset();
    resetSsoExchangesForTests();
  });

  it("sends a code once when StrictMode runs the effect twice", async () => {
    post.mockResolvedValue(result);

    const first = exchangeCodeOnce("code-a", "state-a");
    const second = exchangeCodeOnce("code-a", "state-a");

    expect(await first).toEqual(result);
    expect(await second).toEqual(result);
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("does not reuse an exchange for a different code", async () => {
    post.mockResolvedValue(result);

    await exchangeCodeOnce("code-a", "state-a");
    await exchangeCodeOnce("code-b", "state-b");

    expect(post).toHaveBeenCalledTimes(2);
  });

  it("reports a failed exchange to every caller and never replays the code", async () => {
    post.mockRejectedValue(new ApiError("consumed", 400));

    await expect(exchangeCodeOnce("code-a", "state-a")).rejects.toBeInstanceOf(ApiError);
    await expect(exchangeCodeOnce("code-a", "state-a")).rejects.toBeInstanceOf(ApiError);
    expect(post).toHaveBeenCalledTimes(1);
  });
});

import { api } from "../../lib/api";

export interface SsoCallbackResponse {
  user_id: string;
  organization_id: string;
  return_to?: string | null;
}

/**
 * The SSO authorization code is single-use. React StrictMode runs the callback effect
 * twice in development, and a page revisit can run it again. Every caller for the same
 * code shares one exchange, so the code is sent once. A failed exchange is shared too,
 * so a retry cannot replay a code that SIBVO has already consumed.
 */
const exchanges = new Map<string, Promise<SsoCallbackResponse>>();

export function exchangeCodeOnce(
  code: string,
  state: string,
): Promise<SsoCallbackResponse> {
  let exchange = exchanges.get(code);
  if (!exchange) {
    exchange = api.post<SsoCallbackResponse>("/sso/callback", { code, state });
    exchanges.set(code, exchange);
  }
  return exchange;
}

/** Test helper only: forget cached exchanges between tests. */
export function resetSsoExchangesForTests(): void {
  exchanges.clear();
}

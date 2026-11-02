import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  providerConnectionApi,
  type ProviderConnection,
  type ProviderDefinition,
  type VerificationAttempt,
} from "../../services/providerConnectionApi";

// Readiness, not raw status, decides what the screen says. Only "ready" is described as usable.
export function readinessText(connection: ProviderConnection): string {
  switch (connection.readiness_code) {
    case "ready":
      return "Verified and ready. AI features stay disabled until every other gate is enabled.";
    case "verifying":
      return "Verification is queued. The connection is not usable yet.";
    case "not_verified":
      return connection.status_reason_code === "live_adapter_disabled"
        ? "Not verified. Live provider access is disabled in this environment."
        : "Not verified.";
    case "degraded":
      return "The last check failed. Retrying automatically.";
    case "failed":
      return "Verification failed. Correct the credential, then verify again.";
    case "credential_changed":
      return "The secret changed. Verify it before use.";
    case "credential_revoked":
      return "The secret was revoked. Create a new connection.";
    case "stale":
      return "The last verification has expired. Verify again.";
    case "disconnected":
      return "Disconnected.";
    default:
      return "Not connected.";
  }
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "The change could not be saved. Please try again.";
}

export default function AiProvidersPage() {
  const [providers, setProviders] = useState<ProviderDefinition[]>([]);
  const [connections, setConnections] = useState<ProviderConnection[] | null>(null);
  const [canManage, setCanManage] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [providerKey, setProviderKey] = useState("openai");
  const [label, setLabel] = useState("");
  const [secret, setSecret] = useState("");

  const [rotateTarget, setRotateTarget] = useState<string | null>(null);
  const [rotateSecret, setRotateSecret] = useState("");
  const [disconnectTarget, setDisconnectTarget] = useState<string | null>(null);
  const [attempts, setAttempts] = useState<Record<string, VerificationAttempt[]>>({});

  const load = useCallback(async () => {
    try {
      const [registry, list] = await Promise.all([
        providerConnectionApi.listProviders(),
        providerConnectionApi.listConnections(),
      ]);
      setProviders(registry.items);
      setConnections(list.items);
      setCanManage(list.can_manage);
      setLoadError(null);
    } catch (error) {
      setLoadError(errorText(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      await action();
      setNotice(success);
      await load();
    } catch (error) {
      setActionError(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  async function submitCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = secret;
    setSecret(""); // the secret is not kept in component state after it is sent
    await run(
      () => providerConnectionApi.createConnection(providerKey, label.trim(), value),
      "Connection saved. It becomes usable only after verification succeeds.",
    );
    setLabel("");
  }

  async function submitRotate(connectionId: string) {
    const value = rotateSecret;
    setRotateSecret("");
    setRotateTarget(null);
    await run(
      () => providerConnectionApi.rotateConnection(connectionId, value),
      "Secret replaced. The connection is not usable until the new secret is verified.",
    );
  }

  async function toggleAttempts(connectionId: string) {
    if (attempts[connectionId]) {
      setAttempts((current) => {
        const next = { ...current };
        delete next[connectionId];
        return next;
      });
      return;
    }
    try {
      const response = await providerConnectionApi.listAttempts(connectionId);
      setAttempts((current) => ({ ...current, [connectionId]: response.items }));
    } catch (error) {
      setActionError(errorText(error));
    }
  }

  if (loadError) {
    return (
      <main>
        <h1>AI providers</h1>
        <p role="alert">{loadError}</p>
      </main>
    );
  }

  return (
    <main>
      <h1>AI providers</h1>
      <p>
        A provider is used only after a verification succeeds in the background. Saving a key does not connect
        the provider.
      </p>

      {notice ? <p role="status">{notice}</p> : null}
      {actionError ? <p role="alert">{actionError}</p> : null}

      <section aria-labelledby="provider-registry-heading">
        <h2 id="provider-registry-heading">Providers</h2>
        <ul>
          {providers.map((provider) => (
            <li key={provider.key}>
              <strong>{provider.display_name}</strong> ({provider.category}). Declared operations:{" "}
              {provider.declared_operations.join(", ")}.{" "}
              {provider.executable ? "Executable." : "Not executable yet."}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="connections-heading">
        <h2 id="connections-heading">Connections</h2>
        {connections === null ? <p>Loading connections...</p> : null}
        {connections !== null && connections.length === 0 ? <p>No provider is connected.</p> : null}
        <ul>
          {(connections ?? []).map((connection) => (
            <li key={connection.id}>
              <h3>
                {connection.label} ({connection.provider_key})
              </h3>
              <p>
                <strong>{connection.ready ? "Ready" : "Not ready"}</strong>: {readinessText(connection)}
              </p>
              {connection.last_verified_at ? (
                <p>Last verified: {new Date(connection.last_verified_at).toLocaleString()}</p>
              ) : null}

              {canManage && connection.status !== "disconnected" ? (
                <div>
                  <button type="button" disabled={busy} onClick={() => void run(
                    () => providerConnectionApi.verifyConnection(connection.id),
                    "Verification queued.",
                  )}>
                    Verify now
                  </button>{" "}
                  <button type="button" disabled={busy} onClick={() => setRotateTarget(connection.id)}>
                    Replace secret
                  </button>{" "}
                  {disconnectTarget === connection.id ? (
                    <>
                      <button type="button" disabled={busy} onClick={() => {
                        setDisconnectTarget(null);
                        void run(
                          () => providerConnectionApi.disconnectConnection(connection.id),
                          "Disconnected. The stored secret was destroyed.",
                        );
                      }}>
                        Confirm disconnect
                      </button>{" "}
                      <button type="button" onClick={() => setDisconnectTarget(null)}>
                        Keep connection
                      </button>
                    </>
                  ) : (
                    <button type="button" disabled={busy} onClick={() => setDisconnectTarget(connection.id)}>
                      Disconnect
                    </button>
                  )}
                </div>
              ) : null}

              {rotateTarget === connection.id ? (
                <form onSubmit={(event) => {
                  event.preventDefault();
                  void submitRotate(connection.id);
                }}>
                  <label>
                    New API key
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={rotateSecret}
                      onChange={(event) => setRotateSecret(event.target.value)}
                      required
                    />
                  </label>{" "}
                  <button type="submit" disabled={busy}>Save new secret</button>{" "}
                  <button type="button" onClick={() => {
                    setRotateSecret("");
                    setRotateTarget(null);
                  }}>
                    Cancel
                  </button>
                </form>
              ) : null}

              <button type="button" onClick={() => void toggleAttempts(connection.id)}>
                {attempts[connection.id] ? "Hide verification history" : "Show verification history"}
              </button>
              {attempts[connection.id] ? (
                <ul aria-label={`Verification history for ${connection.label}`}>
                  {attempts[connection.id].length === 0 ? <li>No checks yet.</li> : null}
                  {attempts[connection.id].map((attempt) => (
                    <li key={attempt.id}>
                      {new Date(attempt.attempted_at).toLocaleString()}: {attempt.outcome}
                      {attempt.reason_code ? ` (${attempt.reason_code})` : ""}, {attempt.trigger}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      {canManage ? (
        <section aria-labelledby="add-connection-heading">
          <h2 id="add-connection-heading">Add a connection</h2>
          <form onSubmit={(event) => void submitCreate(event)}>
            <label>
              Provider
              <select value={providerKey} onChange={(event) => setProviderKey(event.target.value)}>
                {providers.map((provider) => (
                  <option key={provider.key} value={provider.key}>
                    {provider.display_name}
                  </option>
                ))}
              </select>
            </label>{" "}
            <label>
              Label
              <input value={label} onChange={(event) => setLabel(event.target.value)} maxLength={120} required />
            </label>{" "}
            <label>
              API key
              <input
                type="password"
                autoComplete="new-password"
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
                required
              />
            </label>{" "}
            <button type="submit" disabled={busy}>Save connection</button>
          </form>
        </section>
      ) : (
        <p>Only the organization owner can add, replace or disconnect provider connections.</p>
      )}
    </main>
  );
}

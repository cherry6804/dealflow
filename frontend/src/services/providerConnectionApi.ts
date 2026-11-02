import { api } from "../lib/api";

// Status and readiness mirror backend/app/providers/readiness.py (ADR-0032). A connection is ready
// only when readiness is "ready". Status "connected" alone never means usable.
export type ConnectionStatus =
  | "unverified"
  | "verifying"
  | "connected"
  | "degraded"
  | "failed"
  | "disconnected";

export type ReadinessCode =
  | "ready"
  | "not_connected"
  | "not_verified"
  | "verifying"
  | "degraded"
  | "failed"
  | "disconnected"
  | "credential_revoked"
  | "credential_changed"
  | "stale";

export interface ProviderDefinition {
  key: string;
  display_name: string;
  category: string;
  declared_operations: string[];
  adapter_implemented: boolean;
  executable: boolean;
}

export interface ProviderConnection {
  id: string;
  provider_key: string;
  label: string;
  status: ConnectionStatus;
  status_reason_code: string | null;
  ready: boolean;
  readiness_code: ReadinessCode;
  credential_version: number | null;
  verified_credential_version: number | null;
  last_verified_at: string | null;
  last_attempt_at: string | null;
  consecutive_failures: number;
  next_verification_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderConnectionList {
  items: ProviderConnection[];
  can_manage: boolean;
}

export interface VerificationAttempt {
  id: string;
  attempted_at: string;
  trigger: string;
  outcome: string;
  reason_code: string | null;
  latency_ms: number;
  credential_version: number;
  adapter_version: string;
}

export const providerConnectionApi = {
  listProviders(): Promise<{ items: ProviderDefinition[] }> {
    return api.get<{ items: ProviderDefinition[] }>("/ai/providers");
  },

  listConnections(): Promise<ProviderConnectionList> {
    return api.get<ProviderConnectionList>("/ai/provider-connections");
  },

  createConnection(providerKey: string, label: string, secret: string): Promise<ProviderConnection> {
    return api.post<ProviderConnection>("/ai/provider-connections", {
      provider_key: providerKey,
      label,
      secret,
    });
  },

  verifyConnection(connectionId: string): Promise<ProviderConnection> {
    return api.post<ProviderConnection>(`/ai/provider-connections/${connectionId}/verify`);
  },

  rotateConnection(connectionId: string, secret: string): Promise<ProviderConnection> {
    return api.post<ProviderConnection>(`/ai/provider-connections/${connectionId}/rotate`, { secret });
  },

  disconnectConnection(connectionId: string): Promise<ProviderConnection> {
    return api.post<ProviderConnection>(`/ai/provider-connections/${connectionId}/disconnect`);
  },

  listAttempts(connectionId: string): Promise<{ items: VerificationAttempt[] }> {
    return api.get<{ items: VerificationAttempt[] }>(`/ai/provider-connections/${connectionId}/attempts`);
  },
};

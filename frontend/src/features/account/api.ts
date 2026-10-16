import { apiRequest } from "../../lib/api-client";
import type { StepResponse } from "../../lib/auth";

export interface SecurityKey {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

export interface MfaStatus {
  totp: boolean;
  security_keys: SecurityKey[];
  recovery_codes_left: number;
}

export interface TotpSetup {
  secret: string;
  otpauth_uri: string;
  qr_png_data_uri: string;
}

export interface EnrollmentResponse extends StepResponse {
  recovery_codes: string[];
}

export interface SessionSummary {
  id: string;
  created_at: string;
  last_seen_at: string;
  ip: string | null;
  user_agent: string;
  current: boolean;
}

export const accountApi = {
  changePassword: (currentPassword: string, newPassword: string) =>
    apiRequest<StepResponse>("POST", "/me/password", {
      body: { current_password: currentPassword, new_password: newPassword },
    }),
  mfaStatus: () => apiRequest<MfaStatus>("GET", "/me/mfa"),
  startTotp: () => apiRequest<TotpSetup>("POST", "/me/mfa/totp"),
  confirmTotp: (code: string) =>
    apiRequest<EnrollmentResponse>("POST", "/me/mfa/totp/confirm", { body: { code } }),
  removeTotp: () => apiRequest<undefined>("DELETE", "/me/mfa/totp"),
  securityKeyOptions: () => apiRequest<Record<string, unknown>>("POST", "/me/mfa/webauthn/options"),
  registerSecurityKey: (name: string, credential: Record<string, unknown>) =>
    apiRequest<EnrollmentResponse>("POST", "/me/mfa/webauthn", { body: { name, credential } }),
  removeSecurityKey: (id: string) => apiRequest<undefined>("DELETE", `/me/mfa/webauthn/${id}`),
  regenerateRecoveryCodes: () => apiRequest<{ codes: string[] }>("POST", "/me/mfa/recovery-codes"),
  sessions: () => apiRequest<SessionSummary[]>("GET", "/me/sessions"),
  revokeSession: (id: string) => apiRequest<undefined>("DELETE", `/me/sessions/${id}`),
  revokeOtherSessions: () => apiRequest<{ count: number }>("POST", "/me/sessions/revoke-others"),
};

export type ApiKeyScope = "pages:read" | "pages:write" | "admin";

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: ApiKeyScope[];
  status: "active" | "expired" | "revoked";
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
}

export const apiKeysApi = {
  list: () => apiRequest<ApiKey[]>("GET", "/me/api-keys"),
  create: (body: { name: string; scopes: ApiKeyScope[]; days: number }, key: string) =>
    apiRequest<ApiKey & { secret: string }>("POST", "/me/api-keys", { body, idempotencyKey: key }),
  revoke: (id: string) => apiRequest<undefined>("DELETE", `/me/api-keys/${id}`),
};

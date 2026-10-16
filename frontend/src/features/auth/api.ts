import { apiRequest } from "../../lib/api-client";
import type { StepResponse } from "../../lib/auth";

/** WebAuthn options/credentials are opaque JSON exchanged with @simplewebauthn/browser. */
export type WebAuthnJson = Record<string, unknown>;

export interface AuthMethods {
  oidc: boolean;
  oidc_label: string;
  directory: boolean;
}

export const authApi = {
  methods: () => apiRequest<AuthMethods>("GET", "/auth/methods"),
  login: (username: string, password: string) =>
    apiRequest<StepResponse>("POST", "/auth/login", { body: { username, password } }),
  verifyTotp: (code: string) =>
    apiRequest<StepResponse>("POST", "/auth/mfa/totp", { body: { code } }),
  verifyRecoveryCode: (code: string) =>
    apiRequest<StepResponse>("POST", "/auth/mfa/recovery", { body: { code } }),
  webauthnOptions: () => apiRequest<WebAuthnJson>("POST", "/auth/mfa/webauthn/options"),
  verifyWebauthn: (credential: WebAuthnJson) =>
    apiRequest<StepResponse>("POST", "/auth/mfa/webauthn", { body: { credential } }),
  reauthWebauthnOptions: () => apiRequest<WebAuthnJson>("POST", "/auth/reauth/webauthn/options"),
  reauth: (body: {
    password: string;
    totp_code?: string;
    recovery_code?: string;
    webauthn_credential?: WebAuthnJson;
  }) => apiRequest<StepResponse>("POST", "/auth/reauth", { body }),
  logout: () => apiRequest<undefined>("POST", "/auth/logout"),
  requestReset: (email: string) =>
    apiRequest<{ status: string }>("POST", "/auth/password-reset", { body: { email } }),
  confirmReset: (token: string, newPassword: string) =>
    apiRequest<undefined>("POST", "/auth/password-reset/confirm", {
      body: { token, new_password: newPassword },
    }),
};

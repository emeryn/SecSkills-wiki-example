import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { ApiError, apiRequest, setCsrfToken } from "./api-client";

export type SessionState =
  "active" | "mfa_required" | "password_change_required" | "mfa_enrollment_required";

export interface SessionUser {
  id: string;
  username: string;
  display_name: string | null;
  email: string | null;
  role: "user" | "admin";
  auth_source: "local" | "oidc" | "ldap";
  permissions: string[];
}

export interface SessionInfo {
  state: SessionState;
  user: SessionUser;
  csrf_token: string;
  idle_expires_at: string;
  absolute_expires_at: string;
  mfa_methods: ("totp" | "webauthn")[];
}

export interface StepResponse {
  state: SessionState;
  csrf_token: string;
}

export const SESSION_KEY = ["auth", "session"] as const;

/** Route for each incomplete sign-in step. */
export const STEP_ROUTES: Record<SessionState, string> = {
  active: "/",
  mfa_required: "/login/verify",
  password_change_required: "/setup/password",
  mfa_enrollment_required: "/setup/security",
};

/**
 * Post-login destination. Only same-origin relative paths starting with a single "/" are
 * accepted (no "//host", "/\\host", scheme or control characters): prevents open redirects.
 */
export function safeNextPath(next: string | null | undefined): string {
  if (!next || next.length > 2000) return "/";
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f\\]/.test(next)) return "/";
  return next;
}

async function fetchSession(): Promise<SessionInfo | null> {
  try {
    const session = await apiRequest<SessionInfo>("GET", "/auth/session");
    setCsrfToken(session.csrf_token);
    return session;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw error;
  }
}

export function useSession() {
  return useQuery({ queryKey: SESSION_KEY, queryFn: fetchSession, staleTime: 60_000 });
}

/** Applies a sign-in step result: new CSRF token, then reloads the session. */
export function useApplyStep() {
  const queryClient = useQueryClient();
  return useCallback(
    async (step: StepResponse) => {
      setCsrfToken(step.csrf_token);
      await queryClient.invalidateQueries({ queryKey: SESSION_KEY });
      return step.state;
    },
    [queryClient],
  );
}

export function hasPermission(session: SessionInfo | null | undefined, permission: string) {
  return session?.user.permissions.includes(permission) ?? false;
}

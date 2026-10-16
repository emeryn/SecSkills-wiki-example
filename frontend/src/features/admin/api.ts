import { apiDownload, apiRequest } from "../../lib/api-client";

export type Role = "user" | "admin";
export type UserStatus = "active" | "disabled";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminUser {
  id: string;
  username: string;
  email: string | null;
  display_name: string | null;
  role: Role;
  status: UserStatus;
  auth_source: string;
  created_at: string;
  last_login_at: string | null;
}

export interface AdminUserDetail extends AdminUser {
  mfa_enrolled: boolean;
  active_sessions: number;
  groups: { id: string; name: string }[];
}

export interface Link {
  url: string;
  expires_at: string;
}

export interface Group {
  id: string;
  name: string;
  description: string;
  source: string;
  member_count: number;
  created_at: string;
}

export interface GroupDetail extends Group {
  members: { id: string; username: string; display_name: string | null }[];
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text === "" ? "" : `?${text}`;
}

export const adminApi = {
  users: (params: Record<string, string | number | undefined>) =>
    apiRequest<Page<AdminUser>>("GET", `/admin/users${query(params)}`),
  user: (id: string) => apiRequest<AdminUserDetail>("GET", `/admin/users/${id}`),
  createUser: (
    body: { username: string; email?: string; display_name?: string; role: Role },
    key: string,
  ) =>
    apiRequest<{ user: AdminUser; invitation: Link }>("POST", "/admin/users", {
      body,
      idempotencyKey: key,
    }),
  updateUser: (
    id: string,
    body: Partial<Pick<AdminUser, "email" | "display_name" | "role" | "status">>,
    key: string,
  ) => apiRequest<AdminUser>("PATCH", `/admin/users/${id}`, { body, idempotencyKey: key }),
  resetLink: (id: string) => apiRequest<Link>("POST", `/admin/users/${id}/reset-link`),
  revokeSessions: (id: string) =>
    apiRequest<{ count: number }>("POST", `/admin/users/${id}/revoke-sessions`),
  resetMfa: (id: string) => apiRequest<undefined>("POST", `/admin/users/${id}/reset-mfa`),
  groups: (params: Record<string, string | number | undefined>) =>
    apiRequest<Page<Group>>("GET", `/admin/groups${query(params)}`),
  group: (id: string) => apiRequest<GroupDetail>("GET", `/admin/groups/${id}`),
  createGroup: (body: { name: string; description: string }, key: string) =>
    apiRequest<Group>("POST", "/admin/groups", { body, idempotencyKey: key }),
  updateGroup: (id: string, body: { name?: string; description?: string }, key: string) =>
    apiRequest<GroupDetail>("PATCH", `/admin/groups/${id}`, { body, idempotencyKey: key }),
  deleteGroup: (id: string) => apiRequest<undefined>("DELETE", `/admin/groups/${id}`),
  addMember: (groupId: string, userId: string) =>
    apiRequest<undefined>("PUT", `/admin/groups/${groupId}/members/${userId}`),
  removeMember: (groupId: string, userId: string) =>
    apiRequest<undefined>("DELETE", `/admin/groups/${groupId}/members/${userId}`),
};

export type Period = "24h" | "7d" | "30d";

export interface AuditEvent {
  id: number;
  occurred_at: string;
  actor: { id: string | null; username: string | null };
  actor_ip: string | null;
  user_agent: string;
  action: string;
  outcome: "success" | "failure";
  severity: "info" | "warning" | "critical";
  target_type: string | null;
  target_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  request_id: string | null;
}

export interface ServerError {
  id: number;
  occurred_at: string;
  source: "request" | "job";
  method: string;
  path: string;
  status: number;
  request_id: string | null;
}

export interface Dashboard {
  period: Period;
  since: string;
  users: { total: number; active: number; disabled: number; signed_in: number };
  content: {
    spaces: number;
    pages: number;
    revisions: number;
    attachments: number;
    attachment_bytes: number;
  };
  security: { failed_sign_ins: number; honeytoken_alerts: number; blocked_ips: number };
  errors: { count: number; recent: ServerError[] };
  backup: { last_at: string | null; size_bytes: number | null; overdue: boolean };
  activity: { bucket: string; sign_ins: number; edits: number }[];
  alerts: AuditEvent[];
}

export interface BlockedIp {
  ip: string;
  reason: string;
  hits: number;
  blocked_at: string;
  expires_at: string | null;
}

export const SECTIONS = [
  "syslog",
  "smtp",
  "webhook",
  "notifications",
  "privacy",
  "security",
  "oidc",
  "ldap",
  "llm",
  "mcp",
] as const;
export type Section = (typeof SECTIONS)[number];
export type TestableSection = "syslog" | "smtp" | "webhook" | "oidc" | "ldap" | "llm";

export interface LlmModel {
  name: string;
  digest: string;
  size_bytes: number;
  format: string;
  family: string;
  approved: boolean;
}

export interface PromptState {
  current: string;
  default: string;
  versions: {
    id: number;
    content: string;
    is_default: boolean;
    created_by: string | null;
    created_at: string;
  }[];
}

export interface SettingsResponse<T = Record<string, unknown>> {
  section: Section;
  values: T;
  managed_by_environment: boolean;
  managed_fields: string[];
  updated_at: string | null;
  updated_by: string | null;
  info: Record<string, unknown>;
}

export const operationsApi = {
  dashboard: (period: Period) => apiRequest<Dashboard>("GET", `/admin/dashboard?period=${period}`),
  audit: (params: Record<string, string | number | undefined>) =>
    apiRequest<Page<AuditEvent>>("GET", `/admin/audit${query(params)}`),
  auditActions: () => apiRequest<string[]>("GET", "/admin/audit/actions"),
  auditExport: (params: Record<string, string | undefined>) =>
    apiDownload(`/admin/audit/export${query(params)}`),
  settings: (section: Section) => apiRequest<SettingsResponse>("GET", `/admin/settings/${section}`),
  saveSettings: (section: Section, body: Record<string, unknown>, key: string) =>
    apiRequest<SettingsResponse>("PUT", `/admin/settings/${section}`, {
      body,
      idempotencyKey: key,
    }),
  resetSettings: (section: Section) =>
    apiRequest<SettingsResponse>("DELETE", `/admin/settings/${section}`),
  testSettings: (section: TestableSection) =>
    apiRequest<{ ok: boolean; message: string }>("POST", `/admin/settings/${section}/test`),
  blockedIps: () => apiRequest<BlockedIp[]>("GET", "/admin/blocked-ips"),
  llmModels: () => apiRequest<LlmModel[]>("GET", "/admin/llm/models"),
  llmPrompt: () => apiRequest<PromptState>("GET", "/admin/llm/prompt"),
  saveLlmPrompt: (content: string, key: string) =>
    apiRequest<PromptState>("PUT", "/admin/llm/prompt", { body: { content }, idempotencyKey: key }),
  resetLlmPrompt: () => apiRequest<PromptState>("DELETE", "/admin/llm/prompt"),
  unblock: (ip: string) =>
    apiRequest<undefined>("DELETE", `/admin/blocked-ips/${encodeURIComponent(ip)}`),
};

import type { Section } from "./api";

export type FieldKind =
  "boolean" | "text" | "number" | "select" | "pem" | "secret" | "list" | "mapping";

export interface FieldSpec {
  name: string;
  kind: FieldKind;
  options?: readonly string[];
  maxLength?: number;
  min?: number;
  max?: number;
  /** Increment of number fields (decimals need a step below 1). */
  step?: number;
}

const ID_TOKEN_ALGORITHMS = [
  "RS256",
  "RS384",
  "RS512",
  "PS256",
  "PS384",
  "PS512",
  "ES256",
  "ES384",
  "ES512",
  "EdDSA",
] as const;

/** Form layout of each settings section; labels are `settings.fields.<section>.<name>`. */
export const SECTION_FIELDS: Record<Section, FieldSpec[]> = {
  syslog: [
    { name: "enabled", kind: "boolean" },
    { name: "host", kind: "text", maxLength: 253 },
    { name: "port", kind: "number", min: 1, max: 65535 },
    { name: "app_name", kind: "text", maxLength: 48 },
    { name: "min_level", kind: "select", options: ["INFO", "WARNING", "ERROR", "CRITICAL"] },
    { name: "forward_audit", kind: "boolean" },
    { name: "ca_pem", kind: "pem" },
  ],
  smtp: [
    { name: "enabled", kind: "boolean" },
    { name: "host", kind: "text", maxLength: 253 },
    { name: "port", kind: "number", min: 1, max: 65535 },
    { name: "from_address", kind: "text", maxLength: 254 },
    { name: "username", kind: "text", maxLength: 254 },
    { name: "password", kind: "secret", maxLength: 1024 },
    { name: "ca_pem", kind: "pem" },
  ],
  webhook: [
    { name: "enabled", kind: "boolean" },
    { name: "url", kind: "text", maxLength: 2000 },
    { name: "secret", kind: "secret", maxLength: 256 },
    { name: "ca_pem", kind: "pem" },
  ],
  notifications: [
    { name: "notify_errors", kind: "boolean" },
    { name: "notify_security", kind: "boolean" },
    { name: "email_recipients", kind: "list", maxLength: 254 },
  ],
  privacy: [{ name: "mask_pii", kind: "boolean" }],
  security: [
    { name: "honeytokens_enabled", kind: "boolean" },
    { name: "decoy_usernames", kind: "list", maxLength: 64 },
    { name: "block_minutes", kind: "number", min: 0, max: 525600 },
    { name: "allowed_private_networks", kind: "list", maxLength: 50 },
    { name: "local_sign_in", kind: "select", options: ["all", "admins_only"] },
  ],
  oidc: [
    { name: "enabled", kind: "boolean" },
    { name: "display_name", kind: "text", maxLength: 50 },
    { name: "issuer", kind: "text", maxLength: 2000 },
    { name: "client_id", kind: "text", maxLength: 255 },
    { name: "client_secret", kind: "secret", maxLength: 1024 },
    { name: "scopes", kind: "list", maxLength: 64 },
    { name: "id_token_algorithm", kind: "select", options: ID_TOKEN_ALGORITHMS },
    { name: "username_claim", kind: "text", maxLength: 100 },
    { name: "email_claim", kind: "text", maxLength: 100 },
    { name: "name_claim", kind: "text", maxLength: 100 },
    { name: "groups_claim", kind: "text", maxLength: 100 },
    { name: "auto_provision", kind: "boolean" },
    { name: "group_mapping", kind: "mapping" },
    { name: "admin_groups", kind: "list", maxLength: 500 },
    { name: "ca_pem", kind: "pem" },
  ],
  llm: [
    { name: "enabled", kind: "boolean" },
    { name: "url", kind: "text", maxLength: 2000 },
    { name: "api_key", kind: "secret", maxLength: 1024 },
    { name: "proxy_url", kind: "text", maxLength: 500 },
    { name: "chat_model", kind: "text", maxLength: 200 },
    { name: "embedding_model", kind: "text", maxLength: 200 },
    { name: "temperature", kind: "number", min: 0, max: 2, step: 0.05 },
    { name: "top_p", kind: "number", min: 0, max: 1, step: 0.05 },
    { name: "max_tokens", kind: "number", min: 64, max: 8192 },
    { name: "context_window", kind: "number", min: 2048, max: 131072 },
    { name: "retrieval_chunks", kind: "number", min: 1, max: 12 },
    { name: "min_similarity", kind: "number", min: 0, max: 1, step: 0.05 },
    { name: "daily_token_quota", kind: "number", min: 1000, max: 10000000 },
    { name: "requests_per_minute", kind: "number", min: 1, max: 60 },
    { name: "log_prompts", kind: "boolean" },
    { name: "ca_pem", kind: "pem" },
  ],
  mcp: [
    { name: "user_enabled", kind: "boolean" },
    { name: "admin_enabled", kind: "boolean" },
    { name: "requests_per_minute", kind: "number", min: 1, max: 600 },
  ],
  ldap: [
    { name: "enabled", kind: "boolean" },
    { name: "url", kind: "text", maxLength: 500 },
    { name: "start_tls", kind: "boolean" },
    { name: "bind_dn", kind: "text", maxLength: 500 },
    { name: "bind_password", kind: "secret", maxLength: 1024 },
    { name: "user_base_dn", kind: "text", maxLength: 500 },
    { name: "user_filter", kind: "text", maxLength: 500 },
    { name: "username_attribute", kind: "text", maxLength: 64 },
    { name: "email_attribute", kind: "text", maxLength: 64 },
    { name: "name_attribute", kind: "text", maxLength: 64 },
    { name: "group_base_dn", kind: "text", maxLength: 500 },
    { name: "group_filter", kind: "text", maxLength: 500 },
    { name: "auto_provision", kind: "boolean" },
    { name: "group_mapping", kind: "mapping" },
    { name: "admin_groups", kind: "list", maxLength: 500 },
    { name: "ca_pem", kind: "pem" },
  ],
};

export const TESTABLE: readonly Section[] = ["syslog", "smtp", "webhook", "oidc", "ldap", "llm"];
/** Sections whose test checks a connection instead of sending a message. */
export const CONNECTION_TEST: readonly Section[] = ["oidc", "ldap", "llm"];

export type FormValues = Record<string, string | boolean>;

interface GroupMapping {
  group: string;
  space: string;
  role: string;
}

const MAPPING_SEPARATOR = " | ";

function isMapping(value: unknown): value is GroupMapping {
  return typeof value === "object" && value !== null && "group" in value && "space" in value;
}

/** One rule per line: `group | space-key | role` (a DN may contain commas and equal signs). */
export function parseMapping(text: string): GroupMapping[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "")
    .map((line) => {
      const parts = line.split("|").map((part) => part.trim());
      const role = parts.pop() ?? "";
      const space = parts.pop() ?? "";
      return { group: parts.join("|"), space, role };
    });
}

/** API values → form state (lists one per line, numbers as text, secrets left empty). */
export function toForm(section: Section, values: Record<string, unknown>): FormValues {
  const form: FormValues = {};
  for (const field of SECTION_FIELDS[section]) {
    const value = values[field.name];
    if (field.kind === "boolean") form[field.name] = value === true;
    else if (field.kind === "secret") form[field.name] = "";
    else if (field.kind === "mapping")
      form[field.name] = Array.isArray(value)
        ? value
            .filter(isMapping)
            .map((rule) => [rule.group, rule.space, rule.role].join(MAPPING_SEPARATOR))
            .join("\n")
        : "";
    else if (field.kind === "list") form[field.name] = Array.isArray(value) ? value.join("\n") : "";
    else
      form[field.name] =
        typeof value === "string" || typeof value === "number" ? String(value) : "";
  }
  return form;
}

/**
 * Form state → request body. A secret is sent only when typed (omitted keeps the stored one)
 * or explicitly cleared (`null`). Fields defined by environment variables are never sent.
 */
export function toBody(
  section: Section,
  form: FormValues,
  clearedSecrets: ReadonlySet<string>,
  managed: ReadonlySet<string> = new Set(),
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const field of SECTION_FIELDS[section]) {
    if (managed.has(field.name)) continue;
    const value = form[field.name];
    if (field.kind === "boolean") {
      body[field.name] = value === true;
    } else if (field.kind === "secret") {
      if (clearedSecrets.has(field.name)) body[field.name] = null;
      else if (typeof value === "string" && value !== "") body[field.name] = value;
    } else if (field.kind === "mapping") {
      body[field.name] = parseMapping(String(value));
    } else if (field.kind === "list") {
      body[field.name] = String(value)
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line !== "");
    } else if (field.kind === "number") {
      body[field.name] = Number(value);
    } else {
      const text = String(value).trim();
      body[field.name] = text === "" ? null : text;
    }
  }
  return body;
}

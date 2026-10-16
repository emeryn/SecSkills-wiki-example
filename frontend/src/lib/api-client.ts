import { config } from "./config";

/** Error returned by the API (`{"error": {"code", "message", "request_id"}}`) or the network. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  body?: unknown;
  /** Multipart upload instead of a JSON body. */
  form?: FormData;
  /** Generate once per user action with `newIdempotencyKey()` and reuse it on retries. */
  idempotencyKey?: string;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

// Held in memory only: the CSRF token is never written to Web Storage.
let csrfToken: string | null = null;
let reauthHandler: (() => Promise<boolean>) | null = null;
let unauthenticatedHandler: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Called on `REAUTH_REQUIRED`; resolves true once the user confirmed their identity. */
export function setReauthHandler(handler: (() => Promise<boolean>) | null): void {
  reauthHandler = handler;
}

/** Called when the session is gone (expired or revoked). */
export function setUnauthenticatedHandler(handler: (() => void) | null): void {
  unauthenticatedHandler = handler;
}

interface ErrorPayload {
  error?: { code?: unknown; message?: unknown; request_id?: unknown };
}

async function toApiError(response: Response): Promise<ApiError> {
  let payload: ErrorPayload = {};
  try {
    payload = (await response.json()) as ErrorPayload;
  } catch {
    // Non-JSON error (e.g. from the proxy): keep the defaults below.
  }
  const error = payload.error ?? {};
  return new ApiError(
    response.status,
    typeof error.code === "string" ? error.code : `HTTP_${String(response.status)}`,
    typeof error.message === "string" ? error.message : response.statusText,
    typeof error.request_id === "string" ? error.request_id : response.headers.get("X-Request-ID"),
  );
}

async function send(method: Method, path: string, options: RequestOptions, key: string) {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  headers.set("X-Requested-With", "XMLHttpRequest");
  if (method !== "GET") {
    headers.set("Idempotency-Key", key);
    if (csrfToken !== null) headers.set("X-CSRF-Token", csrfToken);
  }
  let body: string | FormData | undefined;
  if (options.form !== undefined) {
    // The browser sets the multipart boundary itself.
    body = options.form;
  } else if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }
  try {
    return await fetch(config.apiBasePath + path, {
      method,
      headers,
      body,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: options.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "NETWORK_ERROR", "Network error", null);
  }
}

/**
 * Calls the API with credentials, CSRF headers and an idempotency key on every write.
 * A `REAUTH_REQUIRED` answer opens the re-authentication dialog, then retries once with the
 * same idempotency key.
 */
async function call(method: Method, path: string, options: RequestOptions): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("API paths must be relative to the API base path");
  }
  const key = options.idempotencyKey ?? newIdempotencyKey();
  let response = await send(method, path, options, key);
  if (response.ok) return response;
  let error = await toApiError(response);
  if (error.code === "REAUTH_REQUIRED" && reauthHandler !== null && (await reauthHandler())) {
    response = await send(method, path, options, key);
    if (response.ok) return response;
    error = await toApiError(response);
  }
  if (error.code === "UNAUTHENTICATED" && !path.startsWith("/auth/")) unauthenticatedHandler?.();
  throw error;
}

export async function apiRequest<T>(
  method: Method,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  return parse<T>(await call(method, path, options));
}

/** Multipart upload of one file (field `file`). */
export async function apiUpload<T>(path: string, file: File, idempotencyKey?: string): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  return parse<T>(await call("POST", path, { form, idempotencyKey }));
}

/** GET a file (export); returns its content and the server-provided file name. */
export async function apiDownload(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await call("GET", path, {});
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  return { blob: await response.blob(), filename: decodeURIComponent(match?.[1] ?? "download") };
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** POST whose response is read as a stream (server-sent events); errors before it starts throw. */
export async function apiStream(
  path: string,
  body: unknown,
  signal: AbortSignal,
): Promise<Response> {
  return call("POST", path, { body, signal });
}

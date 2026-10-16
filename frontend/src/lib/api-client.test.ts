import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  apiDownload,
  apiRequest,
  apiUpload,
  newIdempotencyKey,
  setCsrfToken,
  setReauthHandler,
  setUnauthenticatedHandler,
} from "./api-client";

function mockFetch(response: Response) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function sentHeaders(fetchMock: ReturnType<typeof mockFetch>): Headers {
  const init = fetchMock.mock.calls[0]?.[1];
  return new Headers(init?.headers);
}

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  setReauthHandler(null);
  setUnauthenticatedHandler(null);
});

describe("apiRequest", () => {
  it("prefixes the API base path and sends the CSRF header", async () => {
    const fetchMock = mockFetch(Response.json({ status: "ok" }));
    await expect(apiRequest("GET", "/health")).resolves.toEqual({ status: "ok" });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/health");
    expect(sentHeaders(fetchMock).get("X-Requested-With")).toBe("XMLHttpRequest");
    expect(sentHeaders(fetchMock).has("Idempotency-Key")).toBe(false);
  });

  it("attaches the given idempotency key to writes so retries reuse it", async () => {
    const key = newIdempotencyKey();
    const fetchMock = mockFetch(new Response(null, { status: 204 }));
    await apiRequest("POST", "/spaces", { body: { name: "Eng" }, idempotencyKey: key });
    expect(sentHeaders(fetchMock).get("Idempotency-Key")).toBe(key);
    expect(sentHeaders(fetchMock).get("Content-Type")).toBe("application/json");
  });

  it("generates an idempotency key when none is given", async () => {
    const fetchMock = mockFetch(new Response(null, { status: 204 }));
    await apiRequest("DELETE", "/spaces/eng");
    expect(sentHeaders(fetchMock).get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("parses the standard error format", async () => {
    mockFetch(
      Response.json(
        { error: { code: "NOT_FOUND", message: "Not found", request_id: "abc123" } },
        { status: 404 },
      ),
    );
    const error = await apiRequest("GET", "/spaces/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, code: "NOT_FOUND", requestId: "abc123" });
  });

  it("maps network failures to NETWORK_ERROR", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline")));
    await expect(apiRequest("GET", "/health")).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });

  it("refuses protocol-relative paths", async () => {
    await expect(apiRequest("GET", "//evil.example/x")).rejects.toThrow();
  });

  it("sends the CSRF token on writes only", async () => {
    setCsrfToken("csrf-1");
    const fetchMock = mockFetch(new Response(null, { status: 204 }));
    await apiRequest("POST", "/groups", { body: {} });
    expect(sentHeaders(fetchMock).get("X-CSRF-Token")).toBe("csrf-1");
    const getMock = mockFetch(Response.json({}));
    await apiRequest("GET", "/groups");
    expect(sentHeaders(getMock).has("X-CSRF-Token")).toBe(false);
  });

  it("re-authenticates then retries once with the same idempotency key", async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        Response.json(
          { error: { code: "REAUTH_REQUIRED", message: "x", request_id: "r" } },
          { status: 401 },
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const handler = vi.fn(() => Promise.resolve(true));
    setReauthHandler(handler);
    await apiRequest("POST", "/admin/users/1/reset-mfa");
    expect(handler).toHaveBeenCalledOnce();
    const keys = fetchMock.mock.calls.map((call) =>
      new Headers(call[1]?.headers).get("Idempotency-Key"),
    );
    expect(keys[0]).toBe(keys[1]);
  });

  it("does not retry when re-authentication is cancelled", async () => {
    const fetchMock = mockFetch(
      Response.json(
        { error: { code: "REAUTH_REQUIRED", message: "x", request_id: "r" } },
        { status: 401 },
      ),
    );
    setReauthHandler(() => Promise.resolve(false));
    await expect(apiRequest("POST", "/admin/users/1/reset-mfa")).rejects.toMatchObject({
      code: "REAUTH_REQUIRED",
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("reports an expired session", async () => {
    mockFetch(
      Response.json(
        { error: { code: "UNAUTHENTICATED", message: "x", request_id: "r" } },
        { status: 401 },
      ),
    );
    const handler = vi.fn();
    setUnauthenticatedHandler(handler);
    await expect(apiRequest("GET", "/me/sessions")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledOnce();
  });
});

describe("apiUpload and apiDownload", () => {
  it("uploads multipart with CSRF and idempotency headers", async () => {
    setCsrfToken("csrf-1");
    const fetchMock = mockFetch(Response.json({ id: "a1" }, { status: 201 }));
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    await apiUpload("/spaces/eng/pages/p1/attachments", file);
    const init = fetchMock.mock.calls[0]?.[1];
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get("file")).toBe(file);
    const headers = new Headers(init?.headers);
    expect(headers.has("Content-Type")).toBe(false);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-1");
    expect(headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("reads the file name of a download", async () => {
    mockFetch(
      new Response("zip-bytes", {
        headers: { "Content-Disposition": "attachment; filename*=UTF-8''eng-20261014.zip" },
      }),
    );
    const { blob, filename } = await apiDownload("/spaces/eng/export");
    expect(filename).toBe("eng-20261014.zip");
    expect(await blob.text()).toBe("zip-bytes");
  });
});

import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { Providers } from "./app/providers";
import { routes } from "./app/router";
import type { SessionInfo } from "./lib/auth";

export type Handler = (init: RequestInit | undefined, url: URL) => Response | Promise<Response>;

/** Stubs `fetch` with handlers keyed by "METHOD /api/v1/path"; unknown calls return 404. */
export function mockApi(handlers: Record<string, Handler>) {
  const calls: { method: string; path: string; init: RequestInit | undefined }[] = [];
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, "https://wiki.example.com");
    const method = init?.method ?? "GET";
    calls.push({ method, path: url.pathname, init });
    const handler = handlers[`${method} ${url.pathname}`];
    if (handler === undefined) {
      return Response.json(
        { error: { code: "NOT_FOUND", message: "Not found", request_id: "test" } },
        { status: 404 },
      );
    }
    return handler(init, url);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function sessionFixture(
  overrides: Partial<SessionInfo> = {},
  permissions: string[] = [],
): SessionInfo {
  const inOneHour = new Date(Date.now() + 3_600_000).toISOString();
  return {
    state: "active",
    csrf_token: "csrf-test-token",
    idle_expires_at: inOneHour,
    absolute_expires_at: inOneHour,
    mfa_methods: [],
    user: {
      id: "u1",
      username: "alice",
      display_name: "Alice",
      email: "alice@example.com",
      role: permissions.length > 0 ? "admin" : "user",
      auth_source: "local",
      permissions,
    },
    ...overrides,
  };
}

export const unauthenticated: Handler = () =>
  Response.json(
    { error: { code: "UNAUTHENTICATED", message: "Sign in required", request_id: "t" } },
    { status: 401 },
  );

export function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <Providers>
      <RouterProvider router={router} />
    </Providers>,
  );
  return router;
}

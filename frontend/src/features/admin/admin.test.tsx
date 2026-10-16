import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderAt, sessionFixture } from "../../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const ADMIN = ["users:read", "users:manage", "groups:read", "groups:manage"];
const page = (items: unknown[]) =>
  Response.json({ items, total: items.length, page: 1, page_size: 25 });
const bob = {
  id: "b1",
  username: "bob",
  email: "bob@example.com",
  display_name: "Bob",
  role: "user",
  status: "active",
  auth_source: "local",
  created_at: "2026-10-01T10:00:00Z",
  last_login_at: null,
};

describe("users administration", () => {
  it("keeps search, filters and sort in the URL and sends them to the API", async () => {
    const api = mockApi({
      "GET /api/v1/auth/session": () => Response.json(sessionFixture({}, ADMIN)),
      "GET /api/v1/admin/users": () => page([bob]),
    });
    const router = renderAt("/admin/users?role=user");
    expect(await screen.findByText("bob")).toBeDefined();
    await userEvent.click(screen.getByRole("button", { name: "Last sign-in" }));
    await waitFor(() => {
      expect(router.state.location.search).toContain("sort=last_login_at");
    });
    expect(router.state.location.search).toContain("role=user");
    const listCalls = api.fetchMock.mock.calls.filter(([input]) =>
      (input as string).startsWith("/api/v1/admin/users"),
    );
    const sent = new URL(listCalls.at(-1)?.[0] as string, "https://x").searchParams;
    expect(sent.get("sort")).toBe("last_login_at");
    expect(sent.get("role")).toBe("user");
  });

  it("creates a user with an idempotency key and CSRF token, then shows the invitation once", async () => {
    const api = mockApi({
      "GET /api/v1/auth/session": () => Response.json(sessionFixture({}, ADMIN)),
      "GET /api/v1/admin/users": () => page([]),
      "POST /api/v1/admin/users": () =>
        Response.json(
          {
            user: bob,
            invitation: {
              url: "https://wiki.example.com/reset-password?token=abc",
              expires_at: "2026-10-20T10:00:00Z",
            },
          },
          { status: 201 },
        ),
    });
    renderAt("/admin/users");
    const [newUser] = await screen.findAllByRole("button", { name: "New user" });
    if (newUser === undefined) throw new Error("New user button missing");
    await userEvent.click(newUser);
    await userEvent.type(screen.getByLabelText(/Username/), "bob");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByDisplayValue("https://wiki.example.com/reset-password?token=abc"),
    ).toBeDefined();
    const create = api.calls.find(
      (call) => call.method === "POST" && call.path === "/api/v1/admin/users",
    );
    const headers = new Headers(create?.init?.headers);
    expect(headers.get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-test-token");
    expect(JSON.parse(create?.init?.body as string)).toEqual({ username: "bob", role: "user" });
  });
});

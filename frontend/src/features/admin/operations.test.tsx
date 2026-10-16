import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderAt, sessionFixture } from "../../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const ADMIN = [
  "dashboard:read",
  "audit:read",
  "audit:export",
  "settings:manage",
  "security:manage",
];
const session = () => Response.json(sessionFixture({}, ADMIN));
const event = {
  id: 7,
  occurred_at: "2026-10-15T08:00:00Z",
  actor: { id: null, username: null },
  actor_ip: "198.51.100.7",
  user_agent: "curl",
  action: "security.honeytoken",
  outcome: "failure",
  severity: "critical",
  target_type: "ip",
  target_id: "198.51.100.7",
  before: null,
  after: { kind: "trap_endpoint", blocked: true },
  request_id: "req-1",
};

describe("audit log", () => {
  it("keeps filters in the URL and exports with the same filters", async () => {
    const api = mockApi({
      "GET /api/v1/auth/session": session,
      "GET /api/v1/admin/audit": () =>
        Response.json({ items: [event], total: 1, page: 1, page_size: 50 }),
      "GET /api/v1/admin/audit/actions": () => Response.json(["auth.login", "security.honeytoken"]),
      "GET /api/v1/admin/audit/export": () =>
        new Response("﻿id\r\n", {
          headers: { "Content-Disposition": 'attachment; filename="audit-1.csv"' },
        }),
    });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const router = renderAt("/admin/audit?severity=critical");
    expect(await screen.findByText("security.honeytoken", { selector: "span" })).toBeDefined();
    await userEvent.selectOptions(screen.getByLabelText("Outcome"), "failure");
    await waitFor(() => {
      expect(router.state.location.search).toContain("outcome=failure");
    });
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await waitFor(() => {
      expect(api.calls.some((call) => call.path === "/api/v1/admin/audit/export")).toBe(true);
    });
    const exportCall = api.fetchMock.mock.calls.find(([input]) =>
      (input as string).startsWith("/api/v1/admin/audit/export"),
    );
    const sent = new URL(exportCall?.[0] as string, "https://x").searchParams;
    expect(sent.get("severity")).toBe("critical");
    expect(sent.get("outcome")).toBe("failure");
    expect(sent.get("page")).toBeNull();
  });
});

describe("settings", () => {
  const webhook = {
    section: "webhook",
    values: { enabled: true, url: "https://hooks.example.com/x", secret: "••••tail", ca_pem: null },
    managed_by_environment: false,
    updated_at: "2026-10-15T08:00:00Z",
    updated_by: "alice",
    info: {},
  };

  it("never sends the masked secret back and keeps it when the field is left empty", async () => {
    const api = mockApi({
      "GET /api/v1/auth/session": session,
      "GET /api/v1/admin/settings/webhook": () => Response.json(webhook),
      "PUT /api/v1/admin/settings/webhook": () => Response.json(webhook),
    });
    renderAt("/admin/settings/webhook");
    const url = await screen.findByLabelText("URL");
    expect(screen.getByLabelText("Signing secret").getAttribute("placeholder")).toBe(
      "••••tail (unchanged)",
    );
    await userEvent.clear(url);
    await userEvent.type(url, "https://hooks.example.com/v2");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.calls.some((call) => call.method === "PUT")).toBe(true);
    });
    const put = api.calls.find((call) => call.method === "PUT");
    const body = JSON.parse(put?.init?.body as string) as Record<string, unknown>;
    expect(body).toEqual({ enabled: true, url: "https://hooks.example.com/v2", ca_pem: null });
  });

  it("shows environment-managed email as read-only", async () => {
    mockApi({
      "GET /api/v1/auth/session": session,
      "GET /api/v1/admin/settings/smtp": () =>
        Response.json({
          section: "smtp",
          values: { enabled: true, host: "smtp.example.com", port: 465, password: "••••" },
          managed_by_environment: true,
          updated_at: null,
          updated_by: null,
          info: {},
        }),
    });
    renderAt("/admin/settings/smtp");
    expect(await screen.findByText("Managed by environment")).toBeDefined();
    expect(screen.getByLabelText<HTMLInputElement>("Host").disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
});

describe("help", () => {
  it("opens the help topic of the current page", async () => {
    mockApi({
      "GET /api/v1/auth/session": session,
      "GET /api/v1/admin/audit": () =>
        Response.json({ items: [], total: 0, page: 1, page_size: 50 }),
      "GET /api/v1/admin/audit/actions": () => Response.json([]),
    });
    const router = renderAt("/admin/audit");
    await userEvent.click(await screen.findByRole("link", { name: "Help for this page" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/help/admin/audit");
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Audit log" })).toBeDefined();
  });

  it("hides administrator topics from users", async () => {
    mockApi({ "GET /api/v1/auth/session": () => Response.json(sessionFixture()) });
    renderAt("/help/admin/audit");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeDefined();
  });
});

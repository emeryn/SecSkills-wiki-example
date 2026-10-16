import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderAt, sessionFixture } from "../../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const key = {
  id: "k1",
  name: "Laptop assistant",
  prefix: "wk_1a2b3c4d",
  scopes: ["pages:read", "pages:write"],
  status: "active",
  created_at: "2026-10-16T08:00:00Z",
  expires_at: "2027-01-14T08:00:00Z",
  last_used_at: null,
};

describe("API keys", () => {
  it("creates a key with the chosen scopes and shows the secret once", async () => {
    const api = mockApi({
      "GET /api/v1/auth/session": () => Response.json(sessionFixture()),
      "GET /api/v1/me/api-keys": () => Response.json([]),
      "POST /api/v1/me/api-keys": () =>
        Response.json({ ...key, secret: "wk_1a2b3c4d_s3cr3t" }, { status: 201 }), // gitleaks:allow
    });
    renderAt("/account?tab=api-keys");
    const [create] = await screen.findAllByRole("button", { name: "New key" });
    if (create === undefined) throw new Error("New key button missing");
    await userEvent.click(create);
    expect(screen.queryByText("admin")).toBeNull();
    await userEvent.type(screen.getByLabelText(/Name/), "Laptop assistant");
    await userEvent.click(screen.getByRole("checkbox", { name: /pages:write/ }));
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByDisplayValue("wk_1a2b3c4d_s3cr3t")).toBeDefined();
    const post = api.calls.find((call) => call.method === "POST");
    expect(JSON.parse(post?.init?.body as string)).toEqual({
      name: "Laptop assistant",
      scopes: ["pages:read", "pages:write"],
      days: 90,
    });
  });

  it("revokes a key after confirmation", async () => {
    const api = mockApi({
      "GET /api/v1/auth/session": () => Response.json(sessionFixture()),
      "GET /api/v1/me/api-keys": () => Response.json([key]),
      "DELETE /api/v1/me/api-keys/k1": () => new Response(null, { status: 204 }),
    });
    renderAt("/account?tab=api-keys");
    await userEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Revoke the key Laptop assistant?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke" }));
    await waitFor(() => {
      expect(api.calls.some((call) => call.method === "DELETE")).toBe(true);
    });
  });
});

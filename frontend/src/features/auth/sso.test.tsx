import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderAt, sessionFixture, unauthenticated } from "../../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

const methods = (oidc: boolean) => () =>
  Response.json({ oidc, oidc_label: "Example ID", directory: false });

describe("single sign-on", () => {
  it("offers the identity provider on the sign-in page, keeping the destination", async () => {
    mockApi({
      "GET /api/v1/auth/session": unauthenticated,
      "GET /api/v1/auth/methods": methods(true),
    });
    renderAt("/login?next=%2Fspaces%2Fdocs");
    const link = await screen.findByRole("link", { name: "Sign in with Example ID" });
    expect(link.getAttribute("href")).toBe("/api/v1/auth/oidc/start?next=%2Fspaces%2Fdocs");
  });

  it("explains a failed single sign-on without details", async () => {
    mockApi({
      "GET /api/v1/auth/session": unauthenticated,
      "GET /api/v1/auth/methods": methods(false),
    });
    renderAt("/login?error=sso");
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Single sign-on did not succeed. Try again, or contact an administrator.",
    );
    expect(screen.queryByRole("link", { name: /Sign in with/ })).toBeNull();
  });

  it("hides password and second factors for SSO accounts", async () => {
    mockApi({
      "GET /api/v1/auth/session": () =>
        Response.json(
          sessionFixture({
            user: { ...sessionFixture().user, auth_source: "oidc" },
          }),
        ),
    });
    renderAt("/account");
    expect(await screen.findByRole("tab", { name: "Sessions" })).toBeDefined();
    expect(screen.queryByRole("tab", { name: "Password" })).toBeNull();
  });
});

describe("OIDC settings", () => {
  const oidc = {
    section: "oidc",
    values: {
      enabled: true,
      display_name: "Example ID",
      issuer: "https://idp.example.com",
      client_id: "wiki",
      client_secret: "••••tail",
      scopes: ["openid", "profile"],
      id_token_algorithm: "RS256",
      username_claim: "preferred_username",
      email_claim: "email",
      name_claim: "name",
      groups_claim: "groups",
      auto_provision: true,
      group_mapping: [
        { group: "cn=eng,ou=groups,dc=example,dc=com", space: "docs", role: "editor" },
      ],
      ca_pem: null,
    },
    managed_by_environment: false,
    managed_fields: ["issuer"],
    updated_at: null,
    updated_by: null,
    info: {},
  };

  it("keeps environment fields read-only and never sends them", async () => {
    const api = mockApi({
      "GET /api/v1/auth/session": () => Response.json(sessionFixture({}, ["settings:manage"])),
      "GET /api/v1/admin/settings/oidc": () => Response.json(oidc),
      "PUT /api/v1/admin/settings/oidc": () => Response.json(oidc),
    });
    renderAt("/admin/settings/oidc");
    const issuer = await screen.findByLabelText<HTMLInputElement>(
      "Issuer URL (set by environment)",
    );
    expect(issuer.disabled).toBe(true);
    const mapping = screen.getByLabelText<HTMLTextAreaElement>("Group to space role mapping");
    expect(mapping.value).toBe("cn=eng,ou=groups,dc=example,dc=com | docs | editor");
    await userEvent.type(mapping, "\nsales | docs | viewer");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(api.calls.some((call) => call.method === "PUT")).toBe(true);
    });
    const body = JSON.parse(
      api.calls.find((call) => call.method === "PUT")?.init?.body as string,
    ) as Record<string, unknown>;
    expect(body).not.toHaveProperty("issuer");
    expect(body).not.toHaveProperty("client_secret");
    expect(body.group_mapping).toEqual([
      { group: "cn=eng,ou=groups,dc=example,dc=com", space: "docs", role: "editor" },
      { group: "sales", space: "docs", role: "viewer" },
    ]);
    expect(screen.getByRole("button", { name: "Test connection" })).toBeDefined();
  });
});

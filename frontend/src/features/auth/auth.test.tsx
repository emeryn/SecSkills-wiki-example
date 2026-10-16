import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderAt, sessionFixture, unauthenticated } from "../../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sign-in", () => {
  it("continues to the second factor and keeps a safe destination", async () => {
    let signedIn = false;
    const api = mockApi({
      "GET /api/v1/auth/session": () =>
        signedIn
          ? Response.json(sessionFixture({ state: "mfa_required", mfa_methods: ["totp"] }))
          : unauthenticated(undefined, new URL("https://x")),
      "POST /api/v1/auth/login": () => {
        signedIn = true;
        return Response.json({ state: "mfa_required", csrf_token: "tok-1" });
      },
    });
    const router = renderAt("/login?next=%2Fadmin%2Fusers");
    await userEvent.type(await screen.findByLabelText(/Username/), "alice");
    await userEvent.type(screen.getByLabelText(/^Password/), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/login/verify");
    });
    expect(router.state.location.search).toBe("?next=%2Fadmin%2Fusers");
    const login = api.calls.find((call) => call.path === "/api/v1/auth/login");
    expect(JSON.parse(login?.init?.body as string)).toEqual({
      username: "alice",
      password: "correct horse battery",
    });
    expect(await screen.findByLabelText(/Authenticator code/)).toBeDefined();
  });

  it("ignores an external next parameter", async () => {
    let signedIn = false;
    mockApi({
      "GET /api/v1/auth/session": () =>
        signedIn
          ? Response.json(sessionFixture())
          : unauthenticated(undefined, new URL("https://x")),
      "POST /api/v1/auth/login": () => {
        signedIn = true;
        return Response.json({ state: "active", csrf_token: "tok-1" });
      },
    });
    const router = renderAt("/login?next=%2F%2Fevil.example");
    await userEvent.type(await screen.findByLabelText(/Username/), "alice");
    await userEvent.type(screen.getByLabelText(/^Password/), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
  });

  it("shows a generic message for invalid credentials", async () => {
    mockApi({
      "GET /api/v1/auth/session": unauthenticated,
      "POST /api/v1/auth/login": () =>
        Response.json(
          { error: { code: "INVALID_CREDENTIALS", message: "x", request_id: "r" } },
          { status: 401 },
        ),
    });
    renderAt("/login");
    await userEvent.type(await screen.findByLabelText(/Username/), "alice");
    await userEvent.type(screen.getByLabelText(/^Password/), "wrong password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toContain(
      "Incorrect username or password.",
    );
  });

  it("validates fields on submit without calling the API", async () => {
    const api = mockApi({ "GET /api/v1/auth/session": unauthenticated });
    renderAt("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect((await screen.findAllByText("This field is required")).length).toBeGreaterThan(0);
    expect(api.calls.some((call) => call.path === "/api/v1/auth/login")).toBe(false);
  });
});

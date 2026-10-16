import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setPrefersDark } from "../test-setup";
import { mockApi, renderAt, sessionFixture, unauthenticated } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function signedIn(permissions: string[] = []) {
  return mockApi({
    "GET /api/v1/auth/session": () => Response.json(sessionFixture({}, permissions)),
  });
}

describe("AppShell", () => {
  it("renders top bar, sidebar navigation, page header and version footer", async () => {
    signedIn();
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toBeDefined();
    expect(screen.getByRole("heading", { level: 1, name: "Dashboard" })).toBeDefined();
    expect(screen.getByText(/^Version /)).toBeDefined();
    expect(screen.getByRole("button", { name: "User menu" }).textContent).toContain("Alice");
  });

  it("hides the admin section without admin permissions", async () => {
    signedIn();
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: "Main navigation" });
    expect(within(nav).queryByRole("link", { name: "Users" })).toBeNull();
  });

  it("shows the admin section with admin permissions", async () => {
    signedIn(["users:read", "groups:read"]);
    renderAt("/");
    const nav = await screen.findByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Users" })).toBeDefined();
    expect(within(nav).getByRole("link", { name: "Groups" })).toBeDefined();
  });

  it("sends signed-out users to sign-in and keeps the requested page", async () => {
    mockApi({ "GET /api/v1/auth/session": unauthenticated });
    const router = renderAt("/account?tab=sessions");
    await screen.findByRole("heading", { name: "Sign in" });
    expect(router.state.location.pathname).toBe("/login");
    expect(router.state.location.search).toBe(
      `?next=${encodeURIComponent("/account?tab=sessions")}`,
    );
  });

  it("sends incomplete sessions to their sign-in step", async () => {
    mockApi({
      "GET /api/v1/auth/session": () =>
        Response.json(sessionFixture({ state: "password_change_required" })),
    });
    const router = renderAt("/");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/setup/password");
    });
  });

  it("hides admin pages from non-admins", async () => {
    signedIn();
    renderAt("/admin/users");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeDefined();
  });

  it("remembers the collapsed sidebar", async () => {
    signedIn();
    renderAt("/");
    await userEvent.click(await screen.findByRole("button", { name: "Collapse sidebar" }));
    expect(window.localStorage.getItem("wiki.sidebar.collapsed")).toBe("true");
  });

  it("opens and closes the navigation drawer with Escape", async () => {
    signedIn();
    renderAt("/");
    await userEvent.click(await screen.findByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("dialog", { name: "Main navigation" })).toBeDefined();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("follows the system theme by default and applies an explicit choice", async () => {
    setPrefersDark(true);
    signedIn();
    renderAt("/");
    await screen.findByRole("navigation", { name: "Main navigation" });
    expect(document.documentElement.dataset.theme).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "User menu" }));
    await userEvent.click(await screen.findByRole("menuitemradio", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("wiki.theme")).toBe("light");
  });
});

import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { demoSpaces, demoUsers, type DemoPage } from "./fixtures/demo-content";
import { totp } from "./tests/totp";

/**
 * README screenshots (scripts/screenshots.sh): signs in as the bootstrap administrator of a fresh
 * stack, seeds the demo content through the API, then captures the main views.
 */
const outputDir = process.env.E2E_SCREENSHOTS_DIR ?? "";
const bootstrapPassword = process.env.E2E_ADMIN_PASSWORD ?? "";
const newPassword = "screenshot operator passphrase 2026";

interface Created {
  id: string;
  slug: string;
}

/** Calls the API from the page, as the SPA does: same origin, session cookie, CSRF token. */
async function api<T>(page: Page, method: string, path: string, body?: unknown): Promise<T> {
  // Stays under the proxy's per-IP API rate.
  await page.waitForTimeout(80);
  return page.evaluate(
    async ({ method, path, body }) => {
      const base = { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" };
      const session = (await (await fetch("/api/v1/auth/session", { headers: base })).json()) as {
        csrf_token: string;
      };
      const response = await fetch(`/api/v1${path}`, {
        method,
        headers: {
          ...base,
          "Content-Type": "application/json",
          "X-CSRF-Token": session.csrf_token,
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`${method} ${path}: ${String(response.status)} ${await response.text()}`);
      return response.status === 204 ? null : ((await response.json()) as unknown);
    },
    { method, path, body },
  ) as Promise<T>;
}

async function createPages(page: Page, space: string, pages: DemoPage[], parentId: string | null) {
  const created: Record<string, Created> = {};
  for (const demo of pages) {
    const result = await api<Created>(page, "POST", `/spaces/${space}/pages`, {
      title: demo.title,
      body: demo.body,
      parent_id: parentId,
    });
    created[demo.title] = result;
    Object.assign(created, await createPages(page, space, demo.children ?? [], result.id));
  }
  return created;
}

async function capture(page: Page, name: string) {
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: join(outputDir, `${name}.png`), animations: "disabled" });
}

test("README screenshots", async ({ page }) => {
  test.skip(outputDir === "" || bootstrapPassword === "", "E2E_SCREENSHOTS_DIR or E2E_ADMIN_PASSWORD not set");
  test.setTimeout(180_000);
  mkdirSync(outputDir, { recursive: true });

  await page.goto("/login");
  await page.getByRole("textbox", { name: "Username", exact: true }).fill("admin");
  await page.getByRole("textbox", { name: "Password", exact: true }).fill(bootstrapPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("textbox", { name: "Current password", exact: true }).fill(bootstrapPassword);
  await page.getByRole("textbox", { name: "New password", exact: true }).fill(newPassword);
  await page.getByRole("textbox", { name: "Confirm new password", exact: true }).fill(newPassword);
  await page.getByRole("button", { name: "Change password" }).click();
  await page.getByRole("button", { name: "Set up an authenticator app" }).click();
  const secret = (await page.locator("code").first().textContent()) ?? "";
  await page.getByRole("textbox", { name: "Authenticator code", exact: true }).fill(totp(secret));
  await page.getByRole("button", { name: "Confirm" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  const me = await api<{ user: { id: string } }>(page, "GET", "/auth/session");
  for (const user of demoUsers) await api(page, "POST", "/admin/users", user);
  const pages: Record<string, Created> = {};
  for (const space of demoSpaces) {
    const created = await api<{ key: string; home_page_id: string }>(page, "POST", "/spaces", {
      name: space.name,
      description: space.description,
      visibility: "internal",
      space_admin_id: me.user.id,
    });
    Object.assign(pages, await createPages(page, created.key, space.pages, created.home_page_id));
  }
  await api(page, "PUT", `/me/favorites/${pages["Release process"]!.id}`);
  await api(page, "PUT", `/me/favorites/${pages["On-call rotation"]!.id}`);

  const releasePath = `/spaces/engineering/pages/${pages["Release process"]!.slug}`;
  await page.goto(releasePath);
  await expect(page.locator(".wiki-content").getByRole("heading", { name: "Checklist" })).toBeVisible();
  await page.getByRole("button", { name: "Expand Release process" }).click();
  await capture(page, "page-view");

  await page.goto(`${releasePath}/edit`);
  await expect(page.getByLabel("Content (Markdown)")).toHaveValue(/Releases ship/);
  await capture(page, "page-editor");

  await page.goto("/admin");
  await expect(page.getByRole("heading", { level: 1, name: "Administration overview" })).toBeVisible();
  await expect(page.getByRole("figure").first()).toBeVisible();
  await capture(page, "admin-dashboard");
});

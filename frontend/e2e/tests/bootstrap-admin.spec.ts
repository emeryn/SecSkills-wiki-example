import { expect, test, type Page } from "@playwright/test";
import { nextStep, totp } from "./totp";

const bootstrapPassword = process.env.E2E_ADMIN_PASSWORD ?? "";
const newPassword = "e2e operator passphrase 2026";
// Shared across the serial tests: the second factor enrolled by the first test.
let totpSecret = "";
// 1×1 PNG.
const PIXEL_PNG =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==";

/** Every page must load without a single CSP or Trusted Types violation. */
async function watchViolations(page: Page): Promise<string[]> {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && /Content Security Policy|TrustedHTML|Trusted Type/i.test(message.text())) {
      violations.push(message.text());
    }
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (event) => {
      console.error(
        `Content Security Policy violation: ${event.violatedDirective} ${event.blockedURI} ` +
          `at ${event.sourceFile}:${String(event.lineNumber)} sample=${event.sample}`,
      );
    });
  });
  return violations;
}

test.describe.serial("bootstrap administrator", () => {
  test.skip(bootstrapPassword === "", "E2E_ADMIN_PASSWORD not set");

  test("first sign-in: forced password change, MFA enrollment, then administration", async ({ page }) => {
    const violations = await watchViolations(page);

    await page.goto("/admin/users");
    await expect(page).toHaveURL(/\/login\?next=%2Fadmin%2Fusers$/);
    await page.getByRole("textbox", { name: "Username", exact: true }).fill("admin");
    await page.getByRole("textbox", { name: "Password", exact: true }).fill(bootstrapPassword);
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByRole("heading", { name: "Choose your own password" })).toBeVisible();
    await page.getByRole("textbox", { name: "Current password", exact: true }).fill(bootstrapPassword);
    await page.getByRole("textbox", { name: "New password", exact: true }).fill(newPassword);
    await page.getByRole("textbox", { name: "Confirm new password", exact: true }).fill(newPassword);
    await page.getByRole("button", { name: "Change password" }).click();

    await expect(page.getByRole("heading", { name: "Protect your account" })).toBeVisible();
    await page.getByRole("button", { name: "Set up an authenticator app" }).click();
    await expect(page.getByRole("img", { name: /QR code/ })).toBeVisible();
    const secret = (await page.locator("code").first().textContent()) ?? "";
    totpSecret = secret;
    await page.getByRole("textbox", { name: "Authenticator code", exact: true }).fill(totp(secret));
    await page.getByRole("button", { name: "Confirm" }).click();

    await expect(page.getByRole("heading", { name: "Save your recovery codes" })).toBeVisible();
    await expect(page.getByRole("listitem")).toHaveCount(10);
    await page.getByRole("button", { name: "Continue" }).click();

    await expect(page).toHaveURL(/\/admin\/users$/);
    await expect(page.getByRole("heading", { level: 1, name: "Users" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "admin", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "New user" }).first().click();
    await page.getByRole("textbox", { name: "Username", exact: true }).fill("carol");
    await page.getByRole("textbox", { name: "Email", exact: true }).fill("carol@example.com");
    await page.getByRole("button", { name: "Create" }).click();
    const invitation = page.getByRole("textbox", { name: "Invitation link" });
    await expect(invitation).toHaveValue(/\/reset-password\?token=/);
    await page.keyboard.press("Escape");
    await expect(page.getByRole("cell", { name: "carol", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "User menu" }).click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);

    expect(violations).toEqual([]);
  });

  test("spaces and pages: create, render safely, edit, history, favorites, trash", async ({ page }) => {
    const violations = await watchViolations(page);
    const dialogs: string[] = [];
    page.on("dialog", (dialog) => {
      dialogs.push(dialog.message());
      void dialog.dismiss();
    });
    const remoteRequests: string[] = [];
    page.on("request", (request) => {
      if (!request.url().startsWith("https://localhost")) remoteRequests.push(request.url());
    });

    await page.goto("/login");
    await page.getByRole("textbox", { name: "Username", exact: true }).fill("admin");
    await page.getByRole("textbox", { name: "Password", exact: true }).fill(newPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("textbox", { name: "Authenticator code", exact: true }).fill(totp(totpSecret, 1));
    await page.getByRole("button", { name: "Verify" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();

    await page.goto("/admin/spaces");
    await page.getByRole("button", { name: "New space" }).first().click();
    await page.getByRole("textbox", { name: "Name", exact: true }).fill("Engineering");
    await page.getByRole("textbox", { name: "Space administrator", exact: true }).fill("ad");
    await page.getByRole("button", { name: "admin", exact: true }).click();
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/spaces\/engineering\/settings$/);

    await page.goto("/spaces/engineering");
    await expect(page).toHaveURL(/\/spaces\/engineering\/pages\/engineering$/);
    await page.getByRole("link", { name: "New page" }).click();
    await page.getByRole("textbox", { name: "Title", exact: true }).fill("Getting Started");
    await page.getByLabel("Content (Markdown)").fill(
      [
        "## Welcome",
        "See [[Engineering]] and [[Nowhere]].",
        "",
        "<img src=x onerror=alert(1)>",
        "",
        "[click me](javascript:alert(1))",
        "",
        "![tracker](https://evil.example/pixel.png)",
      ].join("\n"),
    );
    await page.getByLabel("Content (Markdown)").press("Control+s");

    await expect(page).toHaveURL(/\/spaces\/engineering\/pages\/getting-started$/);
    const content = page.locator(".wiki-content");
    await expect(content.getByRole("heading", { name: "Welcome" })).toBeVisible();
    await expect(content.getByRole("link", { name: "Engineering" })).toHaveAttribute("href", "/spaces/engineering/pages/engineering");
    await expect(content.locator(".wiki-link-broken")).toHaveText("Nowhere");
    await expect(content.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
    await expect(content.getByText("click me")).not.toHaveAttribute("href", /javascript/);
    await expect(content.locator("img[src]")).toHaveCount(0);

    await page.getByRole("link", { name: "Edit" }).click();
    await page.getByLabel("Content (Markdown)").fill("## Welcome\nUpdated text.");
    await page.getByRole("textbox", { name: "Change summary", exact: true }).fill("Rewrite");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(content.getByText("Updated text.")).toBeVisible();

    await page.getByRole("button", { name: "Page actions" }).click();
    await page.getByRole("menuitem", { name: "History" }).click();
    await page.getByRole("radio", { name: "Compare from revision 1" }).check();
    await page.getByRole("radio", { name: "Compare to revision 2" }).check();
    await expect(page.getByLabel("Differences")).toContainText("Updated text.");

    await page.getByRole("link", { name: "Getting Started" }).first().click();
    await page.getByRole("button", { name: "Add to favorites" }).click();
    const sidebar = page.getByRole("navigation", { name: "Main navigation" });
    await expect(sidebar.getByRole("link", { name: "Getting Started" })).toBeVisible();

    // Attachment: uploaded from the editor, embedded, rendered from the same origin.
    await page.getByRole("link", { name: "Edit" }).click();
    await page.locator('input[type="file"]').setInputFiles({ name: "pixel.png", mimeType: "image/png", buffer: Buffer.from(PIXEL_PNG, "base64") });
    await expect(page.getByLabel("Content (Markdown)")).toHaveValue(/!\[pixel\.png\]\(\/api\/v1\/attachments\/[0-9a-f-]{36}\)/);
    await page.getByRole("button", { name: "Save" }).click();
    const image = content.locator('img[src^="/api/v1/attachments/"]');
    await expect(image).toBeVisible();
    expect(await image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    await expect(page.getByRole("heading", { name: "Attachments" })).toBeVisible();

    // Search from the top bar.
    await page.keyboard.press("Control+k");
    await page.getByRole("searchbox", { name: "Search pages" }).fill("updated");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("link", { name: "Getting Started" }).last()).toBeVisible();
    await expect(page.locator("mark").first()).toHaveText(/updated/i);
    await page.getByRole("main").getByRole("link", { name: "Getting Started" }).click();

    // Export of the whole space.
    const downloading = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export space" }).click();
    const download = await downloading;
    expect(download.suggestedFilename()).toMatch(/^engineering-\d{8}\.zip$/);

    await page.getByRole("button", { name: "Page actions" }).click();
    await page.getByRole("menuitem", { name: "Delete" }).click();
    await page.getByRole("button", { name: "Move to trash" }).click();
    await expect(page).toHaveURL(/\/spaces\/engineering\/pages\/engineering$/);
    await page.getByRole("link", { name: "Trash" }).click();
    await page.getByRole("button", { name: "Restore" }).click();
    await expect(page.getByText("The trash is empty")).toBeVisible();

    expect(dialogs).toEqual([]);
    expect(remoteRequests).toEqual([]);
    expect(violations).toEqual([]);
  });

  test("operations: dashboard, audit log and export, settings, help", async ({ page }) => {
    // The previous sign-in used the next TOTP step; wait for a step it cannot have used.
    test.setTimeout(90_000);
    await nextStep();
    const violations = await watchViolations(page);
    await page.goto("/login?next=%2Fadmin");
    await page.getByRole("textbox", { name: "Username", exact: true }).fill("admin");
    await page.getByRole("textbox", { name: "Password", exact: true }).fill(newPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("textbox", { name: "Authenticator code", exact: true }).fill(totp(totpSecret, 1));
    await page.getByRole("button", { name: "Verify" }).click();

    await expect(page.getByRole("heading", { level: 1, name: "Administration overview" })).toBeVisible();
    await expect(page.getByRole("figure").first()).toBeVisible();
    await page.getByRole("link", { name: /Failed sign-ins/ }).click();
    await expect(page).toHaveURL(/\/admin\/audit\?action=auth\.login&outcome=failure/);

    await page.goto("/admin/audit?action=backup.created");
    await page.getByRole("cell", { name: "backup.created" }).first().click();
    await expect(page.getByRole("dialog")).toContainText("Request ID");
    await page.keyboard.press("Escape");
    const downloading = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export CSV" }).click();
    expect((await downloading).suggestedFilename()).toMatch(/^audit-\d{8}-\d{6}\.csv$/);

    await page.goto("/admin/settings/privacy");
    await page.getByRole("checkbox", { name: /Mask personal data/ }).check();
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Changes saved")).toBeVisible();
    await page.getByRole("button", { name: "Reset to default" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Reset to default" }).click();
    await expect(page.getByRole("checkbox", { name: /Mask personal data/ })).not.toBeChecked();

    await page.getByRole("link", { name: "Security" }).click();
    await expect(page.getByText("No blocked IP addresses")).toBeVisible();
    await page.getByRole("link", { name: "Help for this page" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();

    expect(violations).toEqual([]);
  });

  test("security headers are present on the application page", async ({ page }) => {
    const response = await page.goto("/login");
    const headers = response?.headers() ?? {};
    expect(headers["content-security-policy"]).toContain("require-trusted-types-for 'script'");
    expect(headers["x-frame-options"]).toBe("DENY");
  });
});

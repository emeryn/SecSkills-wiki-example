import { defineConfig } from "@playwright/test";

/**
 * Runs against a live stack (scripts/e2e.sh). The browser reaches the proxy at the public URL,
 * so Origin checks, cookies, CSP and Trusted Types behave as in production.
 */
export default defineConfig({
  projects: [
    { name: "e2e", testDir: "./tests" },
    // README screenshots (scripts/screenshots.sh); skipped unless E2E_SCREENSHOTS_DIR is set.
    { name: "screenshots", testDir: ".", testMatch: "screenshots.spec.ts" },
  ],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "./test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "https://localhost:8443",
    // The generated internal CA is not in the browser trust store.
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 900 },
    locale: "en-US",
    colorScheme: "light",
    trace: "retain-on-failure",
  },
});

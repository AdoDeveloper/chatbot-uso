import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for E2E smoke tests.
 *
 * Default base URL hits the docker-compose frontend (port 3000). Override
 * with `PLAYWRIGHT_BASE_URL` if you're running against a deployed environment.
 *
 * Run with `npm run test:e2e`. The frontend and backend containers must be up.
 */
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});

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
  // 1 worker en CI: el runner de GitHub Actions tiene solo 2 vCPU y ya corre
  // el stack de 5 contenedores Docker. Con 2 workers, dos Chromium arrancan
  // a la vez justo cuando el stack recién terminó de levantar, y el primer
  // test puede toparse con contención de CPU que Chromium reporta como
  // chrome-error://chromewebdata/ en vez de un timeout normal - el healthcheck
  // y un curl aislado pasan bien porque no compiten por el mismo CPU.
  workers: process.env.CI ? 1 : 2,
  reporter: [["list"], ["html", { open: "never" }]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    // Margen extra sobre el default (30s) para la navegación y las acciones
    // en CI, por la misma razón: el primer request real puede coincidir con
    // el pico de CPU de Docker + Chromium arrancando.
    navigationTimeout: process.env.CI ? 45_000 : undefined,
    actionTimeout: process.env.CI ? 15_000 : undefined,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});

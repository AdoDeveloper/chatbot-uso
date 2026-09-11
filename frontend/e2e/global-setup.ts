import { chromium, type FullConfig } from "@playwright/test";

/**
 * Logs in once via the real UI form and persists the resulting cookies to
 * disk. Every spec that sets `storageState` to this file starts already
 * authenticated, avoiding a repeated login flow per test.
 *
 * Skips silently when E2E_USER / E2E_PASS aren't set - specs that depend on
 * the auth state file should gate on the same env vars.
 */
export default async function globalSetup(config: FullConfig) {
  const { E2E_USER, E2E_PASS } = process.env;
  if (!E2E_USER || !E2E_PASS) return;

  const baseURL = config.projects[0].use.baseURL ?? "http://localhost:3000";
  const browser = await chromium.launch();
  const page = await browser.newPage({ baseURL });

  await page.goto("/login");
  await page.locator('input[type="email"]').fill(E2E_USER);
  await page.locator('input#login-password').fill(E2E_PASS);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/dashboard|\/cambiar-contrasena/, { timeout: 10_000 });

  // Un admin recién sembrado (ej. el que crea el backend al primer arranque
  // en CI) trae must_change_password=true y el login lo manda aquí en vez
  // de a /dashboard. El backend rechaza la nueva contraseña si es igual a
  // la actual, así que hay que generar una distinta - no importa cuál
  // quede después: el resto de specs reutiliza las cookies persistidas
  // más abajo, no vuelve a loguearse con E2E_PASS.
  if (page.url().includes("/cambiar-contrasena")) {
    const rotatedPassword = `${E2E_PASS}Aa1`;
    await page.locator("#current_password").fill(E2E_PASS);
    await page.locator("#new_password").fill(rotatedPassword);
    await page.locator("#confirm_password").fill(rotatedPassword);
    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/auth/change-password")),
      page.locator('button[type="submit"]').click(),
    ]);
    if (!response.ok()) {
      const body = await response.text().catch(() => "<no body>");
      throw new Error(`change-password devolvió ${response.status()}: ${body}`);
    }
    await page.waitForURL(/\/dashboard/, { timeout: 10_000 });
  }

  await page.context().storageState({ path: "e2e/.auth/admin.json" });
  await browser.close();
}

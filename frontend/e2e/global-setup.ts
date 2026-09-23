import { chromium, type FullConfig } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

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

  if (page.url().includes("/cambiar-contrasena")) {
    const rotatedPassword = `${E2E_PASS}Aa1`;

    await page.locator("#current_password").fill(E2E_PASS);
    await page.locator("#new_password").fill(rotatedPassword);
    await page.locator("#confirm_password").fill(rotatedPassword);

    const submitBtn = page.locator('button[type="submit"]');
    await submitBtn.waitFor({ state: "visible", timeout: 5_000 });

    const [response] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/auth/change-password"), { timeout: 15_000 }),
      submitBtn.click(),
    ]);
    if (!response.ok()) {
      const body = await response.text().catch(() => "<no body>");
      throw new Error(`change-password devolvió ${response.status()}: ${body}`);
    }
    await page.waitForURL(/\/dashboard/, { timeout: 10_000 });

    mkdirSync("e2e/.auth", { recursive: true });
    writeFileSync("e2e/.auth/admin-password.json", JSON.stringify({ password: rotatedPassword }));
  }

  await page.context().storageState({ path: "e2e/.auth/admin.json" });
  await browser.close();
}

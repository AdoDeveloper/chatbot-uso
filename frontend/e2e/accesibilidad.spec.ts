import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

/**
 * Automated a11y audit via axe-core on a representative sample: the public
 * login page, the main dashboard, and one data-heavy admin form (usuarios).
 * Flags only serious/critical violations - axe surfaces some "moderate"
 * findings (color contrast on decorative elements, etc.) that don't block
 * usability and would make this test too noisy to keep green.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.describe("Accesibilidad - login (no auth needed)", () => {
  test("login page has no serious/critical a11y violations", async ({ page }) => {
    await page.goto("/login");
    const results = await new AxeBuilder({ page })
      .include("body")
      .analyze();

    const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([]);
  });
});

test.describe("Accesibilidad - dashboard autenticado", () => {
  test.use({ storageState: "e2e/.auth/admin.json" });
  test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

  test("main dashboard has no serious/critical a11y violations", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.locator(".animate-spin")).toHaveCount(0, { timeout: 20_000 });
    const results = await new AxeBuilder({ page }).include("body").analyze();
    const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([]);
  });

  test("usuarios form has no serious/critical a11y violations", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/usuarios");
    await expect(page.locator(".animate-spin")).toHaveCount(0, { timeout: 20_000 });
    const results = await new AxeBuilder({ page }).include("body").analyze();
    const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(blocking, JSON.stringify(blocking, null, 2)).toEqual([]);
  });
});

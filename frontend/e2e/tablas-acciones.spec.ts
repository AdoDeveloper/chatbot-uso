import { test, expect } from "@playwright/test";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const TABLES: { route: string; name: string }[] = [
  { route: "/dashboard/configuracion/acceso/usuarios", name: "usuarios" },
  { route: "/dashboard/conocimiento/documentos", name: "documentos" },
];

test.describe("Columna de Acciones - visual regression", () => {
  for (const { route, name } of TABLES) {
    test(`acciones column renders without overflow - ${name}`, async ({ page }) => {
      await page.goto(route);
      const table = page.locator("table").first();
      await expect(table).toBeVisible({ timeout: 10_000 });

      const lastColumnCells = page.locator("table tbody tr td:last-child");
      await expect(lastColumnCells.first()).toBeVisible();

      await expect(table).toHaveScreenshot(`acciones-${name}.png`, {
        maxDiffPixelRatio: 0.02,
      });
    });
  }
});

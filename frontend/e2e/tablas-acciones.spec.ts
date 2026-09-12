import { test, expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

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
      // "documentos" corre al final de la suite y puede quedar sin filas si
      // otros specs ya borraron sus fuentes desechables - sube y deja lista
      // una propia para garantizar que la tabla (no el EmptyState) sea lo
      // que se renderiza, sin depender del estado que dejen otros specs.
      let sourceName: string | null = null;
      if (name === "documentos") {
        sourceName = `E2E Tabla Acciones ${Date.now()}`;
        const filePath = path.join(os.tmpdir(), `e2e-tabla-acciones-${Date.now()}.txt`);
        fs.writeFileSync(filePath, "Contenido de prueba E2E para verificar la columna de acciones.");

        await page.goto(route);
        // .first(): si la tabla está vacía, el EmptyState agrega su propio
        // botón "Agregar" además del de la cabecera.
        await page.getByRole("button", { name: /^agregar$/i }).first().click();
        const uploadDialog = page.getByRole("dialog");
        await uploadDialog.locator('input[type="file"]').setInputFiles(filePath);
        await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(sourceName);
        await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
        await expect(uploadDialog).not.toBeVisible({ timeout: 15_000 });
        const row = page.locator("tr", { hasText: sourceName });
        await expect(row.getByText("Listo", { exact: true })).toBeVisible({ timeout: 60_000 });
        fs.unlinkSync(filePath);
      }

      await page.goto(route);
      const table = page.locator("table").first();
      await expect(table).toBeVisible({ timeout: 10_000 });

      const lastColumnCells = page.locator("table tbody tr td:last-child");
      await expect(lastColumnCells.first()).toBeVisible();

      await expect(table).toHaveScreenshot(`acciones-${name}.png`, {
        maxDiffPixelRatio: 0.02,
      });

      if (sourceName) {
        const row = page.locator("tr", { hasText: sourceName });
        await row.getByRole("button").last().click();
        await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
        const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
        await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
        await expect(page.locator("tr", { hasText: sourceName })).toHaveCount(0, { timeout: 10_000 });
      }
    });
  }
});

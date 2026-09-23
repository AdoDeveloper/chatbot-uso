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
      let sourceName: string | null = null;
      if (name === "documentos") {
        const stamp = Date.now();
        sourceName = `E2E Tabla Acciones ${stamp}`;
        const filePath = path.join(os.tmpdir(), `e2e-tabla-acciones-${stamp}.txt`);
        fs.writeFileSync(filePath, `Contenido de prueba E2E ${stamp} para verificar la columna de acciones.`);

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

      // Verificación directa del desbordamiento en vez de una captura de toda
      // la tabla: la captura cambiaba con cada alta o baja de filas reales.
      const overflow = await page.evaluate(() => {
        const tableBox = document.querySelector("table")!.getBoundingClientRect();
        const problems: string[] = [];
        document.querySelectorAll<HTMLElement>("table tbody tr td:last-child").forEach((cell, i) => {
          if (cell.scrollWidth > cell.clientWidth + 1) problems.push(`fila ${i}: contenido desbordado`);
          cell.querySelectorAll("button, a").forEach((el) => {
            const r = el.getBoundingClientRect();
            if (r.right > tableBox.right + 1 || r.left < tableBox.left - 1) problems.push(`fila ${i}: acción fuera de la tabla`);
          });
        });
        return problems;
      });
      expect(overflow).toEqual([]);

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

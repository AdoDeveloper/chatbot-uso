import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

/**
 * Functional coverage for the bulk-delete action on
 * /dashboard/conocimiento/documentos (POST /sources/bulk/delete): uploads
 * two small disposable sources, selects both via their row checkboxes, and
 * deletes them together through the real bulk endpoint. Only ever acts on
 * sources this test itself created.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "conocimiento-bulk-delete");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test("seleccionar y eliminar varias fuentes en lote", async ({ page }) => {
  test.setTimeout(90_000);
  const uniqueId = Date.now();
  const names = [`E2E Bulk A ${uniqueId}`, `E2E Bulk B ${uniqueId}`];
  const filePaths = names.map((_, i) => path.join(os.tmpdir(), `e2e-bulk-${uniqueId}-${i}.txt`));

  for (let i = 0; i < names.length; i++) {
    fs.writeFileSync(filePaths[i], `Documento de prueba E2E para borrado en lote ${uniqueId}-${i}. `.repeat(10));
  }

  await page.goto("/dashboard/conocimiento/documentos");
  await expect(page.getByRole("tab", { name: /fuentes/i })).toBeVisible({ timeout: 10_000 });

  for (let i = 0; i < names.length; i++) {
    await page.getByRole("button", { name: /^agregar$/i }).click();
    const uploadDialog = page.getByRole("dialog");
    await uploadDialog.locator('input[type="file"]').setInputFiles(filePaths[i]);
    await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(names[i]);
    await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(uploadDialog).not.toBeVisible({ timeout: 15_000 });
    await expect(page.locator("tr", { hasText: names[i] })).toBeVisible({ timeout: 15_000 });
  }
  await page.screenshot({ path: path.join(SHOT_DIR, "01-dos-fuentes-creadas.png") });

  for (const name of names) {
    const row = page.locator("tr", { hasText: name });
    await row.locator('input[type="checkbox"]').check();
  }
  await expect(page.getByText(/2 seleccionadas/i)).toBeVisible({ timeout: 5_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "02-dos-seleccionadas.png") });

  await page.getByRole("button", { name: /^eliminar$/i }).click();
  const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
  await expect(confirmDialog.getByRole("heading")).toContainText(/eliminar 2 fuentes/i);
  await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();

  for (const name of names) {
    await expect(page.locator("tr", { hasText: name })).toHaveCount(0, { timeout: 15_000 });
  }
  await page.screenshot({ path: path.join(SHOT_DIR, "03-eliminadas-en-lote.png") });

  for (const p of filePaths) fs.unlinkSync(p);
});

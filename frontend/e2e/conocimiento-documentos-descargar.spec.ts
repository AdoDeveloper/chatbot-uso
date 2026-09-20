import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

/**
 * Coverage for GET /sources/{id}/download ("Descargar original" en el menu
 * de una fila), no cubierto por conocimiento-documentos.spec.ts. Sube una
 * fuente desechable propia, descarga el archivo original y confirma que el
 * contenido descargado coincide con el subido, luego la elimina.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

test("descargar el archivo original de una fuente", async ({ page }) => {
  test.setTimeout(90_000);
  const uniqueId = Date.now();
  const sourceName = `E2E Download Source ${uniqueId}`;
  const content = `Contenido unico E2E ${uniqueId} para verificar la descarga del archivo original.`;
  const filePath = path.join(os.tmpdir(), `e2e-download-${uniqueId}.txt`);
  fs.writeFileSync(filePath, content);

  await page.goto("/dashboard/conocimiento/documentos");
  await expect(page.getByRole("tab", { name: /fuentes/i })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: /^agregar$/i }).first().click();
  const uploadDialog = page.getByRole("dialog");
  await uploadDialog.locator('input[type="file"]').setInputFiles(filePath);
  await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(sourceName);
  await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
  await expect(uploadDialog).not.toBeVisible({ timeout: 15_000 });
  const row = page.locator("tr", { hasText: sourceName });
  await expect(row.getByText("Listo", { exact: true })).toBeVisible({ timeout: 60_000 });

  await row.getByRole("button").last().click();
  const [download] = await Promise.all([
    page.waitForEvent("download", { timeout: 15_000 }),
    page.getByRole("menuitem", { name: /descargar original/i }).click(),
  ]);
  const downloadedPath = await download.path();
  expect(downloadedPath).toBeTruthy();
  const downloadedContent = fs.readFileSync(downloadedPath!, "utf-8");
  expect(downloadedContent).toBe(content);

  await row.getByRole("button").last().click();
  await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
  const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
  await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
  await expect(page.locator("tr", { hasText: sourceName })).toHaveCount(0, { timeout: 10_000 });

  fs.unlinkSync(filePath);
});

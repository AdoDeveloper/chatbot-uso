import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

/**
 * Functional coverage for the bulk "Reingestar" and "+Tag"/"−Tag" actions
 * on /dashboard/conocimiento/documentos (POST /sources/bulk/reingest and
 * POST /sources/bulk/tag), the sources-page counterparts of the already-
 * covered bulk-delete (conocimiento-bulk-delete.spec.ts). Uploads two
 * disposable sources, only ever acts on sources this test itself created,
 * and deletes them at the end via the same bulk-delete flow.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

test("reingestar y etiquetar varias fuentes en lote", async ({ page }) => {
  test.setTimeout(90_000);
  const uniqueId = Date.now();
  const names = [`E2E BulkTag A ${uniqueId}`, `E2E BulkTag B ${uniqueId}`];
  const filePaths = names.map((_, i) => path.join(os.tmpdir(), `e2e-bulktag-${uniqueId}-${i}.txt`));

  for (let i = 0; i < names.length; i++) {
    fs.writeFileSync(filePaths[i], `Documento de prueba E2E para reingest/tag en lote ${uniqueId}-${i}. `.repeat(10));
  }

  await page.goto("/dashboard/conocimiento/documentos");
  await expect(page.getByRole("tab", { name: /fuentes/i })).toBeVisible({ timeout: 10_000 });

  for (let i = 0; i < names.length; i++) {
    await page.getByRole("button", { name: /^agregar$/i }).first().click();
    const uploadDialog = page.getByRole("dialog");
    await uploadDialog.locator('input[type="file"]').setInputFiles(filePaths[i]);
    await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(names[i]);
    await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(uploadDialog).not.toBeVisible({ timeout: 15_000 });
    await expect(page.locator("tr", { hasText: names[i] })).toBeVisible({ timeout: 15_000 });
  }

  for (const name of names) {
    await page.locator("tr", { hasText: name }).locator('input[type="checkbox"]').check();
  }
  await expect(page.getByText(/2 seleccionadas/i)).toBeVisible({ timeout: 5_000 });

  // Reingestar: ambas fuentes recien subidas quedan "pendiente_revision"
  // (no aprobadas), asi que corre sin dialogo de confirmacion adicional
  // (ese solo aparece si alguna seleccionada ya esta aprobada y en uso).
  const [reingestResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/v1/sources/bulk/reingest") && r.request().method() === "POST"),
    page.getByRole("button", { name: /^reingestar$/i }).click(),
  ]);
  expect(reingestResp.status(), `unexpected bulk/reingest status: ${reingestResp.status()}`).toBe(200);

  for (const name of names) {
    await expect(page.locator("tr", { hasText: name }).getByText("Listo", { exact: true })).toBeVisible({ timeout: 30_000 });
    await page.locator("tr", { hasText: name }).locator('input[type="checkbox"]').check();
  }
  await expect(page.getByText(/2 seleccionadas/i)).toBeVisible({ timeout: 10_000 });

  const disposableTag = `e2e-bulk-tag-${uniqueId}`;
  const tagInput = page.getByPlaceholder("tag...");
  await tagInput.fill(disposableTag);
  const [addTagResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/v1/sources/bulk/tag") && r.request().method() === "POST"),
    page.getByRole("button", { name: /^\+tag$/i }).click(),
  ]);
  expect(addTagResp.status(), `unexpected bulk/tag (add) status: ${addTagResp.status()}`).toBe(200);
  await expect(page.getByText(disposableTag).first()).toBeVisible({ timeout: 10_000 });

  for (const name of names) {
    await page.locator("tr", { hasText: name }).locator('input[type="checkbox"]').check();
  }
  await expect(page.getByText(/2 seleccionadas/i)).toBeVisible({ timeout: 5_000 });
  await tagInput.fill(disposableTag);
  const [removeTagResp] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/v1/sources/bulk/tag") && r.request().method() === "POST"),
    page.getByRole("button", { name: /^−tag$/i }).click(),
  ]);
  expect(removeTagResp.status(), `unexpected bulk/tag (remove) status: ${removeTagResp.status()}`).toBe(200);

  // Limpieza: mismo flujo que conocimiento-bulk-delete.spec.ts.
  for (const name of names) {
    await page.locator("tr", { hasText: name }).locator('input[type="checkbox"]').check();
  }
  await expect(page.getByText(/2 seleccionadas/i)).toBeVisible({ timeout: 5_000 });
  await page.getByRole("button", { name: /^eliminar$/i }).click();
  const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
  await expect(confirmDialog.getByRole("heading")).toContainText(/eliminar 2 fuentes/i);
  await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
  for (const name of names) {
    await expect(page.locator("tr", { hasText: name })).toHaveCount(0, { timeout: 15_000 });
  }

  for (const p of filePaths) fs.unlinkSync(p);
});

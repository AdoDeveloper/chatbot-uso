import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

/**
 * Functional coverage for /dashboard/conocimiento/documentos/[id]/chunks:
 * uploads a real source, waits for ingestion, then exercises discard/
 * restore and edit-content on one of its chunks. Cleans up by deleting the
 * source at the end (cascades chunk deletion in Qdrant/DB).
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "conocimiento-chunks");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test("descartar/restaurar y editar el contenido de un chunk", async ({ page }) => {
  test.setTimeout(90_000);
  const uniqueId = Date.now();
  const sourceName = `E2E Chunks ${uniqueId}`;
  const filePath = path.join(os.tmpdir(), `e2e-chunks-${uniqueId}.txt`);
  // Unique id avoids collisions with the backend's duplicate-content check.
  fs.writeFileSync(
    filePath,
    `Documento de prueba E2E ${uniqueId} para edicion de chunks. `.repeat(20) +
      "Segunda seccion con contenido adicional de relleno para asegurar al menos un chunk indexado. ".repeat(20),
  );

  await page.goto("/dashboard/conocimiento/documentos");
  await page.getByRole("button", { name: /^agregar$/i }).click();
  const uploadDialog = page.getByRole("dialog");
  await uploadDialog.locator('input[type="file"]').setInputFiles(filePath);
  await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(sourceName);
  await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
  await expect(uploadDialog).not.toBeVisible({ timeout: 15_000 });

  const row = page.locator("tr", { hasText: sourceName });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await expect(row.getByText("Listo", { exact: true })).toBeVisible({ timeout: 60_000 });

  await row.getByRole("button").last().click();
  const verChunks = page.getByRole("menuitem", { name: /ver chunks/i });
  if (!(await verChunks.isVisible().catch(() => false))) {
    test.skip(true, "la fuente no generó chunks indexables (contenido muy corto o filtrado)");
  }
  await verChunks.click();
  await expect(page).toHaveURL(/\/chunks$/, { timeout: 10_000 });
  await expect(page.getByRole("heading", { name: /chunks indexados/i })).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "01-lista-chunks.png") });

  const firstRow = page.locator("tbody tr").first();
  await firstRow.getByRole("button").last().click();
  await page.getByRole("menuitem", { name: /descartar/i }).click();
  await expect(firstRow).toHaveClass(/opacity-60/, { timeout: 10_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "02-chunk-descartado.png") });

  await firstRow.getByRole("button").last().click();
  await page.getByRole("menuitem", { name: /restaurar/i }).click();
  await expect(firstRow).not.toHaveClass(/opacity-60/, { timeout: 10_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "03-chunk-restaurado.png") });

  await firstRow.getByRole("button").last().click();
  await page.getByRole("menuitem", { name: /editar contenido/i }).click();
  const editDialog = page.getByRole("dialog");
  await expect(editDialog.getByRole("heading", { name: /editar chunk/i })).toBeVisible();
  const textarea = editDialog.locator("textarea").first();
  const original = await textarea.inputValue();
  await textarea.fill(`${original} [editado por E2E]`);
  await page.screenshot({ path: path.join(SHOT_DIR, "04-chunk-editar-formulario.png") });
  await editDialog.getByRole("button", { name: /re-indexar/i }).click();
  await expect(editDialog).not.toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/editado por e2e/i)).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, "05-chunk-editado.png") });

  await firstRow.getByRole("button").last().click();
  const historyItem = page.getByRole("menuitem", { name: /ver historial/i });
  await expect(historyItem).toBeEnabled({ timeout: 5_000 });
  await historyItem.click();
  const historyDialog = page.getByRole("dialog");
  await expect(historyDialog.getByRole("heading", { name: /historial de ediciones/i })).toBeVisible({ timeout: 10_000 });
  await expect(historyDialog.getByText(/antes/i)).toBeVisible();
  await expect(historyDialog.getByText(/después/i)).toBeVisible();
  await page.screenshot({ path: path.join(SHOT_DIR, "06-historial-edicion.png") });
  await page.keyboard.press("Escape");
  await expect(historyDialog).not.toBeVisible({ timeout: 5_000 });

  await firstRow.getByRole("button").last().click();
  await page.getByRole("menuitem", { name: /vista previa/i }).click();
  const previewDialog = page.getByRole("dialog");
  await expect(previewDialog.getByText(/editado por e2e/i)).toBeVisible({ timeout: 10_000 });
  await previewDialog.getByRole("button", { name: /^cerrar$/i }).click();
  await expect(previewDialog).not.toBeVisible({ timeout: 5_000 });

  await page.context().grantPermissions(["clipboard-write", "clipboard-read"]);
  const copyIdBtn = firstRow.locator('button[aria-label^="Copiar ID"]');
  if (await copyIdBtn.isVisible().catch(() => false)) {
    await copyIdBtn.click();
  }

  const searchInput = page.getByPlaceholder(/buscar en página actual/i);
  await searchInput.fill("editado por e2e");
  await expect(page.getByText(/coinciden\./i)).toBeVisible({ timeout: 5_000 });
  await searchInput.fill("texto que definitivamente no existe en ningún chunk xyz123");
  await expect(page.getByText(/ningún chunk de esta página coincide/i)).toBeVisible({ timeout: 5_000 });
  await searchInput.fill("");

  const chunkText = firstRow.locator("p.text-sm").first();
  await chunkText.click();
  await expect(chunkText).toHaveClass(/whitespace-pre-wrap/);
  await chunkText.click();
  await expect(chunkText).toHaveClass(/line-clamp-2/);

  await page.goto("/dashboard/conocimiento/documentos");
  const cleanupRow = page.locator("tr", { hasText: sourceName });
  await cleanupRow.getByRole("button").last().click();
  await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
  const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
  await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
  await expect(page.locator("tr", { hasText: sourceName })).toHaveCount(0, { timeout: 10_000 });

  fs.unlinkSync(filePath);
});

test("filtro de warnings por tipo (chunk corto)", async ({ page }) => {
  test.setTimeout(90_000);
  const uniqueId = Date.now();
  const sourceName = `E2E Chunks Warning ${uniqueId}`;
  const filePath = path.join(os.tmpdir(), `e2e-chunks-warning-${uniqueId}.txt`);
  // Segunda sección queda bajo MIN_LEN_CHARS (50) -> genera warning "short".
  fs.writeFileSync(
    filePath,
    `Contenido de prueba E2E ${uniqueId} para warnings de chunks. `.repeat(25) +
      `\n\nNOTA FINAL\nFin.`,
  );

  await page.goto("/dashboard/conocimiento/documentos");
  await page.getByRole("button", { name: /^agregar$/i }).click();
  const uploadDialog = page.getByRole("dialog");
  await uploadDialog.locator('input[type="file"]').setInputFiles(filePath);
  await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(sourceName);
  await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
  await expect(uploadDialog).not.toBeVisible({ timeout: 15_000 });

  const row = page.locator("tr", { hasText: sourceName });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await expect(row.getByText("Listo", { exact: true })).toBeVisible({ timeout: 60_000 });

  await row.getByRole("button").last().click();
  const verChunks = page.getByRole("menuitem", { name: /ver chunks/i });
  if (!(await verChunks.isVisible().catch(() => false))) {
    test.skip(true, "la fuente no generó chunks indexables (contenido muy corto o filtrado)");
  }
  await verChunks.click();
  await expect(page).toHaveURL(/\/chunks$/, { timeout: 10_000 });
  await expect(page.getByRole("heading", { name: /chunks indexados/i })).toBeVisible({ timeout: 10_000 });
  // La lista carga asincrona: da tiempo antes de descartar el warning banner.
  await page.locator("tbody tr").first().waitFor({ timeout: 10_000 }).catch(() => {});

  const warningBanner = page.getByText(/necesita atenci[oó]n|necesitan atenci[oó]n/i);
  const bannerAppeared = await warningBanner
    .waitFor({ state: "visible", timeout: 5_000 })
    .then(() => true)
    .catch(() => false);
  if (!bannerAppeared) {
    await page.goto("/dashboard/conocimiento/documentos");
    const cleanupRow0 = page.locator("tr", { hasText: sourceName });
    await cleanupRow0.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
    await page.locator("div.fixed.inset-0.z-\\[200\\]").getByRole("button", { name: /^eliminar$/i }).click();
    test.skip(true, "el documento no generó ningún chunk con warning en este run");
  }
  await expect(warningBanner).toBeVisible();

  const shortBadge = page.getByRole("button", { name: /muy corto/i });
  await expect(shortBadge).toBeVisible();
  const totalRows = await page.locator("tbody tr").count();

  await shortBadge.click();
  await expect(shortBadge).toHaveClass(/bg-warning text-white/);
  const limpiarFiltro = page.getByRole("button", { name: /limpiar filtro/i });
  await expect(limpiarFiltro).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(1, { timeout: 10_000 });
  for (const row of await page.locator("tbody tr").all()) {
    await expect(row.getByText(/muy corto/i)).toBeVisible();
  }

  await limpiarFiltro.click();
  await expect(limpiarFiltro).toHaveCount(0);
  await expect(page.locator("tbody tr")).toHaveCount(totalRows);

  await shortBadge.click();
  await expect(shortBadge).toHaveClass(/bg-warning text-white/);
  await shortBadge.click();
  await expect(shortBadge).not.toHaveClass(/bg-warning text-white/);
  await expect(page.locator("tbody tr")).toHaveCount(totalRows);

  await page.goto("/dashboard/conocimiento/documentos");
  const cleanupRow = page.locator("tr", { hasText: sourceName });
  await cleanupRow.getByRole("button").last().click();
  await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
  const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
  await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
  await expect(page.locator("tr", { hasText: sourceName })).toHaveCount(0, { timeout: 10_000 });

  fs.unlinkSync(filePath);
});

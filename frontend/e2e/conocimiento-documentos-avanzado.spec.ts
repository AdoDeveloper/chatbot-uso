import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

/**
 * Additional functional coverage for /dashboard/conocimiento/documentos not
 * already covered by conocimiento-documentos.spec.ts: the row-level "Vista
 * previa" modal (content + quality stats), the inline tag editor modal
 * launched from the row, and the full reject -> "Reemplazar archivo" ->
 * re-review lifecycle (previously out of scope because it required a
 * rejected source, which this test now creates disposably).
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "conocimiento-documentos-avanzado");
fs.mkdirSync(SHOT_DIR, { recursive: true });

async function uploadDisposableSource(page: import("@playwright/test").Page, name: string, content: string) {
  const filePath = path.join(os.tmpdir(), `e2e-adv-${Date.now()}.txt`);
  fs.writeFileSync(filePath, content);
  await page.goto("/dashboard/conocimiento/documentos");
  await expect(page.getByRole("tab", { name: /fuentes/i })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: /^agregar$/i }).click();
  const uploadDialog = page.getByRole("dialog");
  await uploadDialog.locator('input[type="file"]').setInputFiles(filePath);
  await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(name);
  await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
  // Bajo carga E2E concurrente (workers:2, pipeline de ingestión compartido) puede tardar mucho más que en solitario.
  await expect(uploadDialog).not.toBeVisible({ timeout: 120_000 });
  const row = page.locator("tr", { hasText: name });
  await expect(row.getByText("Listo", { exact: true })).toBeVisible({ timeout: 60_000 });
  fs.unlinkSync(filePath);
  return row;
}

test.describe("Conocimiento > Documentos > controles avanzados de fila", () => {
  test("vista previa: contenido extraido y estadisticas de calidad, cerrar y reabrir", async ({ page }) => {
    test.setTimeout(180_000);
    const name = `E2E Preview Source ${Date.now()}`;
    const row = await uploadDisposableSource(page, name, "Contenido de prueba E2E para el modal de vista previa. Segunda linea de contenido de ejemplo.");

    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /vista previa/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/contenido extraído/i)).toBeVisible({ timeout: 10_000 });
    await expect(dialog.getByText(/chunks/i).first()).toBeVisible();
    await expect(dialog.getByText(/hits 7d/i)).toBeVisible();
    await expect(dialog.getByText(/último uso/i)).toBeVisible();
    await page.screenshot({ path: path.join(SHOT_DIR, "01-vista-previa.png") });

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });

    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /vista previa/i }).click();
    const dialog2 = page.getByRole("dialog");
    await expect(dialog2.getByText(/contenido extraído/i)).toBeVisible({ timeout: 10_000 });
    await page.keyboard.press("Escape");
    await expect(dialog2).not.toBeVisible({ timeout: 5_000 });

    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.locator("tr", { hasText: name })).toHaveCount(0, { timeout: 10_000 });
  });

  test("editor de etiquetas inline: modal abrir, agregar/quitar, guardar, cancelar sin persistir", async ({ page }) => {
    test.setTimeout(180_000);
    const name = `E2E Tags Source ${Date.now()}`;
    const row = await uploadDisposableSource(page, name, "Contenido de prueba E2E para el editor de etiquetas inline.");

    await row.getByRole("button", { name: /agregar/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /etiquetas/i })).toBeVisible({ timeout: 5_000 });

    const tagInput = dialog.locator("input").first();
    await tagInput.fill("e2e-tag-cancelada");
    await tagInput.press("Enter");
    // Este tag NO debe persistir.
    await dialog.getByRole("button", { name: /cancelar/i }).click();
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
    await expect(row.getByText("e2e-tag-cancelada")).toHaveCount(0);

    await row.getByRole("button", { name: /agregar/i }).click();
    const dialog2 = page.getByRole("dialog");
    const tagInput2 = dialog2.locator("input").first();
    await tagInput2.fill("e2e-tag-guardada");
    await tagInput2.press("Enter");
    await dialog2.getByRole("button", { name: /^guardar$/i }).click();
    await expect(dialog2).not.toBeVisible({ timeout: 10_000 });
    await expect(row.getByText("e2e-tag-guardada")).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-etiqueta-guardada.png") });

    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.locator("tr", { hasText: name })).toHaveCount(0, { timeout: 10_000 });
  });

  test("ciclo completo: rechazar una fuente, luego reemplazar el archivo, vuelve a pendiente de revision", async ({ page }) => {
    test.setTimeout(240_000);
    const name = `E2E Replace Source ${Date.now()}`;
    const row = await uploadDisposableSource(page, name, "Contenido de prueba E2E para el flujo de rechazo y reemplazo de archivo.");

    await row.getByRole("button").last().click();
    const rejectItem = page.getByRole("menuitem", { name: /^rechazar$/i });
    await expect(rejectItem).toBeVisible({ timeout: 5_000 });
    await rejectItem.click();
    const rejectDialog = page.getByRole("dialog");
    await expect(rejectDialog).toBeVisible({ timeout: 5_000 });
    const reasonField = rejectDialog.locator("textarea, input").first();
    await reasonField.fill("Motivo de prueba E2E: contenido no relevante para el flujo de reemplazo.");
    await rejectDialog.getByRole("button", { name: /^rechazar$/i }).click();
    await expect(rejectDialog).not.toBeVisible({ timeout: 10_000 });
    await expect(row.getByText(/rechazada/i)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-fuente-rechazada.png") });

    await row.getByRole("button").last().click();
    const replaceItem = page.getByRole("menuitem", { name: /reemplazar archivo/i });
    await expect(replaceItem).toBeVisible({ timeout: 5_000 });
    await replaceItem.click();

    const replaceDialog = page.getByRole("dialog");
    await expect(replaceDialog.getByRole("heading", { name: /reemplazar archivo/i })).toBeVisible({ timeout: 5_000 });

    const submitBtn = replaceDialog.getByRole("button", { name: /^reemplazar$/i });
    await expect(submitBtn).toBeDisabled();

    const newFilePath = path.join(os.tmpdir(), `e2e-replace-${Date.now()}.txt`);
    fs.writeFileSync(newFilePath, "Contenido de reemplazo E2E, distinto al original.");
    await replaceDialog.locator('input[type="file"]').setInputFiles(newFilePath);
    await expect(submitBtn).toBeEnabled();
    await page.screenshot({ path: path.join(SHOT_DIR, "04-reemplazar-formulario.png") });

    await replaceDialog.getByRole("button", { name: /cancelar/i }).click();
    await expect(replaceDialog).not.toBeVisible({ timeout: 5_000 });
    await expect(row.getByText(/rechazada/i)).toBeVisible();

    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /reemplazar archivo/i }).click();
    const replaceDialog2 = page.getByRole("dialog");
    await replaceDialog2.locator('input[type="file"]').setInputFiles(newFilePath);
    await replaceDialog2.getByRole("button", { name: /^reemplazar$/i }).click();
    // Reemplazar dispara re-ingestión síncrona server-side antes de responder; bajo contención E2E puede tardar más que una subida normal.
    await expect(replaceDialog2).not.toBeVisible({ timeout: 40_000 });
    fs.unlinkSync(newFilePath);

    // Tras un reemplazo exitoso, tanto el badge de estado como el de revisión pueden leer "Pendiente" a la vez; match por cualquiera evita ambigüedad de strict-mode.
    await expect(row.getByText(/pendiente/i).first()).toBeVisible({ timeout: 20_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "05-fuente-reemplazada.png") });

    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.locator("tr", { hasText: name })).toHaveCount(0, { timeout: 10_000 });
  });
});

import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

/**
 * Functional coverage for /dashboard/conocimiento/documentos: both tabs.
 *
 * Fuentes: upload a small real .txt source, add a tag, reingest it, then
 * delete it (full lifecycle, real backend ingestion pipeline).
 *
 * FAQ: create/edit/delete an FAQ entry.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "conocimiento-documentos");
fs.mkdirSync(SHOT_DIR, { recursive: true });

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test.describe("Conocimiento > Documentos > Fuentes", () => {
  test("subir, etiquetar, reingestar y eliminar una fuente", async ({ page }) => {
    // Compite por el mismo pipeline de ingestión con conocimiento-chunks.spec.ts bajo workers:2; el timeout explícito debe superar el budget del .toPass() de abajo.
    test.setTimeout(300_000);
    const uniqueId = Date.now();
    const sourceName = `E2E Source ${uniqueId}`;
    const filePath = path.join(os.tmpdir(), `e2e-source-${uniqueId}.txt`);
    fs.writeFileSync(filePath, `Este es un documento de prueba E2E ${uniqueId} para el chatbot institucional. Contiene informacion de ejemplo sobre el proceso de inscripcion.`);

    await page.goto("/dashboard/conocimiento/documentos");
    await expect(page.getByRole("tab", { name: /fuentes/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /^agregar$/i }).click();
    const uploadDialog = page.getByRole("dialog");
    await expect(uploadDialog.getByRole("heading", { name: /nueva fuente de datos/i })).toBeVisible();

    const fileInput = uploadDialog.locator('input[type="file"]');
    await fileInput.setInputFiles(filePath);
    await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(sourceName);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-subir-formulario.png") });
    await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(uploadDialog).not.toBeVisible({ timeout: 15_000 });

    const row = page.locator("tr", { hasText: sourceName });
    await expect(row).toBeVisible({ timeout: 15_000 });

    // Solo espera el badge de estado "Listo", no el de revisión (ese queda "Pendiente" legítimamente hasta que un admin aprueba).
    await expect(row.getByText("Listo", { exact: true })).toBeVisible({ timeout: 60_000 });
    // El backend puede tardar unos segundos en liberar el lock de Redis tras marcar "Listo"; reingestar antes puede pegarle a "already_running" como no-op silencioso.
    await page.waitForTimeout(8_000);
    await page.screenshot({ path: path.join(SHOT_DIR, "02-fuente-procesada.png") });

    await row.getByRole("button", { name: /agregar/i }).click();
    const tagDialog = page.getByRole("dialog");
    await expect(tagDialog.getByRole("heading", { name: /etiquetas/i })).toBeVisible();
    await tagDialog.locator("input").first().fill("e2e-test");
    await tagDialog.locator("input").first().press("Enter");
    await tagDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(tagDialog).not.toBeVisible({ timeout: 10_000 });
    await expect(row.getByText("e2e-test")).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-etiquetada.png") });

    // Retries si el primer click coincide con el lock de ingestión aún liberándose (ver comentario arriba).
    await expect(async () => {
      await row.getByRole("button").last().click();
      await page.getByRole("menuitem", { name: /reingestar/i }).click();
      await expect(row.getByText("Listo", { exact: true })).toBeVisible({ timeout: 25_000 });
    }).toPass({ timeout: 260_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-reingestada.png") });

    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(confirmDialog.getByRole("heading")).toContainText(/eliminar/i);
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();

    await expect(page.locator("tr", { hasText: sourceName })).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "05-eliminada.png") });

    fs.unlinkSync(filePath);
  });
});

test.describe("Conocimiento > Documentos > FAQ", () => {
  test("crear, editar y eliminar una entrada FAQ", async ({ page }) => {
    const question = `E2E Pregunta ${Date.now()}`;
    const renamedQuestion = `${question} (editada)`;

    await page.goto("/dashboard/conocimiento/documentos?tab=faq");
    await expect(page.getByRole("tab", { name: /faq/i })).toBeVisible({ timeout: 10_000 });
    await page.getByRole("tab", { name: /^faq$/i }).click();

    await page.getByRole("button", { name: /nueva entrada/i }).click();
    const createDialog = page.getByRole("dialog");
    await expect(createDialog.getByRole("heading", { name: /nueva entrada faq/i })).toBeVisible();
    await createDialog.locator("#faq-question").fill(question);
    await createDialog.locator("#faq-answer").fill("Esta es una respuesta de prueba E2E.");
    await page.screenshot({ path: path.join(SHOT_DIR, "06-faq-crear.png") });
    await createDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(createDialog).not.toBeVisible({ timeout: 10_000 });

    await expect(page.getByText(question)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "07-faq-creada.png") });

    // Match la pregunta completa, no un prefijo: un leftover de una corrida anterior con el mismo prefijo colisionaría en el strict-mode match.
    await page.getByRole("button", { name: new RegExp(`editar.*${escapeRegExp(question)}`, "i") }).click();
    const editDialog = page.getByRole("dialog");
    await expect(editDialog.getByRole("heading", { name: /editar entrada/i })).toBeVisible();
    await editDialog.locator("#faq-question").fill(renamedQuestion);
    await editDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(editDialog).not.toBeVisible({ timeout: 10_000 });

    await expect(page.getByText(renamedQuestion)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "08-faq-editada.png") });

    // Usa el confirm() compartido de useToast(), no un Modal con role="dialog".
    await page.getByRole("button", { name: new RegExp(`eliminar.*${escapeRegExp(renamedQuestion)}`, "i") }).click();
    const deleteConfirm = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(deleteConfirm.getByRole("heading")).toContainText(/eliminar/i);
    await deleteConfirm.getByRole("button", { name: /^eliminar$/i }).click();

    await expect(page.getByText(renamedQuestion)).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "09-faq-eliminada.png") });
  });

  test("FAQ: buscar, filtrar por estado y por tag, switch de activo en el formulario", async ({ page }) => {
    const question = `E2E FAQ Filtros ${Date.now()}`;
    const uniqueTag = `e2e-tag-${Date.now()}`;

    await page.goto("/dashboard/conocimiento/documentos?tab=faq");
    await page.getByRole("tab", { name: /^faq$/i }).click();
    await expect(page.getByRole("button", { name: /nueva entrada/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /nueva entrada/i }).click();
    const createDialog = page.getByRole("dialog");
    await createDialog.locator("#faq-question").fill(question);
    await createDialog.locator("#faq-answer").fill("Respuesta de prueba E2E para filtros.");
    await createDialog.locator("#faq-tags").fill(uniqueTag);

    const activeSwitch = createDialog.locator("#faq-active");
    await expect(activeSwitch).toBeChecked();
    await activeSwitch.click();
    await expect(activeSwitch).not.toBeChecked();
    await createDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(createDialog).not.toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(question)).toBeVisible({ timeout: 10_000 });

    const searchInput = page.getByPlaceholder(/buscar por pregunta, respuesta o tag/i);
    await searchInput.fill(question);
    await expect(page.getByText(question)).toBeVisible({ timeout: 5_000 });
    await searchInput.fill("texto que no coincide con ninguna faq xyz123");
    await expect(page.getByText(/sin resultados/i)).toBeVisible({ timeout: 5_000 });
    await searchInput.fill("");

    await page.getByRole("button", { name: /^activas/i }).click();
    await expect(page.getByText(question)).toHaveCount(0, { timeout: 5_000 });
    await page.getByRole("button", { name: /^inactivas/i }).click();
    await expect(page.getByText(question)).toBeVisible({ timeout: 5_000 });
    await page.getByRole("button", { name: /^todas/i }).click();
    await expect(page.getByText(question)).toBeVisible({ timeout: 5_000 });

    const tagChip = page.getByRole("button", { name: new RegExp(`^${uniqueTag}$`) });
    if (await tagChip.isVisible().catch(() => false)) {
      await tagChip.click();
      await expect(page.getByText(question)).toBeVisible({ timeout: 5_000 });
      await page.getByRole("button", { name: /limpiar filtro de tag/i }).click();
    }
    await page.screenshot({ path: path.join(SHOT_DIR, "10-faq-filtros.png") });

    await page.getByRole("button", { name: new RegExp(`editar.*${escapeRegExp(question)}`, "i") }).click();
    const editDialog = page.getByRole("dialog");
    const editActiveSwitch = editDialog.locator("#faq-active");
    await expect(editActiveSwitch).not.toBeChecked();
    await editActiveSwitch.click();
    await expect(editActiveSwitch).toBeChecked();
    await editDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(editDialog).not.toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: new RegExp(`eliminar.*${escapeRegExp(question)}`, "i") }).click();
    const deleteConfirm = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(deleteConfirm.getByRole("heading")).toContainText(/eliminar/i);
    await deleteConfirm.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.getByText(question)).toHaveCount(0, { timeout: 10_000 });
  });
});

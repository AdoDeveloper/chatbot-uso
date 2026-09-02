import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Functional coverage for /dashboard/configuracion/escalamiento: create/
 * toggle/edit/delete an escalation rule against the real backend.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-escalamiento");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Escalamiento", () => {
  test("crear, activar/desactivar, editar y eliminar una regla", async ({ page }) => {
    const name = `E2E Rule ${Date.now()}`;
    const renamed = `${name} (editada)`;

    await page.goto("/dashboard/configuracion/escalamiento");
    await expect(page.getByText(/reglas de escalamiento/i)).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /agregar/i }).click();
    const createDialog = page.getByRole("dialog");
    await expect(createDialog.getByRole("heading", { name: /nueva regla/i })).toBeVisible();
    await createDialog.getByPlaceholder(/nombre de la regla/i).fill(name);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-crear-formulario.png") });
    await createDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(createDialog).not.toBeVisible({ timeout: 10_000 });

    const ruleItem = page.locator("li", { hasText: name });
    await expect(ruleItem).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-creada.png") });

    const toggle = ruleItem.locator("button[role='switch']");
    await toggle.click();
    await expect(ruleItem.getByText(/inactiva/i)).toBeVisible({ timeout: 10_000 });
    await toggle.click();
    await expect(ruleItem.getByText(/^activa$/i)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-toggle.png") });

    await ruleItem.locator("button").nth(1).click();
    const editDialog = page.getByRole("dialog");
    await expect(editDialog.getByRole("heading", { name: /editar regla/i })).toBeVisible();
    await editDialog.getByPlaceholder(/nombre de la regla/i).fill(renamed);
    await editDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(editDialog).not.toBeVisible({ timeout: 10_000 });

    const renamedItem = page.locator("li", { hasText: renamed });
    await expect(renamedItem).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-editada.png") });

    await renamedItem.locator("button").nth(2).click();
    const deleteDialog = page.getByRole("dialog");
    await expect(deleteDialog.getByRole("heading", { name: /eliminar regla/i })).toBeVisible();
    await deleteDialog.getByRole("button", { name: /^eliminar$/i }).click();

    await expect(page.locator("li", { hasText: renamed })).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "05-eliminada.png") });
  });

  test("probar SMTP", async ({ page }) => {
    await page.goto("/dashboard/configuracion/escalamiento");
    await expect(page.getByText("Destinatarios", { exact: true })).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: /^probar$/i }).click();
    await expect(page.getByRole("button", { name: /^probar$/i })).toBeEnabled({ timeout: 15_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "06-smtp-probado.png") });
  });

  test("enviar prueba de escalamiento (boton del header)", async ({ page }) => {
    await page.goto("/dashboard/configuracion/escalamiento");
    await expect(page.getByText(/reglas de escalamiento/i)).toBeVisible({ timeout: 10_000 });
    const consoleErrors: string[] = [];
    page.on("pageerror", (e) => consoleErrors.push(String(e)));

    const testBtn = page.getByRole("button", { name: /enviar prueba/i });
    await testBtn.click();
    await expect(testBtn).toBeEnabled({ timeout: 30_000 });
    expect(consoleErrors).toEqual([]);
  });

  test("select de tipo de activacion: las 6 opciones renderizan sus campos dinamicos sin excepcion", async ({ page }) => {
    await page.goto("/dashboard/configuracion/escalamiento");
    const consoleErrors: string[] = [];
    page.on("pageerror", (e) => consoleErrors.push(String(e)));

    await page.getByRole("button", { name: /agregar/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /nueva regla/i })).toBeVisible();

    const triggerSelect = dialog.locator("select");
    const values = ["no_answer", "user_request", "negative_feedback", "keyword_detected", "confidence_below", "loop_detected"];
    for (const value of values) {
      await triggerSelect.selectOption(value);
      await expect(triggerSelect).toHaveValue(value);
      await expect(dialog.locator("input, textarea").first()).toBeVisible();
    }
    expect(consoleErrors, `console errors while switching trigger types:\n${consoleErrors.join("\n")}`).toEqual([]);

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });

  test("modal 'Probar regla': ejecutar prueba con cada tipo de activacion y ver resultado", async ({ page }) => {
    await page.goto("/dashboard/configuracion/escalamiento");
    const consoleErrors: string[] = [];
    page.on("pageerror", (e) => consoleErrors.push(String(e)));

    await page.getByRole("button", { name: /agregar/i }).click();
    const ruleDialog = page.getByRole("dialog").nth(0);
    await expect(ruleDialog.getByRole("heading", { name: /nueva regla/i })).toBeVisible();
    await ruleDialog.getByPlaceholder(/nombre de la regla/i).fill(`E2E RuleTest ${Date.now()}`);

    const probarBtn = ruleDialog.getByRole("button", { name: /^probar$/i });
    await expect(probarBtn).toBeEnabled();
    await probarBtn.click();

    const testDialog = page.getByRole("dialog").nth(1);
    await expect(testDialog).toBeVisible({ timeout: 5_000 });
    await expect(testDialog.getByText(/probar regla/i)).toBeVisible();
    await expect(testDialog.getByText(/completa el contexto/i)).toBeVisible();

    await testDialog.getByPlaceholder("180").fill("200");
    await testDialog.getByRole("button", { name: /ejecutar prueba/i }).click();
    await expect(testDialog.getByText(/la regla (se activaría|no se activaría)/i)).toBeVisible({ timeout: 10_000 });
    await expect(testDialog.getByText(/payload que se enviaría/i)).toBeVisible();

    await testDialog.getByRole("button", { name: /^cerrar$/i }).click();
    await expect(testDialog).not.toBeVisible({ timeout: 5_000 });
    await expect(ruleDialog).toBeVisible();
    const triggerSelect = ruleDialog.locator("select");
    await triggerSelect.selectOption("keyword_detected");
    await ruleDialog.getByRole("button", { name: /^probar$/i }).click();
    const testDialog2 = page.getByRole("dialog").nth(1);
    await expect(testDialog2).toBeVisible({ timeout: 5_000 });
    await expect(testDialog2.getByText(/probar regla/i)).toBeVisible();
    await testDialog2.getByPlaceholder(/quiero hablar con un agente humano/i).fill("quiero hablar con un humano");
    await testDialog2.getByRole("button", { name: /ejecutar prueba/i }).click();
    await expect(testDialog2.getByText(/la regla (se activaría|no se activaría)/i)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "07-probar-regla-resultado.png") });

    await page.keyboard.press("Escape");
    await expect(testDialog2).not.toBeVisible({ timeout: 5_000 });

    await ruleDialog.getByRole("button", { name: /cancelar/i }).click();
    await expect(ruleDialog).not.toBeVisible({ timeout: 5_000 });

    expect(consoleErrors, `console errors during rule-test modal flow:\n${consoleErrors.join("\n")}`).toEqual([]);
  });

  test("modal crear regla: validacion de nombre vacio y cierre por Escape sin dejar residuo", async ({ page }) => {
    await page.goto("/dashboard/configuracion/escalamiento");
    await page.getByRole("button", { name: /agregar/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /nueva regla/i })).toBeVisible();

    await dialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(dialog.getByText(/nombre es obligatorio/i)).toBeVisible({ timeout: 5_000 });
    await expect(dialog).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });

    await page.getByRole("button", { name: /agregar/i }).click();
    const dialog2 = page.getByRole("dialog");
    await expect(dialog2.getByPlaceholder(/nombre de la regla/i)).toHaveValue("");
    await expect(dialog2.getByText(/nombre es obligatorio/i)).toHaveCount(0);
    await dialog2.getByRole("button", { name: /cancelar/i }).click();
    await expect(dialog2).not.toBeVisible({ timeout: 5_000 });
  });

  test("modal eliminar regla: cancelar preserva la regla", async ({ page }) => {
    const name = `E2E Rule Cancel Delete ${Date.now()}`;
    await page.goto("/dashboard/configuracion/escalamiento");
    await page.getByRole("button", { name: /agregar/i }).click();
    const createDialog = page.getByRole("dialog");
    await createDialog.getByPlaceholder(/nombre de la regla/i).fill(name);
    await createDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(createDialog).not.toBeVisible({ timeout: 10_000 });

    const ruleItem = page.locator("li", { hasText: name });
    await expect(ruleItem).toBeVisible({ timeout: 10_000 });

    await ruleItem.locator("button").nth(2).click();
    const deleteDialog = page.getByRole("dialog");
    await expect(deleteDialog.getByRole("heading", { name: /eliminar regla/i })).toBeVisible();
    await expect(deleteDialog.getByText(name)).toBeVisible();
    await deleteDialog.getByRole("button", { name: /cancelar/i }).click();
    await expect(deleteDialog).not.toBeVisible({ timeout: 5_000 });
    await expect(ruleItem).toBeVisible();

    await ruleItem.locator("button").nth(2).click();
    const deleteDialog2 = page.getByRole("dialog");
    await deleteDialog2.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.locator("li", { hasText: name })).toHaveCount(0, { timeout: 10_000 });
  });
});

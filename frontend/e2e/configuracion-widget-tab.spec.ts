import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Coverage for the Apariencia/Integración/Límites subtabs of /dashboard/configuracion/asistente (WidgetTab). Deliberately never clicks "Regenerar" on the widget API key - it would break every widget currently deployed with the old key.
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-widget-tab");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Asistente > Apariencia", () => {
  test("selector de posicion (4 esquinas), color, iconos y toggles avanzados, restaurado", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=apariencia");
    await expect(page.getByText(/posición en pantalla/i)).toBeVisible({ timeout: 10_000 });

    const positions = ["Superior izquierda", "Superior derecha", "Inferior izquierda", "Inferior derecha"];
    const originalPos = await page.locator('button[aria-pressed="true"]').getAttribute("aria-label");
    for (const label of positions) {
      const btn = page.getByRole("button", { name: label, exact: true });
      await btn.click();
      await expect(btn).toHaveAttribute("aria-pressed", "true");
    }
    if (originalPos) {
      await page.getByRole("button", { name: originalPos, exact: true }).click();
    }

    const colorText = page.locator('input.font-mono').first();
    const originalColor = await colorText.inputValue();
    await colorText.fill("#123456");
    await expect(colorText).toHaveValue("#123456");
    await colorText.fill(originalColor);

    const iconToggle = page.getByText(/mostrar icono del bot/i).locator("../..").locator('[role="switch"]');
    const originalIcon = (await iconToggle.getAttribute("aria-checked")) === "true";
    await iconToggle.click();
    await expect(iconToggle).toHaveAttribute("aria-checked", String(!originalIcon));
    await iconToggle.click();
    await expect(iconToggle).toHaveAttribute("aria-checked", String(originalIcon));

    await page.getByText(/más opciones de visualización/i).click();
    const nestedLabels = [
      /mostrar fuentes/i, /botón de copiar/i, /iconos de valoración/i,
      /menú de accesibilidad/i, /leer respuestas en voz alta/i,
    ];
    for (const label of nestedLabels) {
      const sw = page.getByText(label).locator("../..").locator('[role="switch"]');
      await expect(sw).toBeVisible({ timeout: 5_000 });
      const was = (await sw.getAttribute("aria-checked")) === "true";
      await sw.click();
      await expect(sw).toHaveAttribute("aria-checked", String(!was));
      await sw.click();
      await expect(sw).toHaveAttribute("aria-checked", String(was));
    }
    await page.screenshot({ path: path.join(SHOT_DIR, "01-apariencia.png") });

    const discardBtn = page.getByRole("button", { name: /descartar/i });
    if (await discardBtn.isVisible().catch(() => false)) {
      await discardBtn.click();
    }
  });

  test("controles de conversacion: toggles y encuesta CSAT con pregunta personalizada, restaurado", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=apariencia");
    await expect(page.getByText(/controles de conversación/i)).toBeVisible({ timeout: 10_000 });

    for (const label of [/escalamiento a un humano/i, /botón «finalizar chat»/i, /botón «nueva conversación»/i]) {
      const sw = page.getByText(label).locator("../..").locator('[role="switch"]');
      const was = (await sw.getAttribute("aria-checked")) === "true";
      await sw.click();
      await expect(sw).toHaveAttribute("aria-checked", String(!was));
      await sw.click();
      await expect(sw).toHaveAttribute("aria-checked", String(was));
    }

    const csatSwitch = page.getByText(/encuesta de satisfacción \(csat\)/i).locator("../..").locator('[role="switch"]');
    const csatWasOn = (await csatSwitch.getAttribute("aria-checked")) === "true";
    if (!csatWasOn) await csatSwitch.click();
    await expect(page.getByPlaceholder(/cómo calificarías esta conversación/i)).toBeVisible({ timeout: 5_000 });

    const questionInput = page.getByPlaceholder(/cómo calificarías esta conversación/i);
    const originalQuestion = await questionInput.inputValue();
    await questionInput.fill("Pregunta de prueba E2E para CSAT");
    await expect(page.getByText(/32\/200 caracteres/)).toBeVisible();
    await questionInput.fill(originalQuestion);

    if (!csatWasOn) await csatSwitch.click();

    const discardBtn = page.getByRole("button", { name: /descartar/i });
    if (await discardBtn.isVisible().catch(() => false)) {
      await discardBtn.click();
    }
  });

  test("motivos CSAT: crear, editar, activar/desactivar, reordenar y eliminar, restaurado", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=apariencia");
    await expect(page.getByText(/controles de conversación/i)).toBeVisible({ timeout: 10_000 });

    const csatSwitch = page.getByText(/encuesta de satisfacción \(csat\)/i).locator("../..").locator('[role="switch"]');
    const csatWasOn = (await csatSwitch.getAttribute("aria-checked")) === "true";
    if (!csatWasOn) await csatSwitch.click();
    await expect(page.getByText(/motivos seleccionables/i)).toBeVisible({ timeout: 5_000 });

    const uniqueLabel = `E2E motivo ${Date.now()}`;
    const newReasonInput = page.getByPlaceholder(/nuevo motivo/i);
    await newReasonInput.fill(uniqueLabel);
    await newReasonInput.press("Enter");
    await expect(page.getByText(uniqueLabel)).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: uniqueLabel }).click();
    const editedLabel = `${uniqueLabel} editado`;
    const editInput = page.locator("input.h-7.text-xs.flex-1:not([placeholder])");
    await expect(editInput).toBeVisible({ timeout: 5_000 });
    await editInput.fill(editedLabel);
    await editInput.blur();
    await expect(page.getByText(editedLabel)).toBeVisible({ timeout: 10_000 });

    const reasonSwitch = page.locator("div", { hasText: editedLabel }).locator('[role="switch"]').last();
    await expect(reasonSwitch).toHaveAttribute("aria-checked", "true", { timeout: 5_000 });
    await reasonSwitch.click();
    await expect(reasonSwitch).toHaveAttribute("aria-checked", "false", { timeout: 5_000 });
    await reasonSwitch.click();
    await expect(reasonSwitch).toHaveAttribute("aria-checked", "true", { timeout: 5_000 });

    await page.getByTitle("Eliminar motivo").last().click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(confirmDialog.getByRole("heading")).toContainText(/eliminar/i);
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.getByText(editedLabel)).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "01b-csat-motivos.png") });

    if (!csatWasOn) await csatSwitch.click();
    const discardBtn = page.getByRole("button", { name: /descartar/i });
    if (await discardBtn.isVisible().catch(() => false)) {
      await discardBtn.click();
    }
  });

  test("captacion: toggle, etiqueta del boton, mensaje proactivo con contador y preview, sugerencias rapidas, restaurado", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=apariencia");
    await expect(page.getByText(/^captación$/i)).toBeVisible({ timeout: 10_000 });

    const captacionSwitch = page.getByText(/^captación$/i).locator("../..").locator('[role="switch"]');
    const wasOpen = (await captacionSwitch.getAttribute("aria-checked")) === "true";
    if (!wasOpen) await captacionSwitch.click();
    await expect(page.getByPlaceholder(/necesitas ayuda/i)).toBeVisible({ timeout: 5_000 });

    const labelInput = page.getByPlaceholder(/necesitas ayuda/i);
    const originalLabel = await labelInput.inputValue();
    await labelInput.fill("Hola E2E");
    await expect(page.getByText(/8\/80 caracteres/)).toBeVisible();

    const proactiveInput = page.getByPlaceholder(/tienes dudas sobre la universidad/i);
    const originalProactive = await proactiveInput.inputValue();
    await proactiveInput.fill("Mensaje proactivo E2E de prueba");
    await expect(page.getByText(/vista previa:/i)).toBeVisible();
    await expect(page.getByText("Mensaje proactivo E2E de prueba")).toBeVisible();

    const addBtn = page.getByRole("button", { name: /^agregar$/i }).last();
    await addBtn.click();
    const suggestionInput = page.getByPlaceholder(/^sugerencia 1$/i);
    await expect(suggestionInput).toBeVisible({ timeout: 5_000 });
    await suggestionInput.fill("Sugerencia E2E");
    await page.getByRole("button", { name: /quitar sugerencia 1/i }).click();
    await expect(suggestionInput).toHaveCount(0);
    await page.screenshot({ path: path.join(SHOT_DIR, "02-captacion.png") });

    await labelInput.fill(originalLabel);
    await proactiveInput.fill(originalProactive);
    if (!wasOpen) await captacionSwitch.click();

    const discardBtn = page.getByRole("button", { name: /descartar/i });
    if (await discardBtn.isVisible().catch(() => false)) {
      await discardBtn.click();
    }
  });
});

test.describe("Configuracion > Asistente > Integración", () => {
  test("snippet script/iframe, copiar codigo, agregar y quitar un dominio permitido, restaurado", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=integracion");
    await expect(page.getByRole("heading", { name: /código de integración/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: "iframe", exact: true }).click();
    await expect(page.locator("pre")).toContainText("iframe", { timeout: 5_000 });
    await page.getByRole("button", { name: "Script tag", exact: true }).click();
    await expect(page.locator("pre")).toContainText("script", { timeout: 5_000 });

    await page.context().grantPermissions(["clipboard-write", "clipboard-read"]);
    await page.getByRole("button", { name: /^copiar$/i }).click();
    await expect(page.getByText(/^copiado$/i)).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-integracion-snippet.png") });

    const apiKeyCopyBtn = page.locator("input.font-mono.select-all").locator("..").getByRole("button").first();
    if (await apiKeyCopyBtn.isVisible().catch(() => false)) {
      await apiKeyCopyBtn.click();
    }

    const domainInput = page.getByPlaceholder(/ejemplo\.com o \*\.ejemplo\.com/i);
    await expect(domainInput).toBeVisible({ timeout: 10_000 });
    const testDomain = `e2e-test-${Date.now()}.invalid`;
    await domainInput.fill(testDomain);
    await domainInput.press("Enter");
    await expect(page.getByText(testDomain)).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-dominio-agregado.png") });

    const saveBtn = page.getByRole("button", { name: /^guardar$/i });
    await expect(saveBtn).toBeVisible({ timeout: 5_000 });
    await saveBtn.click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    await expect(page.getByText(testDomain)).toBeVisible();

    await page.getByRole("button", { name: `Quitar dominio ${testDomain}` }).click();
    await expect(page.getByText(testDomain)).toHaveCount(0);
    const saveBtn2 = page.getByRole("button", { name: /^guardar$/i });
    if (await saveBtn2.isVisible().catch(() => false)) {
      await saveBtn2.click();
      await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    }
  });
});

test.describe("Configuracion > Asistente > Límites", () => {
  test("caps anti-abuso: mensajes por sesion y por dia, editar y restaurar", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=limites");
    await expect(page.getByText(/caps anti-abuso/i)).toBeVisible({ timeout: 10_000 });

    const perSessionInput = page.locator('input[type="number"]').first();
    const perDayInput = page.locator('input[type="number"]').nth(1);
    const originalSession = await perSessionInput.inputValue();
    const originalDay = await perDayInput.inputValue();
    const newSession = String((Number(originalSession) || 10) + 7);
    const newDay = String((Number(originalDay) || 100) + 111);

    await perSessionInput.fill(newSession);
    await perDayInput.fill(newDay);
    const saveBtn = page.getByRole("button", { name: /^guardar$/i });
    await expect(saveBtn).toBeVisible({ timeout: 5_000 });
    await saveBtn.click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    await expect(perSessionInput).toHaveValue(newSession);
    await page.screenshot({ path: path.join(SHOT_DIR, "05-limites-guardados.png") });

    await perSessionInput.fill(originalSession);
    await perDayInput.fill(originalDay);
    const saveBtn2 = page.getByRole("button", { name: /^guardar$/i });
    if (await saveBtn2.isVisible().catch(() => false)) {
      await saveBtn2.click();
      await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    }
  });
});

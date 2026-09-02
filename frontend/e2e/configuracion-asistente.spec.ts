import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Coverage for /dashboard/configuracion/asistente: settings export, the Prompt tab save flow, a widget appearance toggle, and CSAT reason CRUD. Never touches "Regenerar clave del widget" - it would break every widget embed currently deployed with the old key.
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-asistente");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Asistente", () => {
  test("exportar la configuracion", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente");
    await expect(page.getByRole("button", { name: /exportar/i })).toBeVisible({ timeout: 10_000 });

    const downloadPromise = page.waitForEvent("download", { timeout: 15_000 });
    await page.getByRole("button", { name: /exportar/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBeTruthy();
    await page.screenshot({ path: path.join(SHOT_DIR, "01-configuracion.png") });
  });

  test("editar y guardar el nombre del asistente (tab Prompt)", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=prompt");
    await expect(page.getByText(/^nombre$/i).first()).toBeVisible({ timeout: 10_000 });

    const nameInput = page.locator("input[maxlength='80']");
    const original = await nameInput.inputValue();
    await nameInput.fill(`${original} `);
    await page.screenshot({ path: path.join(SHOT_DIR, "02-prompt-editado.png") });

    await page.getByRole("button", { name: /^guardar$/i }).click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-prompt-guardado.png") });

    await nameInput.fill(original);
    const saveBtn = page.getByRole("button", { name: /^guardar$/i });
    if (await saveBtn.isVisible().catch(() => false)) {
      await saveBtn.click();
    }
  });

  test("gestionar motivos CSAT (crear, editar, activar/desactivar, eliminar)", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=apariencia");
    await expect(page.getByText(/encuesta de satisfacción/i)).toBeVisible({ timeout: 10_000 });

    const csatToggle = page.getByText(/encuesta de satisfacción/i).locator("../..").locator("button[role='switch']");
    await expect(csatToggle).toBeVisible({ timeout: 10_000 });
    const csatWasOn = await csatToggle.isChecked().catch(() => false);
    if (!csatWasOn) {
      await csatToggle.click();
    }
    await expect(page.getByText(/motivos seleccionables/i)).toBeVisible({ timeout: 10_000 });

    const label = `E2E Motivo ${Date.now()}`;
    const renamedLabel = `${label} (editado)`;

    await page.getByPlaceholder(/nuevo motivo/i).fill(label);
    await page.getByPlaceholder(/nuevo motivo/i).press("Enter");
    const reasonRow = page.locator("div", { hasText: label }).last();
    await expect(reasonRow).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-csat-motivo-creado.png") });

    await page.getByText(label, { exact: false }).last().click();
    const editInput = page.locator("input[maxlength='120']").first();
    await editInput.fill(renamedLabel);
    await editInput.press("Enter");
    await expect(page.getByText(renamedLabel)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "05-csat-motivo-editado.png") });

    const renamedRow = page.locator("div", { hasText: renamedLabel }).last();
    await renamedRow.locator("button[role='switch']").click();
    await page.screenshot({ path: path.join(SHOT_DIR, "06-csat-motivo-toggle.png") });

    await renamedRow.locator('button[title="Eliminar motivo"]').click();
    const deleteConfirm = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(deleteConfirm.getByRole("heading")).toContainText(/eliminar/i);
    await deleteConfirm.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.getByText(renamedLabel)).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "07-csat-motivo-eliminado.png") });

    if (!csatWasOn) {
      await csatToggle.click();
      const saveBtn = page.getByRole("button", { name: /^guardar$/i });
      if (await saveBtn.isVisible().catch(() => false)) {
        await saveBtn.click();
      }
    }
  });

  test("tab Prompt: mensajes automaticos (bienvenida, saludo, bloqueo, sin-servicio) editables y restaurados", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=prompt");
    await expect(page.getByText(/^nombre$/i).first()).toBeVisible({ timeout: 10_000 });

    const welcomeInput = page.locator("input[maxlength='500']");
    const originalWelcome = await welcomeInput.inputValue();
    await welcomeInput.fill(`${originalWelcome} `);
    await expect(page.getByRole("button", { name: /^guardar$/i })).toBeVisible({ timeout: 5_000 });

    const systemPromptCard = page.getByText(/prompt del sistema/i);
    await systemPromptCard.click();
    const systemTextarea = page.locator("textarea.font-mono");
    await expect(systemTextarea).toBeVisible({ timeout: 5_000 });
    const originalPrompt = await systemTextarea.inputValue();
    await expect(page.getByText(new RegExp(`${originalPrompt.length}/4000`))).toBeVisible();

    await page.getByText(/mensajes automáticos/i).click();
    const greetingTextarea = page.locator("textarea").nth(1);
    const blockedTextarea = page.locator("textarea").nth(2);
    const noProvidersTextarea = page.locator("textarea").nth(3);
    await expect(greetingTextarea).toBeVisible({ timeout: 5_000 });

    const originalGreeting = await greetingTextarea.inputValue();
    const originalBlocked = await blockedTextarea.inputValue();
    const originalNoProviders = await noProvidersTextarea.inputValue();

    await greetingTextarea.fill(`${originalGreeting} `);
    await blockedTextarea.fill(`${originalBlocked} `);
    await noProvidersTextarea.fill(`${originalNoProviders} `);

    const saveBtn = page.getByRole("button", { name: /^guardar$/i });
    await expect(saveBtn).toBeVisible({ timeout: 5_000 });
    await saveBtn.click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });

    await welcomeInput.fill(originalWelcome);
    await greetingTextarea.fill(originalGreeting);
    await blockedTextarea.fill(originalBlocked);
    await noProvidersTextarea.fill(originalNoProviders);
    const saveBtn2 = page.getByRole("button", { name: /^guardar$/i });
    if (await saveBtn2.isVisible().catch(() => false)) {
      await saveBtn2.click();
      await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    }
    await expect(welcomeInput).toHaveValue(originalWelcome);
  });

  test("tab Prompt: presets rapidos de parametros RAG, sliders y switch de revision de relevancia, restaurado", async ({ page }) => {

    await page.goto("/dashboard/configuracion/asistente?tab=prompt");
    await expect(page.getByText(/perfil del asistente/i)).toBeVisible({ timeout: 10_000 });

    const tempSlider = page.locator('input[type="range"]').nth(2); // top_k, score_threshold, then temperature
    const maxTokensInput = page.locator('input[type="number"]').last();
    const originalTemp = await tempSlider.inputValue();
    const originalMaxTokens = await maxTokensInput.inputValue();
    const correctiveSwitch = page.getByText(/revisión de relevancia/i).locator("../../..").locator('[role="switch"]');
    const originalCorrective = (await correctiveSwitch.getAttribute("aria-checked")) === "true";

    for (const label of ["Preciso", "Equilibrado", "Exploratorio"]) {
      await page.getByRole("button", { name: new RegExp(`^${label}`, "i") }).click();
      await expect(page.getByText("● Activo")).toBeVisible({ timeout: 5_000 });
    }

    // Manual slider adjustment breaks preset detection - no preset stays marked active.
    await tempSlider.fill("1.5");
    await expect(page.getByText("● Activo")).toHaveCount(0);

    await correctiveSwitch.click();
    await expect(correctiveSwitch).toHaveAttribute("aria-checked", String(!originalCorrective));

    const saveBtn = page.getByRole("button", { name: /^guardar$/i });
    await expect(saveBtn).toBeVisible({ timeout: 5_000 });
    await saveBtn.click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });

    await tempSlider.fill(originalTemp);
    await maxTokensInput.fill(originalMaxTokens);
    const correctiveNow = (await correctiveSwitch.getAttribute("aria-checked")) === "true";
    if (correctiveNow !== originalCorrective) await correctiveSwitch.click();

    const saveBtn2 = page.getByRole("button", { name: /^guardar$/i });
    if (await saveBtn2.isVisible().catch(() => false)) {
      await saveBtn2.click();
      await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    }
  });
});

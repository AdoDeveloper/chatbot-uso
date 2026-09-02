import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Functional coverage for /dashboard/configuracion/notificaciones: the
 * report schedule save flow (Programación tab) and the global email toggle
 * (Eventos tab), against the real backend. The email toggle test restores
 * its original state at the end so it doesn't permanently change delivery
 * behavior for the environment.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-notificaciones");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Notificaciones", () => {
  test("ver historial de notificaciones agrupado por disparo, con canales", async ({ page }) => {
    await page.goto("/dashboard/configuracion/notificaciones");
    await expect(page.getByRole("tab", { name: /historial/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("columnheader", { name: /evento/i })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("columnheader", { name: /canales/i })).toBeVisible();

    // Each row groups one trigger (not one raw NotificationLog row), so "Canales" shows badges like "Correo"/"En la app" instead of a single target.
    const firstRow = page.locator("tbody tr").first();
    if (await firstRow.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await expect(firstRow.getByText(/correo|en la app/i).first()).toBeVisible();
    }
    await page.screenshot({ path: path.join(SHOT_DIR, "01-historial.png") });
  });

  test("cambiar y guardar la programacion del reporte", async ({ page }) => {
    await page.goto("/dashboard/configuracion/notificaciones");
    await page.getByRole("tab", { name: /programación/i }).click();
    await expect(page.getByText(/programación del reporte/i).first()).toBeVisible({ timeout: 10_000 });

    const minuteSelect = page.locator("select").last();
    const original = await minuteSelect.inputValue();
    const options = await minuteSelect.locator("option").allInnerTexts();
    const newValue = original === "0" ? "15" : "0";
    void options;
    await minuteSelect.selectOption(newValue);

    await page.screenshot({ path: path.join(SHOT_DIR, "02-programacion-editada.png") });
    await page.getByRole("button", { name: /^guardar$/i }).click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-programacion-guardada.png") });

    await minuteSelect.selectOption(original);
    const saveBtn = page.getByRole("button", { name: /^guardar$/i });
    if (await saveBtn.isVisible().catch(() => false)) {
      await saveBtn.click();
    }
  });

  test("frecuencia de la programacion: cada opcion revela sus controles condicionales, sin excepcion", async ({ page }) => {
    const consoleErrors: string[] = [];
    await page.goto("/dashboard/configuracion/notificaciones");
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
    await page.getByRole("tab", { name: /programación/i }).click();
    await expect(page.getByText(/programación del reporte/i).first()).toBeVisible({ timeout: 10_000 });

    const freqSelect = page.locator("select").first();
    const originalFreq = await freqSelect.inputValue();

    // Weekly reveals day-of-week toggles; toggled on and back off in place, independent of whichever frequency is actually saved at the end of the test.
    await freqSelect.selectOption("weekly");
    await expect(page.getByText(/días de la semana/i)).toBeVisible({ timeout: 5_000 });
    const dayButtons = page.locator("button.h-8.w-8");
    const dayCount = await dayButtons.count();
    expect(dayCount).toBeGreaterThan(0);
    const firstDay = dayButtons.first();
    const wasActive = (await firstDay.getAttribute("class"))?.includes("bg-primary");
    await firstDay.click();
    await firstDay.click();
    const nowActive = (await firstDay.getAttribute("class"))?.includes("bg-primary");
    expect(!!nowActive).toBe(!!wasActive);

    await freqSelect.selectOption("monthly");
    await expect(page.getByText(/^día del mes$/i)).toBeVisible({ timeout: 5_000 });

    await freqSelect.selectOption("yearly");
    await expect(page.getByText(/^mes$/i)).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText(/^día$/i)).toBeVisible();

    expect(consoleErrors, `console errors while switching frequency:\n${consoleErrors.join("\n")}`).toEqual([]);
    await page.screenshot({ path: path.join(SHOT_DIR, "06-frecuencia-anual.png") });

    // This page's FloatingSaveBar has no onDiscard (no "Descartar" button), so restoring means explicitly saving the original value.
    await freqSelect.selectOption(originalFreq);
    const saveBtn = page.getByRole("button", { name: /^guardar$/i });
    if (await saveBtn.isVisible().catch(() => false)) {
      await saveBtn.click();
      await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    }
  });

  test("activar y desactivar el canal de correo", async ({ page }) => {
    await page.goto("/dashboard/configuracion/notificaciones");
    await page.getByRole("tab", { name: /eventos/i }).click();
    await expect(page.getByText(/^correos$/i)).toBeVisible({ timeout: 10_000 });

    const toggle = page.getByLabel(/activar correos/i);
    const wasChecked = await toggle.isChecked();

    await toggle.click();
    await expect(async () => {
      expect(await toggle.isChecked()).toBe(!wasChecked);
    }).toPass({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-toggle-correos.png") });

    const nowChecked = await toggle.isChecked();
    if (nowChecked !== wasChecked) {
      await toggle.click();
    }
  });

  test("tabla de eventos: activar/desactivar dos filas distintas por email, restauradas", async ({ page }) => {
    await page.goto("/dashboard/configuracion/notificaciones");
    await page.getByRole("tab", { name: /eventos/i }).click();
    await expect(page.getByRole("columnheader", { name: /evento/i })).toBeVisible({ timeout: 10_000 });

    for (const eventLabel of ["Documento procesado", "Escalamiento activado"]) {
      const row = page.locator("tr", { hasText: eventLabel });
      await expect(row).toBeVisible({ timeout: 10_000 });
      const rowSwitch = row.locator('[role="switch"]');
      await expect(rowSwitch).toBeVisible();
      const wasChecked = await rowSwitch.isChecked();

      await rowSwitch.click();
      await expect(async () => {
        expect(await rowSwitch.isChecked()).toBe(!wasChecked);
      }).toPass({ timeout: 10_000 });

      await rowSwitch.click();
      await expect(async () => {
        expect(await rowSwitch.isChecked()).toBe(wasChecked);
      }).toPass({ timeout: 10_000 });
    }
    await page.screenshot({ path: path.join(SHOT_DIR, "05-tabla-eventos.png") });
  });
});

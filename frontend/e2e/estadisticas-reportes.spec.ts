import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Functional coverage for /dashboard/estadisticas (export dropdown) and
 * /dashboard/reportes (PDF generation), against the real backend export
 * endpoints. Both trigger a real blob download.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "estadisticas-reportes");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Estadisticas", () => {
  test("exportar estadisticas a Excel", async ({ page }) => {
    await page.goto("/dashboard/estadisticas");
    await expect(page.getByRole("button", { name: /exportar/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /exportar/i }).click();
    const downloadPromise = page.waitForEvent("download", { timeout: 15_000 });
    await page.getByRole("menuitem", { name: /excel/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBeTruthy();
    await page.screenshot({ path: path.join(SHOT_DIR, "01-estadisticas-exportadas.png") });
  });

  test("exportar estadisticas a PDF", async ({ page }) => {
    await page.goto("/dashboard/estadisticas");
    const exportBtn = page.getByRole("button", { name: /exportar/i });
    await expect(exportBtn).toBeVisible({ timeout: 10_000 });
    await exportBtn.click();
    const downloadPromise = page.waitForEvent("download", { timeout: 15_000 });
    await page.getByRole("menuitem", { name: /^pdf$/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBeTruthy();
  });

  test("fuente Produccion/Previsualizar, filtro de periodo y ventana de actividad no lanzan excepcion", async ({ page }) => {
    const consoleErrors: string[] = [];
    await page.goto("/dashboard/estadisticas");
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
    await expect(page.getByText(/^producción$/i)).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /previsualizar/i }).click();
    await expect(page.getByText(/mostrando métricas de/i)).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: /cambiar a producción/i }).click();
    await expect(page.getByText(/mostrando métricas de/i)).toHaveCount(0, { timeout: 5_000 });

    const dateInputs = page.locator('input[type="date"]');
    if (await dateInputs.count() >= 1) {
      await dateInputs.first().fill("2026-01-01");
      await page.waitForTimeout(800);
    }

    for (const label of ["Día", "Semana", "Mes", "Año"]) {
      await page.getByRole("button", { name: label, exact: true }).click();
      await page.waitForTimeout(300);
    }

    expect(consoleErrors, `console errors:\n${consoleErrors.join("\n")}`).toEqual([]);
    await page.screenshot({ path: path.join(SHOT_DIR, "04-estadisticas-controles.png") });
  });
});

test.describe("Reportes", () => {
  test("descargar el reporte ejecutivo en PDF", async ({ page }) => {
    await page.goto("/dashboard/reportes");
    const execTitle = page.getByText("Reporte Ejecutivo", { exact: true });
    await expect(execTitle).toBeVisible({ timeout: 10_000 });
    // Each report is its own <Card> with one "Descargar PDF" button - find the smallest ancestor containing both the title and that button to scope the click.
    const execCard = execTitle.locator("xpath=(ancestor::*[.//button[contains(., 'Descargar PDF')]])[last()]");
    await expect(execCard.getByRole("button", { name: /descargar pdf/i })).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-reportes.png") });

    const downloadPromise = page.waitForEvent("download", { timeout: 30_000 });
    await execCard.getByRole("button", { name: /descargar pdf/i }).first().click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBeTruthy();
    await page.screenshot({ path: path.join(SHOT_DIR, "03-reporte-descargado.png") });
  });

  test("descargar los otros 3 reportes: Uso y Temas, Escalamientos, Base de Conocimiento", async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto("/dashboard/reportes");
    await expect(page.getByText("Reporte Ejecutivo", { exact: true })).toBeVisible({ timeout: 10_000 });

    for (const title of ["Uso y Temas", "Escalamientos", "Base de Conocimiento"]) {
      const cardTitle = page.getByText(title, { exact: true });
      const card = cardTitle.locator("xpath=(ancestor::*[.//button[contains(., 'Descargar PDF')]])[last()]");
      const downloadBtn = card.getByRole("button", { name: /descargar pdf/i });
      await expect(downloadBtn).toBeVisible({ timeout: 5_000 });
      const downloadPromise = page.waitForEvent("download", { timeout: 30_000 });
      await downloadBtn.click();
      const download = await downloadPromise;
      expect(download.suggestedFilename(), `${title} download`).toBeTruthy();
      await expect(card.getByText(/descargado a las/i)).toBeVisible({ timeout: 10_000 });
    }
  });

  test("rango de fechas invalido deshabilita la descarga y muestra el mensaje de validacion", async ({ page }) => {
    await page.goto("/dashboard/reportes");
    await expect(page.getByText("Reporte Ejecutivo", { exact: true })).toBeVisible({ timeout: 10_000 });

    const dateInputs = page.locator('input[type="date"]');
    await expect(dateInputs.first()).toBeVisible({ timeout: 5_000 });
    const toValue = await dateInputs.nth(1).inputValue();
    const invalidFrom = new Date(new Date(toValue).getTime() + 5 * 86400000).toISOString().slice(0, 10);
    await dateInputs.first().fill(invalidFrom);

    await expect(page.getByText(/la fecha inicial debe ser anterior o igual a la final/i)).toBeVisible({ timeout: 5_000 });
    const execTitle = page.getByText("Reporte Ejecutivo", { exact: true });
    const execCard = execTitle.locator("xpath=(ancestor::*[.//button[contains(., 'Descargar PDF')]])[last()]");
    await expect(execCard.getByRole("button", { name: /descargar pdf/i })).toBeDisabled();

    await dateInputs.first().fill(toValue);
    await expect(page.getByText(/la fecha inicial debe ser anterior o igual a la final/i)).toHaveCount(0, { timeout: 5_000 });
  });
});

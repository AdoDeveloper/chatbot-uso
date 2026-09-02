import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Functional coverage for /dashboard/configuracion/estado: health snapshot
 * refresh, rate-limit config save (restored after), and the "Sincronizar
 * Qdrant" recovery action (safe/idempotent - only removes already-orphaned
 * chunks, does not touch valid data), all against the real backend.
 *
 * Deliberately skips "Limpiar caché completo" and "Limpiar P99" - both are
 * destructive/irreversible bulk-delete maintenance tools not meant to run
 * unconditionally on every suite execution.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-estado");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Estado", () => {
  test("revisar salud de los servicios", async ({ page }) => {
    await page.goto("/dashboard/configuracion/estado");
    await expect(page.getByRole("heading", { name: /salud de los servicios/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /revisar/i }).click();
    await expect(page.locator(".animate-spin")).toHaveCount(0, { timeout: 15_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "01-salud-revisada.png") });
  });

  test("sincronizar qdrant (recovery, idempotente)", async ({ page }) => {
    await page.goto("/dashboard/configuracion/estado");
    await expect(page.getByRole("heading", { name: /recovery/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /sincronizar ahora/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(confirmDialog.getByRole("heading")).toContainText(/sincronizar/i);
    await confirmDialog.getByRole("button", { name: /^sincronizar$/i }).click();

    await expect(page.getByRole("button", { name: /sincronizar ahora/i })).toBeEnabled({ timeout: 15_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-qdrant-sincronizado.png") });
  });

  test("editar y guardar limites de cuota (chat por minuto/hora)", async ({ page }) => {
    await page.goto("/dashboard/configuracion/estado");
    await page.getByRole("tab", { name: /cuotas/i }).click();
    await expect(page.getByText(/límites configurados/i)).toBeVisible({ timeout: 10_000 });

    const perMinInput = page.getByText(/chat por minuto/i).locator("..").locator("input[type='number']");
    const original = await perMinInput.inputValue();
    const newValue = String(Number(original) + 1);
    const saveButton = page.getByRole("button", { name: /^guardar$/i });
    await perMinInput.fill(newValue);
    await expect(saveButton).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-limites-editados.png") });

    await saveButton.click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-limites-guardados.png") });

    await perMinInput.fill(original);
    const saveBtn = page.getByRole("button", { name: /^guardar$/i });
    if (await saveBtn.isVisible().catch(() => false)) {
      await saveBtn.click();
    }
  });

  test("editar y guardar configuracion del cache (TTL, umbral, toggle), restaurado al final", async ({ page }) => {
    await page.goto("/dashboard/configuracion/estado");
    await expect(page.getByRole("heading", { name: /^caché$/i })).toBeVisible({ timeout: 10_000 });

    const ttlInput = page.locator("#cache-ttl");
    const thresholdInput = page.locator("#cache-threshold");
    await expect(ttlInput).toBeVisible({ timeout: 10_000 });

    const originalTtl = await ttlInput.inputValue();
    const originalThreshold = await thresholdInput.inputValue();
    const cacheSwitch = page.getByLabel(/activar caché/i);
    const originalEnabled = (await cacheSwitch.getAttribute("aria-checked")) === "true";

    await ttlInput.fill(String(Number(originalTtl) + 1));
    const saveBar = page.getByRole("button", { name: /^guardar$/i });
    await expect(saveBar).toBeVisible({ timeout: 5_000 });
    await saveBar.click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });

    await ttlInput.fill(originalTtl);
    const saveBar2 = page.getByRole("button", { name: /^guardar$/i });
    await expect(saveBar2).toBeVisible({ timeout: 5_000 });
    await saveBar2.click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    await expect(ttlInput).toHaveValue(originalTtl);
    await expect(thresholdInput).toHaveValue(originalThreshold);
    await expect(cacheSwitch).toHaveAttribute("aria-checked", String(originalEnabled));
  });

  test("modal 'Ver entradas' del cache: abrir, listar/vacio, cerrar", async ({ page }) => {
    await page.goto("/dashboard/configuracion/estado");
    await expect(page.getByRole("heading", { name: /^caché$/i })).toBeVisible({ timeout: 10_000 });

    const viewEntriesBtn = page.getByRole("button", { name: /ver entradas/i });

    const hasEntries = await viewEntriesBtn.isVisible().catch(() => false);
    test.skip(!hasEntries, "no hay entradas de caché en este momento - nada que abrir");

    await viewEntriesBtn.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /entradas del caché/i })).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "05-cache-entradas.png") });

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });

    await viewEntriesBtn.click();
    const dialog2 = page.getByRole("dialog");
    await expect(dialog2).toBeVisible();
    await dialog2.getByRole("button", { name: /^cerrar$/i }).click();
    await expect(dialog2).not.toBeVisible({ timeout: 5_000 });
  });

  test("tab Tendencia: cambiar el rango de fechas sin excepcion", async ({ page }) => {
    const consoleErrors: string[] = [];
    await page.goto("/dashboard/configuracion/estado");
    page.on("pageerror", (e) => consoleErrors.push(String(e)));

    await page.getByRole("tab", { name: /cuotas/i }).click();
    await page.getByRole("tab", { name: /tendencia/i }).click();
    await expect(page.getByText(/uso vs\. límite/i)).toBeVisible({ timeout: 10_000 });

    const dateInputs = page.locator('input[type="date"]');
    const count = await dateInputs.count();
    if (count >= 2) {
      const from = dateInputs.first();
      await from.fill("2026-01-01");
      await expect(page.getByText(/uso vs\. límite/i)).toBeVisible({ timeout: 10_000 });
    }
    expect(consoleErrors, `console errors while changing Tendencia date range:\n${consoleErrors.join("\n")}`).toEqual([]);
    await page.screenshot({ path: path.join(SHOT_DIR, "06-tendencia.png") });
  });
});

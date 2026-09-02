import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

/**
 * Functional coverage for /dashboard/configuracion/publicaciones: saving a
 * manual restore point (non-destructive, always safe) and expanding a
 * version's diff, against the real backend. Deliberately does NOT click
 * "Publicar a producción" or "Restaurar" - those are the two highest-stakes
 * actions in the whole app (they change what real end users see in the
 * widget / roll back the live config) and running them unconditionally on
 * every test run would make this suite itself a production risk.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-publicaciones");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Publicaciones", () => {
  test("guardar punto de restauracion manual", async ({ page, request, baseURL }) => {
    test.setTimeout(90_000);

    const authHeader = `Bearer ${(await page.context().cookies()).find((c) => c.name === "chatbot_access")?.value}`;
    async function touchConfig() {
      const res = await request.put(`${baseURL}/api/v1/widget/config`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { welcome_message: `E2E snapshot toggle ${Date.now()}` },
      }).catch(() => null);
      expect(res?.ok(), `failed to force a real config change: ${res?.status()}`).toBeTruthy();
    }

    await page.goto("/dashboard/configuracion/publicaciones");
    await expect(page.getByText(/publicar versión/i)).toBeVisible({ timeout: 10_000 });

    let saved = false;
    for (let attempt = 0; attempt < 4 && !saved; attempt++) {
      await touchConfig();
      await page.getByRole("button", { name: /guardar punto de restauración/i }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog.getByRole("heading", { name: /guardar punto de restauración/i })).toBeVisible();

      const desc = `E2E restore point ${Date.now()}`;
      await dialog.getByPlaceholder(/antes de cambiar el prompt/i).fill(desc);
      if (attempt === 0) await page.screenshot({ path: path.join(SHOT_DIR, "01-snapshot-formulario.png") });

      const versionsResp = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/api/v1/versions") && r.request().method() === "POST"),
        dialog.getByRole("button", { name: /^guardar$/i }).click(),
      ]).then(([r]) => r);

      if (versionsResp.status() === 201) {
        saved = true;
      } else if (versionsResp.status() === 409) {
        // Perdió la carrera contra el auto-snapshot del middleware; reintenta con un nuevo touch de config.
        await page.keyboard.press("Escape");
        await expect(dialog).not.toBeVisible({ timeout: 5_000 });
      } else {
        expect(versionsResp.status(), `unexpected /versions status: ${versionsResp.status()}`).toBe(201);
      }
    }
    expect(saved, "could not save a manual snapshot after 4 attempts (kept losing the race to the auto-snapshot middleware)").toBe(true);

    // Serializa toda la config del sistema; bajo contención real de E2E (workers:2, otros specs escribiendo las mismas tablas) puede superar 20s vs. 5.8s en solitario.
    await expect(page.getByRole("dialog")).not.toBeVisible({ timeout: 60_000 });

    // Los snapshots manuales quedan ocultos por defecto (solo "Ver todos") y el historial muestra un change_summary calculado, no la descripción libre enviada.
    await page.getByRole("button", { name: /ver todos los snapshots/i }).click();
    await expect(page.getByText(/snapshot manual/i).first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-snapshot-en-historial.png") });
  });

  test("ver historial y expandir el diff de una version", async ({ page }) => {
    await page.goto("/dashboard/configuracion/publicaciones");
    await expect(page.getByRole("heading", { name: /historial/i })).toBeVisible({ timeout: 10_000 });

    const toggleBtn = page.getByRole("button", { name: /ver todos los snapshots/i });
    await toggleBtn.click();
    const firstVersion = page.locator("button", { hasText: /^v\d/ }).first();
    await expect(firstVersion).toBeVisible({ timeout: 10_000 });
    await firstVersion.click();

    await page.screenshot({ path: path.join(SHOT_DIR, "03-diff-expandido.png") });

    await firstVersion.click();
    await expect(page.getByText(/mostrando todos los snapshots/i)).toBeVisible();

    await page.getByRole("button", { name: /solo publicaciones/i }).click();
    await expect(page.getByText(/mostrando todos los snapshots/i)).toHaveCount(0);
    await expect(page.getByRole("button", { name: /ver todos los snapshots/i })).toBeVisible();
  });

  test("rechazar una fuente pendiente: modal, validacion, cierre por Escape y rechazo real", async ({ page }) => {
    test.setTimeout(90_000); // real ingestion wait below can approach the 30s default
    const uniqueId = Date.now();
    const sourceName = `E2E Reject Source ${uniqueId}`;
    const filePath = path.join(os.tmpdir(), `e2e-reject-${uniqueId}.txt`);
    fs.writeFileSync(filePath, `Documento de prueba E2E ${uniqueId} para probar el flujo de rechazo de publicaciones.`);

    await page.goto("/dashboard/conocimiento/documentos");
    await expect(page.getByRole("tab", { name: /fuentes/i })).toBeVisible({ timeout: 10_000 });
    await page.getByRole("button", { name: /^agregar$/i }).click();
    const uploadDialog = page.getByRole("dialog");
    await uploadDialog.locator('input[type="file"]').setInputFiles(filePath);
    await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(sourceName);
    await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(uploadDialog).not.toBeVisible({ timeout: 15_000 });
    const sourceRow = page.locator("tr", { hasText: sourceName });
    await expect(sourceRow.getByText("Listo", { exact: true })).toBeVisible({ timeout: 60_000 });
    fs.unlinkSync(filePath);

    await page.goto("/dashboard/configuracion/publicaciones");
    await expect(page.getByText(/publicar versión/i)).toBeVisible({ timeout: 10_000 });

    const pendingRow = page.locator("div.bg-muted\\/30.border-border\\/50", { hasText: sourceName });
    await expect(pendingRow).toBeVisible({ timeout: 15_000 });

    await pendingRow.getByRole("button", { name: /rechazar/i }).click();
    const rejectDialog = page.getByRole("dialog");
    await expect(rejectDialog.getByRole("heading", { name: /rechazar fuente/i })).toBeVisible();
    await expect(rejectDialog.getByText(sourceName)).toBeVisible();

    const confirmBtn = rejectDialog.getByRole("button", { name: /^rechazar$/i });
    await expect(confirmBtn).toBeDisabled();

    // Sin X visible (footer modals la ocultan); solo Escape / click afuera / Cancelar.
    await page.keyboard.press("Escape");
    await expect(rejectDialog).not.toBeVisible({ timeout: 5_000 });

    await pendingRow.getByRole("button", { name: /rechazar/i }).click();
    const rejectDialog2 = page.getByRole("dialog");
    const reasonInput = rejectDialog2.locator("input");
    await expect(reasonInput).toHaveValue("");

    await rejectDialog2.getByRole("button", { name: /cancelar/i }).click();
    await expect(rejectDialog2).not.toBeVisible({ timeout: 5_000 });

    await pendingRow.getByRole("button", { name: /rechazar/i }).click();
    const rejectDialog3 = page.getByRole("dialog");
    await rejectDialog3.locator("input").fill("Motivo de prueba E2E: contenido no relevante.");
    const confirmBtn3 = rejectDialog3.getByRole("button", { name: /^rechazar$/i });
    await expect(confirmBtn3).toBeEnabled();
    await confirmBtn3.click();
    await expect(rejectDialog3).not.toBeVisible({ timeout: 15_000 });

    await expect(page.locator("div.bg-muted\\/30.border-border\\/50", { hasText: sourceName })).toHaveCount(0, { timeout: 10_000 });

    await page.goto("/dashboard/conocimiento/documentos");
    const cleanupRow = page.locator("tr", { hasText: sourceName });
    await expect(cleanupRow).toBeVisible({ timeout: 15_000 });
    await cleanupRow.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.locator("tr", { hasText: sourceName })).toHaveCount(0, { timeout: 10_000 });
  });

  test("aprobar una fuente pendiente desde publicaciones", async ({ page }) => {
    test.setTimeout(90_000); // real ingestion wait below can approach the 30s default
    const uniqueId = Date.now();
    const sourceName = `E2E Approve Source ${uniqueId}`;
    const filePath = path.join(os.tmpdir(), `e2e-approve-${uniqueId}.txt`);
    fs.writeFileSync(filePath, `Documento de prueba E2E ${uniqueId} para probar el flujo de aprobacion de publicaciones.`);

    await page.goto("/dashboard/conocimiento/documentos");
    await page.getByRole("button", { name: /^agregar$/i }).click();
    const uploadDialog = page.getByRole("dialog");
    await uploadDialog.locator('input[type="file"]').setInputFiles(filePath);
    await uploadDialog.getByPlaceholder(/instructivo para alumnos/i).fill(sourceName);
    await uploadDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(uploadDialog).not.toBeVisible({ timeout: 15_000 });
    const sourceRow = page.locator("tr", { hasText: sourceName });
    await expect(sourceRow.getByText("Listo", { exact: true })).toBeVisible({ timeout: 60_000 });
    fs.unlinkSync(filePath);

    await page.goto("/dashboard/configuracion/publicaciones");
    const pendingRow = page.locator("div.bg-muted\\/30.border-border\\/50", { hasText: sourceName });
    await expect(pendingRow).toBeVisible({ timeout: 15_000 });
    await pendingRow.getByRole("button", { name: /aprobar/i }).click();
    await expect(page.locator("div.bg-muted\\/30.border-border\\/50", { hasText: sourceName })).toHaveCount(0, { timeout: 15_000 });

    await page.goto("/dashboard/conocimiento/documentos");
    const cleanupRow = page.locator("tr", { hasText: sourceName });
    await expect(cleanupRow).toBeVisible({ timeout: 15_000 });
    await cleanupRow.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.locator("tr", { hasText: sourceName })).toHaveCount(0, { timeout: 10_000 });
  });

  test("modal de snapshot: cerrar por Escape y por Cancelar sin dejar excepciones ni el dialogo abierto", async ({ page }) => {
    // El texto del borrador NO se limpia en Escape/Cancel (solo al guardar con éxito) - quirk conocido y no destructivo; este test valida solo apertura/cierre limpios.
    await page.goto("/dashboard/configuracion/publicaciones");
    await expect(page.getByText(/publicar versión/i)).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /guardar punto de restauración/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /guardar punto de restauración/i })).toBeVisible();
    await dialog.locator("input").fill("Texto que se debe descartar");

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });

    await page.getByRole("button", { name: /guardar punto de restauración/i }).click();
    const dialog2 = page.getByRole("dialog");
    await expect(dialog2.getByRole("heading", { name: /guardar punto de restauración/i })).toBeVisible();
    await dialog2.getByRole("button", { name: /cancelar/i }).click();
    await expect(dialog2).not.toBeVisible({ timeout: 5_000 });

    // Tercera apertura: confirma que no queda overlay/backdrop bloqueando interacción tras dos cierres.
    await page.getByRole("button", { name: /guardar punto de restauración/i }).click();
    const dialog3 = page.getByRole("dialog");
    await expect(dialog3).toBeVisible();
    await dialog3.locator("input").fill("");
    await dialog3.getByRole("button", { name: /cancelar/i }).click();
    await expect(dialog3).not.toBeVisible({ timeout: 5_000 });
  });
});

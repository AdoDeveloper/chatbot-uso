import { test, expect } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/**
 * Coverage for POST /settings/import ("Importar"), the write-side
 * counterpart of "exportar la configuracion" (already covered in
 * configuracion-asistente.spec.ts). Disposable-safe: exports the CURRENT
 * settings first, then re-imports that exact same file - net effect on
 * the system is zero (same idea as the version-rollback round-trip), but
 * the real import code path (multipart upload, ChatbotSettings validation,
 * settings invalidation) runs end-to-end.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

test.describe("Configuracion > Asistente > Importar", () => {
  test("exportar y reimportar la misma configuracion (round-trip sin efecto neto)", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/dashboard/configuracion/asistente");
    await expect(page.getByRole("button", { name: /exportar/i })).toBeVisible({ timeout: 10_000 });

    const downloadPromise = page.waitForEvent("download", { timeout: 15_000 });
    await page.getByRole("button", { name: /exportar/i }).click();
    const download = await downloadPromise;
    const tempPath = await download.path();
    expect(tempPath).toBeTruthy();
    // El backend exige que el filename termine en .json; download.path()
    // guarda el archivo con un nombre temporal de Playwright que no
    // conserva la extensión, asi que se copia con el nombre real sugerido
    // (suggestedFilename ya es "...json" segun el Content-Disposition).
    const filePath = path.join(os.tmpdir(), download.suggestedFilename());
    fs.copyFileSync(tempPath!, filePath);

    const fileInput = page.locator('input[type="file"][accept=".json"]');
    const [importResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/v1/settings/import") && r.request().method() === "POST"),
      fileInput.setInputFiles(filePath),
    ]);
    expect(importResp.status(), `unexpected /settings/import status: ${importResp.status()}`).toBe(200);

    await expect(page.getByText(/configuración importada|importado con advertencias/i)).toBeVisible({ timeout: 10_000 });
    fs.unlinkSync(filePath);
  });
});

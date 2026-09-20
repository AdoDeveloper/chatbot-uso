import { test, expect } from "@playwright/test";

/**
 * Coverage for DELETE /cache/clear ("Limpiar caché completo") and
 * DELETE /maintenance/health-snapshots/outliers ("Limpiar P99"), both
 * deliberately excluded from configuracion-estado.spec.ts's header comment
 * as "destructive/irreversible". Unlike the SSO/rollback cases, neither
 * needs a disposable-data round-trip: both only delete regenerable data
 * (cached LLM responses, historical latency outliers) with no config or
 * access-control side effect - safe to run unconditionally, idempotent
 * (running with nothing to delete just returns deleted: 0).
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

test.describe("Configuracion > Estado > Mantenimiento destructivo (seguro de repetir)", () => {
  test("limpiar cache completo", async ({ page }) => {
    await page.goto("/dashboard/configuracion/estado");
    await expect(page.getByRole("heading", { name: /^caché$/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /^limpiar caché$/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(confirmDialog.getByRole("heading")).toContainText(/limpiar/i);
    const [clearResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/v1/cache/clear") && r.request().method() === "DELETE"),
      confirmDialog.getByRole("button", { name: /limpiar caché/i }).click(),
    ]);
    expect(clearResp.status(), `unexpected /cache/clear status: ${clearResp.status()}`).toBe(200);
    const body: { deleted: number } = await clearResp.json();
    expect(typeof body.deleted).toBe("number");
  });

  test("limpiar historial de salud (purgar outliers > 2s)", async ({ page }) => {
    await page.goto("/dashboard/configuracion/estado");
    await expect(page.getByRole("heading", { name: /salud de los servicios/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /^limpiar p99$/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(confirmDialog.getByRole("heading")).toContainText(/limpiar historial/i);
    const [purgeResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/health-snapshots/outliers") && r.request().method() === "DELETE"),
      confirmDialog.getByRole("button", { name: /limpiar historial/i }).click(),
    ]);
    expect(purgeResp.status(), `unexpected purge status: ${purgeResp.status()}`).toBe(200);
    const body: { deleted: number; threshold_ms: number } = await purgeResp.json();
    expect(typeof body.deleted).toBe("number");
    expect(body.threshold_ms).toBe(2000);
  });
});

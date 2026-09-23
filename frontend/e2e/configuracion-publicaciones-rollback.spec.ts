import { test, expect } from "@playwright/test";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

test.describe("Configuracion > Publicaciones > Restaurar", () => {
  test("crear snapshot desechable y restaurar a la version anterior (round-trip sin efecto neto)", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/dashboard/configuracion/publicaciones");
    await expect(page.getByRole("heading", { name: /historial/i }).first()).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /ver todo el historial/i }).click();

    await page.getByRole("button", { name: /guardar punto de restauración/i }).click();
    const snapshotDialog = page.getByRole("dialog");
    await snapshotDialog.getByPlaceholder(/antes de cambiar el prompt/i).fill(`E2E rollback probe ${Date.now()}`);
    const [versionsResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/v1/versions") && r.request().method() === "POST"),
      snapshotDialog.getByRole("button", { name: /^guardar$/i }).click(),
    ]);
    expect(versionsResp.status(), `unexpected /versions status: ${versionsResp.status()}`).toBe(201);
    await expect(snapshotDialog).not.toBeVisible({ timeout: 60_000 });
    const newVersion: { version_number: number } = await versionsResp.json();
    const previousVersionNumber = newVersion.version_number - 1;

    const targetRow = page.locator("div.overflow-hidden", {
      has: page.getByText(new RegExp(`^v${previousVersionNumber}$`)),
    }).first();
    await expect(targetRow).toBeVisible({ timeout: 10_000 });
    await expect(targetRow.getByRole("button", { name: /^restaurar$/i })).toBeVisible({ timeout: 10_000 });
    await targetRow.getByRole("button", { name: /^restaurar$/i }).click();

    const rollbackDialog = page.getByRole("dialog");
    await expect(rollbackDialog.getByRole("heading", { name: new RegExp(`restaurar a v${previousVersionNumber}$`, "i") })).toBeVisible();
    const [rollbackResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/rollback") && r.request().method() === "POST"),
      rollbackDialog.getByRole("button", { name: /^restaurar$/i }).click(),
    ]);
    expect(rollbackResp.status(), `unexpected rollback status: ${rollbackResp.status()}`).toBe(200);
    await expect(rollbackDialog).not.toBeVisible({ timeout: 15_000 });

    const newestRow = page.locator("div.overflow-hidden", {
      has: page.getByText(/último registro/i),
    }).first();
    await expect(newestRow.getByText(new RegExp(`restauraci[oó]n a v${previousVersionNumber}`, "i"))).toBeVisible({ timeout: 10_000 });
  });
});

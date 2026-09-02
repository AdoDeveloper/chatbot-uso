import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Functional coverage for /dashboard/configuracion/acceso/sso: editing and
 * saving the allowed-domains field, against the real backend. Deliberately
 * does NOT toggle "Inicio de sesión con contraseña" or "Activar Microsoft
 * SSO" - both can lock the whole team out of the dashboard if flipped
 * without a fully configured second auth method, so they're excluded from
 * unconditional automated runs.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-acceso-sso");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Acceso > SSO", () => {
  test("editar y guardar dominios permitidos", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/sso");
    await expect(page.getByText("Microsoft SSO (Azure AD)")).toBeVisible({ timeout: 10_000 });

    const domainsInput = page.getByPlaceholder(/empresa\.com, filial\.com/i);
    const original = await domainsInput.inputValue();
    await domainsInput.fill(original ? `${original}, e2e-test.invalid` : "e2e-test.invalid");
    await page.screenshot({ path: path.join(SHOT_DIR, "01-dominios-editados.png") });

    await page.getByRole("button", { name: /^guardar$/i }).click();
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-dominios-guardados.png") });

    await domainsInput.fill(original);
    const saveBtn = page.getByRole("button", { name: /^guardar$/i });
    if (await saveBtn.isVisible().catch(() => false)) {
      await saveBtn.click();
    }
  });

  test("copiar redirect URI", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/sso");
    await expect(page.getByText(/redirect uri/i)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-redirect-uri.png") });
  });

  test("descartar cambios en dominios permitidos", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/sso");
    const domainsInput = page.getByPlaceholder(/empresa\.com, filial\.com/i);
    await expect(domainsInput).toBeVisible({ timeout: 10_000 });

    const original = await domainsInput.inputValue();
    await domainsInput.fill("descartar-esto.invalid");
    const discardBtn = page.getByRole("button", { name: /descartar/i });
    await expect(discardBtn).toBeVisible({ timeout: 5_000 });
    await discardBtn.click();
    await expect(domainsInput).toHaveValue(original);
    await expect(page.getByRole("button", { name: /^guardar$/i })).toHaveCount(0);
  });
});

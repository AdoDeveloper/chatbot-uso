import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-proveedores-tipos");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Proveedores > Tipos de proveedor", () => {
  test("crear, editar y eliminar un tipo de proveedor del catalogo", async ({ page }) => {
    const typeKey = `e2e_type_${Date.now()}`;
    const displayName = `E2E Type ${Date.now()}`;
    const renamedDisplayName = `${displayName} (editado)`;

    await page.goto("/dashboard/configuracion/proveedores");
    const typesSection = page.locator("div", { has: page.getByText("Tipos de proveedor", { exact: true }) })
      .filter({ has: page.getByRole("button", { name: /^agregar$/i }) }).last();
    await expect(typesSection.getByRole("button", { name: /^agregar$/i })).toBeVisible({ timeout: 10_000 });
    const catalogCard = page.locator("table").filter({ has: page.getByRole("columnheader", { name: /^clave$/i }) });

    await typesSection.getByRole("button", { name: /^agregar$/i }).click();
    const createDialog = page.getByRole("dialog");
    await expect(createDialog.getByRole("heading", { name: /agregar tipo de proveedor/i })).toBeVisible();

    await createDialog.getByPlaceholder("ej. together", { exact: true }).fill(typeKey);
    await createDialog.getByPlaceholder(/together ai/i).fill(displayName);

    await createDialog.getByRole("button", { name: /^agregar$/i }).first().click();
    await createDialog.getByPlaceholder(/nombre-header/i).fill("x-e2e-test");
    await createDialog.getByPlaceholder(/^valor$/i).fill("1");

    await page.screenshot({ path: path.join(SHOT_DIR, "01-crear-formulario.png") });

    await createDialog.getByRole("button", { name: /^agregar$/i }).last().click();
    await expect(createDialog).not.toBeVisible({ timeout: 10_000 });

    const row = catalogCard.locator("tr", { hasText: typeKey });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-creado-en-tabla.png") });

    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /^editar$/i }).click();
    const editDialog = page.getByRole("dialog");
    await expect(editDialog.getByRole("heading", { name: /editar tipo de proveedor/i })).toBeVisible();
    await editDialog.getByPlaceholder(/together ai/i).fill(renamedDisplayName);
    await editDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(editDialog).not.toBeVisible({ timeout: 10_000 });

    const renamedRow = catalogCard.locator("tr", { hasText: renamedDisplayName });
    await expect(renamedRow).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-editado.png") });

    await renamedRow.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /^eliminar$/i }).click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(confirmDialog.getByRole("heading")).toContainText(/eliminar/i);
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();

    await expect(catalogCard.locator("tr", { hasText: typeKey })).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-eliminado.png") });
  });
});

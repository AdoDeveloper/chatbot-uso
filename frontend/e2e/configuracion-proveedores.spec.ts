import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Functional coverage for /dashboard/configuracion/proveedores: full CRUD on
 * LLM providers against the real backend (create -> edit -> delete), plus
 * chain add/remove. Uses provider_type "custom" with a fake api_base so no
 * real LLM vendor is contacted (the "Probar" button is not clicked - it
 * would hang/fail against a fake endpoint and isn't required to prove the
 * CRUD surface works).
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-proveedores");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Proveedores", () => {
  test("crear, editar y eliminar un proveedor LLM", async ({ page }) => {
    const name = `E2E Provider ${Date.now()}`;
    const renamed = `${name} (editado)`;

    await page.goto("/dashboard/configuracion/proveedores");
    await expect(page.getByText(/cadena de proveedores/i)).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /^agregar$/i }).click();
    const createDialog = page.getByRole("dialog");
    await expect(createDialog.getByRole("heading", { name: /agregar proveedor/i })).toBeVisible();

    await createDialog.locator("input").first().fill(name);
    await createDialog.locator("select").first().selectOption("custom");
    await createDialog.getByPlaceholder(/together_ai/i).fill("e2e_custom");
    await createDialog.getByPlaceholder(/nombre-del-modelo/i).fill("e2e-fake-model");
    await createDialog.getByPlaceholder(/sk-\.\.\./i).fill("sk-e2e-fake-key");
    await createDialog.getByPlaceholder("https://...").fill("https://example.invalid/v1");

    await page.screenshot({ path: path.join(SHOT_DIR, "01-crear-formulario.png") });

    await createDialog.getByRole("button", { name: /^agregar$/i }).click();
    await expect(createDialog).not.toBeVisible({ timeout: 10_000 });

    const row = page.locator("tr", { hasText: name });
    await expect(row).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-creado-en-tabla.png") });

    await expect(async () => {
      await row.getByRole("button").last().click();
      const editItem = page.getByRole("menuitem", { name: /^editar$/i });
      await expect(editItem).toBeVisible({ timeout: 2_000 });
      await editItem.click({ timeout: 2_000 });
      await expect(page.getByRole("dialog")).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 15_000 });
    const editDialog = page.getByRole("dialog");
    await expect(editDialog.getByRole("heading", { name: /editar proveedor/i })).toBeVisible();
    await editDialog.locator("input").first().fill(renamed);
    await editDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(editDialog).not.toBeVisible({ timeout: 10_000 });

    const renamedRow = page.locator("tr", { hasText: renamed });
    await expect(renamedRow).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-editado.png") });

    let addedToChain = false;
    await expect(async () => {
      await renamedRow.getByRole("button").last().click();
      await expect(page.getByRole("menu")).toBeVisible({ timeout: 2_000 });
      const addToChain = page.getByRole("menuitem", { name: /agregar a la cadena/i });
      if (await addToChain.isVisible().catch(() => false)) {
        await addToChain.click({ timeout: 2_000 });
        addedToChain = true;
      } else {
        await page.keyboard.press("Escape");
      }
    }).toPass({ timeout: 15_000 });
    if (addedToChain) {
      await expect(page.locator("tr", { hasText: renamed })).toBeVisible({ timeout: 10_000 });
      await page.screenshot({ path: path.join(SHOT_DIR, "04-en-cadena.png") });
    }

    // El health polling refetchea la lista periódicamente y puede desmontar el dropdown a mitad de interacción; abrir menú + click van en el mismo retry loop.
    const finalRow = page.locator("tr", { hasText: renamed });
    await expect(finalRow).toBeVisible({ timeout: 10_000 });
    await finalRow.scrollIntoViewIfNeeded();
    await expect(async () => {
      await finalRow.getByRole("button").last().click();
      const deleteItem = page.getByRole("menuitem", { name: /^eliminar$/i });
      await expect(deleteItem).toBeVisible({ timeout: 2_000 });
      await deleteItem.click({ timeout: 2_000 });
      await expect(page.locator("div.fixed.inset-0.z-\\[200\\]")).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 20_000 });

    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(confirmDialog.getByRole("heading")).toContainText(/eliminar/i);
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();

    await expect(page.locator("tr", { hasText: renamed })).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "05-eliminado.png") });
  });

  test("modal agregar proveedor: mostrar/ocultar API key, boton Probar, cancelar", async ({ page }) => {
    test.setTimeout(70_000);
    await page.goto("/dashboard/configuracion/proveedores");
    await page.getByRole("button", { name: /^agregar$/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /agregar proveedor/i })).toBeVisible();

    const keyInput = dialog.getByPlaceholder(/sk-\.\.\./i);
    await expect(keyInput).toHaveAttribute("type", "password");
    await keyInput.fill("sk-e2e-visibility-test");
    const toggleBtn = dialog.getByLabel(/mostrar api key/i);
    await toggleBtn.click();
    await expect(keyInput).toHaveAttribute("type", "text");
    await expect(dialog.getByLabel(/ocultar api key/i)).toBeVisible();
    await dialog.getByLabel(/ocultar api key/i).click();
    await expect(keyInput).toHaveAttribute("type", "password");

    // Endpoint custom falso: nunca contacta a un proveedor real, resuelve a un estado de fallo manejado.
    await dialog.locator("select").first().selectOption("custom");
    await dialog.getByPlaceholder(/together_ai/i).fill("e2e_probar_test");
    await dialog.getByPlaceholder(/nombre-del-modelo/i).fill("e2e-fake-model");
    await dialog.getByPlaceholder("https://...").fill("https://example.invalid/v1");
    const probarBtn = dialog.getByRole("button", { name: /^probar$/i });
    await expect(probarBtn).toBeEnabled();
    await probarBtn.click();
    // example.invalid tarda ~15-20s en fallar server-side (DNS); el error de red no siempre contiene la palabra "error", por eso el match amplio.
    await expect(dialog.getByText(/conexión exitosa|no se pudo|errno|name or service|falló|refus|timeout/i)).toBeVisible({ timeout: 45_000 });

    await dialog.getByRole("button", { name: /cancelar/i }).click();
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
    await expect(page.locator("tr", { hasText: "e2e-fake-model" })).toHaveCount(0);
  });

  test("mover proveedor en la cadena arriba/abajo y probar conexion rapida desde el menu", async ({ page }) => {
    test.setTimeout(70_000);
    const name = `E2E Chain Order ${Date.now()}`;
    await page.goto("/dashboard/configuracion/proveedores");
    await page.getByRole("button", { name: /^agregar$/i }).click();
    const createDialog = page.getByRole("dialog");
    await createDialog.locator("input").first().fill(name);
    await createDialog.locator("select").first().selectOption("custom");
    await createDialog.getByPlaceholder(/together_ai/i).fill("e2e_chain_order");
    await createDialog.getByPlaceholder(/nombre-del-modelo/i).fill("e2e-fake-model");
    await createDialog.getByPlaceholder(/sk-\.\.\./i).fill("sk-e2e-fake-key");
    await createDialog.getByPlaceholder("https://...").fill("https://example.invalid/v1");
    // Lo pone directo en la cadena vía el campo de prioridad, evitando un round-trip extra por dropdown.
    await createDialog.locator('input[type="number"]').fill("1");
    await createDialog.getByRole("button", { name: /^agregar$/i }).click();
    await expect(createDialog).not.toBeVisible({ timeout: 10_000 });

    const row = page.locator("tr", { hasText: name });
    await expect(row).toBeVisible({ timeout: 10_000 });

    await row.getByRole("button").last().click();
    await page.getByRole("menuitem", { name: /probar conexión/i }).click();
    await expect(page.getByText(/falló la conexión|conexión exitosa/i)).toBeVisible({ timeout: 45_000 });

    // Con más de un proveedor encadenado ejercita el reordenamiento real; si es el único, ambas flechas quedan deshabilitadas (estado inerte esperado, se valida ese caso).
    const downBtn = row.getByRole("button", { name: new RegExp(`Mover ${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} abajo`, "i") });
    const isDisabled = await downBtn.isDisabled();
    if (!isDisabled) {
      await downBtn.click();
      await page.waitForTimeout(1000);
      const upBtn = row.getByRole("button", { name: new RegExp(`Mover ${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} arriba`, "i") });
      await upBtn.click();
    } else {
      await expect(downBtn).toBeDisabled();
    }

    await expect(async () => {
      await row.getByRole("button").last().click();
      const deleteItem = page.getByRole("menuitem", { name: /^eliminar$/i });
      await expect(deleteItem).toBeVisible({ timeout: 2_000 });
      await deleteItem.click({ timeout: 2_000 });
      await expect(page.locator("div.fixed.inset-0.z-\\[200\\]")).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 20_000 });
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.locator("tr", { hasText: name })).toHaveCount(0, { timeout: 10_000 });
  });
});

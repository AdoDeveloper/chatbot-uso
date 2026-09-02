import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Coverage for /dashboard/configuracion/acceso/usuarios beyond invitaciones.spec.ts: full invitation lifecycle against the real backend using a disposable @invalid address, plus editing the logged-in admin's own display name (the only user edit safe to run unconditionally). Never touches "Resetear contraseña" or "Eliminar" on a real user account.
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-acceso-usuarios");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Acceso > Usuarios", () => {
  test("invitar, reenviar, revocar y eliminar una invitacion", async ({ page }) => {
    const email = `e2e-test-${Date.now()}@invalid.example`;

    await page.goto("/dashboard/configuracion/acceso/usuarios");
    await expect(page.getByRole("button", { name: /invitar usuario/i })).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /invitar usuario/i }).click();
    const inviteDialog = page.getByRole("dialog");
    await expect(inviteDialog.getByRole("heading", { name: /invitar usuario/i })).toBeVisible();
    await inviteDialog.locator('input[type="email"]').fill(email);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-invitar-formulario.png") });
    await inviteDialog.getByRole("button", { name: /enviar invitación/i }).click();
    await expect(inviteDialog.getByRole("button", { name: /copiar enlace/i })).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-invitacion-creada.png") });
    await inviteDialog.getByRole("button", { name: /^cerrar$/i }).click();

    const row = page.locator("tr", { hasText: email });
    await expect(row).toBeVisible({ timeout: 10_000 });

    await row.locator('button[title="Reenviar"]').click();
    const resendConfirm = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(resendConfirm.getByRole("heading")).toContainText(/reenviar/i);
    await resendConfirm.getByRole("button", { name: /reenviar/i }).click();
    await page.screenshot({ path: path.join(SHOT_DIR, "03-invitacion-reenviada.png") });

    await row.locator('button[title="Revocar"]').click();
    const revokeConfirm = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(revokeConfirm.getByRole("heading")).toContainText(/revocar/i);
    await revokeConfirm.getByRole("button", { name: /revocar/i }).click();
    await expect(row.getByText(/revocada/i)).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-invitacion-revocada.png") });

    await row.locator('button[title="Eliminar"]').click();
    const deleteConfirm = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(deleteConfirm.getByRole("heading")).toContainText(/eliminar/i);
    await deleteConfirm.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.locator("tr", { hasText: email })).toHaveCount(0, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "05-invitacion-eliminada.png") });
  });

  test("editar el nombre para mostrar del usuario actual", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/usuarios");
    await expect(page.getByRole("heading", { name: /equipo/i })).toBeVisible({ timeout: 10_000 });

    const ownRow = page.locator("tr", { hasText: E2E_USER! });
    await expect(ownRow).toBeVisible({ timeout: 10_000 });
    await ownRow.locator('button[title="Editar"]').click();
    const editDialog = page.getByRole("dialog");
    await expect(editDialog.getByRole("heading", { name: /editar usuario/i })).toBeVisible();

    await expect(editDialog.getByText(/no puede cambiar su propio rol/i)).toBeVisible();
    await expect(editDialog.locator('[role="switch"]')).toHaveCount(0);

    const nameInput = editDialog.locator("input").first();
    const original = await nameInput.inputValue();
    await nameInput.fill(original);
    await page.screenshot({ path: path.join(SHOT_DIR, "06-editar-usuario.png") });
    await editDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(editDialog).not.toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "07-usuario-editado.png") });
  });

  test("modal invitar: validacion de correo invalido, cierre por Escape y por Cancelar", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/usuarios");
    await page.getByRole("button", { name: /invitar usuario/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /invitar usuario/i })).toBeVisible();

    await dialog.locator('input[type="email"]').fill("no-es-un-correo");
    await dialog.getByRole("button", { name: /enviar invitación/i }).click();
    await expect(dialog.getByText(/correo válido/i)).toBeVisible({ timeout: 5_000 });
    await expect(dialog).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });

    await page.getByRole("button", { name: /invitar usuario/i }).click();
    const dialog2 = page.getByRole("dialog");
    await expect(dialog2.locator('input[type="email"]')).toHaveValue("");
    await expect(dialog2.getByText(/correo válido/i)).toHaveCount(0);

    await dialog2.getByRole("button", { name: /cancelar/i }).click();
    await expect(dialog2).not.toBeVisible({ timeout: 5_000 });

    await expect(page.getByRole("button", { name: /invitar usuario/i })).toBeEnabled();
  });

  test("select de rol: las tres opciones (viewer/editor/admin) se pueden elegir en el formulario de invitar", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/usuarios");
    await page.getByRole("button", { name: /invitar usuario/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /invitar usuario/i })).toBeVisible();

    const roleSelect = dialog.locator("select");
    for (const value of ["viewer", "editor", "admin"]) {
      await roleSelect.selectOption(value);
      await expect(roleSelect).toHaveValue(value);
    }

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });

  test("slider de validez del enlace: mueve dias entre 1 y 30", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/usuarios");
    await page.getByRole("button", { name: /invitar usuario/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText(/expira el/i)).toBeVisible();

    const slider = dialog.locator('input[type="range"]');
    await expect(slider).toBeVisible();
    await expect(dialog.getByText(/^7 días$/)).toBeVisible();

    await slider.focus();
    await page.keyboard.press("Home");
    await expect(dialog.getByText(/^1 día$/)).toBeVisible();
    await page.keyboard.press("End");
    await expect(dialog.getByText(/^30 días$/)).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });

  test("ciclo completo de un usuario de prueba: invitar, aceptar, editar rol/estado, resetear contrasena, eliminar", async ({ page, request }) => {
    const email = `e2e-lifecycle-${Date.now()}@invalid.example`;
    const tempPass = "TempPass!2026x";
    await page.context().grantPermissions(["clipboard-write", "clipboard-read"]);

    await page.goto("/dashboard/configuracion/acceso/usuarios");
    await page.getByRole("button", { name: /invitar usuario/i }).click();
    const inviteDialog = page.getByRole("dialog");
    await inviteDialog.locator('input[type="email"]').fill(email);
    await inviteDialog.getByRole("button", { name: /enviar invitación/i }).click();
    await expect(inviteDialog.getByRole("button", { name: /copiar enlace/i })).toBeVisible({ timeout: 10_000 });

    await inviteDialog.getByRole("button", { name: /copiar enlace/i }).click();
    await expect(inviteDialog.getByText(/¡copiado!/i)).toBeVisible({ timeout: 5_000 });
    await inviteDialog.getByRole("button", { name: /^cerrar$/i }).click();
    await expect(inviteDialog).not.toBeVisible({ timeout: 5_000 });

    const row = page.locator("tr", { hasText: email });
    await expect(row).toBeVisible({ timeout: 10_000 });

    const baseURL = "http://localhost:3000";
    const authHeader = `Bearer ${(await page.context().cookies()).find((c) => c.name === "chatbot_access")?.value}`;
    const invitesResp = await request.get(`${baseURL}/api/v1/users/invitations?page=1&page_size=50`, {
      headers: { Authorization: authHeader },
    });
    const invitesJson = await invitesResp.json();
    const invite = (invitesJson.items as Array<{ email: string; token: string; id: string }>).find((i) => i.email === email);
    expect(invite, "invitation for the disposable user must exist via API").toBeTruthy();

    const acceptResp = await request.post(`${baseURL}/api/v1/auth/invite/${invite!.token}/accept`, {
      headers: { "Content-Type": "application/json" },
      data: { password: tempPass, full_name: "E2E Lifecycle User" },
    });
    expect(acceptResp.ok(), `accept invitation failed: ${acceptResp.status()} ${await acceptResp.text()}`).toBeTruthy();

    await page.reload();
    const equipoTable = page.locator("table", { has: page.getByRole("columnheader", { name: /último acceso/i }) });
    const userRow = equipoTable.locator("tr", { hasText: email });
    await expect(userRow).toBeVisible({ timeout: 10_000 });
    await userRow.locator('button[title="Editar"]').click();
    const editDialog = page.getByRole("dialog");
    await expect(editDialog.getByRole("heading", { name: /editar usuario/i })).toBeVisible();

    const roleSelect = editDialog.locator("select");
    await expect(roleSelect).toBeVisible();
    await roleSelect.selectOption("editor");

    const statusSwitch = editDialog.locator('[role="switch"]');
    await expect(statusSwitch).toBeVisible();
    await expect(statusSwitch).toHaveAttribute("aria-checked", "true");
    await statusSwitch.click();
    await expect(statusSwitch).toHaveAttribute("aria-checked", "false");
    await expect(editDialog.getByText(/^inactivo$/i)).toBeVisible();
    await statusSwitch.click();
    await expect(statusSwitch).toHaveAttribute("aria-checked", "true");

    await editDialog.getByRole("button", { name: /^guardar$/i }).click();
    await expect(editDialog).not.toBeVisible({ timeout: 10_000 });
    await expect(userRow.getByText(/editor/i)).toBeVisible({ timeout: 10_000 });

    await userRow.locator('button[title="Resetear contraseña"]').click();
    const resetConfirm = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(resetConfirm.getByRole("heading")).toContainText(/resetear/i);
    await resetConfirm.getByRole("button", { name: /resetear/i }).click();

    const resetDialog = page.getByRole("dialog");
    await expect(resetDialog.getByRole("heading", { name: /contraseña temporal/i })).toBeVisible({ timeout: 10_000 });
    const tempPasswordCode = resetDialog.locator("code");
    await expect(tempPasswordCode).not.toHaveText("");
    await resetDialog.getByTitle("Copiar").click();
    await resetDialog.getByRole("button", { name: /entendido/i }).click();
    await expect(resetDialog).not.toBeVisible({ timeout: 5_000 });

    await userRow.locator('button[title="Eliminar"]').click();
    const deleteConfirm = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(deleteConfirm.getByRole("heading")).toContainText(/eliminar/i);
    await deleteConfirm.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(equipoTable.locator("tr", { hasText: email })).toHaveCount(0, { timeout: 10_000 });
  });
});

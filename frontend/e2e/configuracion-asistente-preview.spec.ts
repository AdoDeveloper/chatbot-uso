import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Coverage for the "Previsualizar" tab of /dashboard/configuracion/asistente (PlaygroundTab) - a live simulated widget running the real chat pipeline end to end.
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "configuracion-asistente-preview");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Configuracion > Asistente > Previsualizar", () => {
  test("abrir/cerrar el launcher, cambiar entorno Pruebas/Produccion, enviar un mensaje real", async ({ page }) => {
    const consoleErrors: string[] = [];
    await page.goto("/dashboard/configuracion/asistente?tab=previsualizar");
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
    await expect(page.getByText(/vista previa/i).first()).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: /producción/i }).click();
    await expect(page.getByText(/entorno de producción/i)).toBeVisible({ timeout: 5_000 });
    await page.getByRole("button", { name: /pruebas/i }).click();
    await expect(page.getByText(/entorno de pruebas/i)).toBeVisible({ timeout: 5_000 });

    await expect(page.getByPlaceholder(/escribe un mensaje/i)).toBeVisible({ timeout: 10_000 });
    const minimizeBtn = page.getByRole("button", { name: /minimizar chat/i });
    await expect(minimizeBtn).toBeVisible();
    await minimizeBtn.click();
    const reopenBtn = page.getByRole("button", { name: /abrir chat/i });
    await expect(reopenBtn).toBeVisible({ timeout: 5_000 });
    await reopenBtn.click();
    await expect(page.getByPlaceholder(/escribe un mensaje/i)).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "01-widget-abierto.png") });

    const input = page.getByPlaceholder(/escribe un mensaje/i);
    await input.fill("Hola, esto es un mensaje de prueba E2E del previsualizador.");
    const sendBtn = page.getByRole("button").filter({ has: page.locator("svg") }).last();
    await input.press("Enter");
    await expect(page.locator(".animate-spin")).toHaveCount(0, { timeout: 30_000 });
    void sendBtn;
    await page.screenshot({ path: path.join(SHOT_DIR, "02-mensaje-enviado.png") });

    expect(consoleErrors, `console errors in preview:\n${consoleErrors.join("\n")}`).toEqual([]);

    await page.getByRole("button", { name: "Cerrar", exact: true }).click();
    await expect(page.getByRole("button", { name: /abrir chat/i })).toBeVisible({ timeout: 5_000 });
  });

  test("escalamiento: prompt si/no, formulario de contacto (correo y whatsapp) con validacion", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=previsualizar");
    await expect(page.getByPlaceholder(/escribe un mensaje/i)).toBeVisible({ timeout: 10_000 });

    const input = page.getByPlaceholder(/escribe un mensaje/i);
    await input.fill("quiero hablar con un humano");
    await input.press("Enter");

    const yesBtn = page.getByRole("button", { name: "Sí", exact: true });
    if (!(await yesBtn.isVisible({ timeout: 5_000 }).catch(() => false))) {
      test.skip(true, "Escalamiento deshabilitado en la configuración actual del widget");
    }

    await page.getByRole("button", { name: "No", exact: true }).click();
    await expect(page.getByText(/desea continuar con el asistente/i)).toBeVisible({ timeout: 5_000 });
    await page.getByRole("button", { name: /sí, continuar/i }).click();
    await expect(page.getByText(/desea continuar con el asistente/i)).toHaveCount(0);

    await input.fill("necesito hablar con un agente");
    await input.press("Enter");
    await expect(yesBtn).toBeVisible({ timeout: 5_000 });
    await yesBtn.click();
    await expect(page.getByText(/cómo prefiere que lo contactemos/i)).toBeVisible({ timeout: 5_000 });

    const contactInput = page.locator('input[type="email"], input[type="tel"]').last();
    await contactInput.fill("no-es-un-correo");
    await page.getByRole("button", { name: /^enviar$/i }).click();
    await expect(page.getByText(/correo electrónico válido/i)).toBeVisible({ timeout: 5_000 });

    await page.getByRole("radio", { name: /whatsapp/i }).check();
    await expect(page.getByText(/su número de whatsapp/i)).toBeVisible();
    const waInput = page.locator('input[type="tel"]');
    await waInput.fill("123");
    await page.getByRole("button", { name: /^enviar$/i }).click();
    await expect(page.getByText(/número de whatsapp válido/i)).toBeVisible({ timeout: 5_000 });

    await waInput.fill("+503 7777 7777");
    await page.getByRole("button", { name: /^enviar$/i }).click();
    await expect(page.getByText(/la universidad se pondrá en contacto/i)).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "05-escalamiento-enviado.png") });
  });

  test("menu kebab: nueva conversacion, panel de accesibilidad (tamaño de texto, alto contraste), finalizar chat", async ({ page }) => {
    await page.goto("/dashboard/configuracion/asistente?tab=previsualizar");
    await expect(page.getByPlaceholder(/escribe un mensaje/i)).toBeVisible({ timeout: 10_000 });

    const kebabBtn = page.getByRole("button", { name: /más opciones/i });
    if (!(await kebabBtn.isVisible().catch(() => false))) {
      test.skip(true, "Menú kebab oculto - ningún ítem habilitado en la config actual del widget");
    }

    await kebabBtn.click();
    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible({ timeout: 5_000 });
    const a11yItem = menu.getByRole("menuitem", { name: /accesibilidad/i });
    if (await a11yItem.isVisible().catch(() => false)) {
      await a11yItem.click();

      const radioGroup = page.getByRole("radiogroup", { name: /tamaño de texto/i });
      await expect(radioGroup).toBeVisible({ timeout: 5_000 });
      const radios = radioGroup.getByRole("radio");
      const count = await radios.count();
      expect(count).toBe(3);
      for (let i = 0; i < count; i++) {
        await radios.nth(i).click();
        await expect(radios.nth(i)).toHaveAttribute("aria-checked", "true");
      }

      const contrastSwitch = page.getByText(/alto contraste/i).locator("../..").locator('[role="switch"]');
      const wasOn = (await contrastSwitch.getAttribute("aria-checked")) === "true";
      await contrastSwitch.click();
      await expect(contrastSwitch).toHaveAttribute("aria-checked", String(!wasOn));
      await page.screenshot({ path: path.join(SHOT_DIR, "03-accesibilidad.png") });
      await contrastSwitch.click();

      await page.getByRole("button", { name: /cerrar accesibilidad/i }).click();
      await expect(radioGroup).toHaveCount(0);
    }

    await input_or_send_message(page);
    await kebabBtn.click();
    const newChatItem = page.getByRole("menuitem", { name: /nueva conversación/i });
    if (await newChatItem.isVisible().catch(() => false)) {
      await newChatItem.click();
      await expect(page.getByRole("menu")).toHaveCount(0);
    } else {
      await page.keyboard.press("Escape");
    }

    await kebabBtn.click();
    const endChatItem = page.getByRole("menuitem", { name: /finalizar chat/i });
    if (await endChatItem.isVisible().catch(() => false)) {
      await endChatItem.click();
      await page.screenshot({ path: path.join(SHOT_DIR, "04-chat-finalizado.png") });
    } else {
      await page.keyboard.press("Escape");
    }
  });
});

async function input_or_send_message(page: import("@playwright/test").Page) {
  const input = page.getByPlaceholder(/escribe un mensaje/i);
  if (await input.isVisible().catch(() => false)) {
    await input.fill("mensaje corto de prueba");
    await input.press("Enter");
    await expect(page.locator(".animate-spin")).toHaveCount(0, { timeout: 30_000 }).catch(() => {});
  }
}

import { test, expect } from "@playwright/test";

/**
 * End-to-end coverage for the real widget's escalation contact form
 * (correo/WhatsApp), running against the actual widget.js bundle served by
 * the backend and the real /widget/public/escalation/contact endpoint - not
 * the simulated playground in configuracion-asistente-preview.spec.ts.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const BACKEND_URL = "http://localhost:8000";

async function getWidgetKey(request: import("@playwright/test").APIRequestContext, authHeader: string): Promise<string> {
  const cfgRes = await request.get(`${BACKEND_URL}/api/v1/widget/config`, { headers: { Authorization: authHeader } });
  expect(cfgRes.ok(), `widget config request failed: ${cfgRes.status()}`).toBeTruthy();
  return (await cfgRes.json()).api_key as string;
}

async function loadWidgetPage(page: import("@playwright/test").Page, widgetKey: string) {
  await page.setContent(`<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body>
<chatbot-widget api-url="${BACKEND_URL}" api-key="${widgetKey}"></chatbot-widget>
<script src="${BACKEND_URL}/widget/widget.js"></script>
</body></html>`, { waitUntil: "domcontentloaded" });

  const openBtn = page.getByRole("button", { name: /abrir chat/i });
  await expect(openBtn).toBeVisible({ timeout: 15_000 });
  await openBtn.click();

  const messageInput = page.locator('textarea[placeholder*="pregunta" i]').first();
  await expect(messageInput).toBeVisible({ timeout: 5_000 });
  return messageInput;
}

async function sendMessageAndWaitReply(messageInput: import("@playwright/test").Locator, page: import("@playwright/test").Page, question: string) {
  await messageInput.fill(question);
  await messageInput.press("Enter");
  await expect(page.locator('[aria-label="Escribiendo"]')).toHaveCount(0, { timeout: 30_000 });
}

async function fillAndSubmitContact(page: import("@playwright/test").Page, type: "email" | "whatsapp", value: string) {
  const footerBtn = page.getByRole("button", { name: /necesitas hablar con alguien/i });
  await expect(footerBtn).toBeVisible({ timeout: 10_000 });
  await footerBtn.click();

  if (type === "whatsapp") {
    await page.getByRole("radio", { name: /whatsapp/i }).check();
  }
  const contactInput = page.locator('input[type="email"], input[type="tel"]').first();
  await expect(contactInput).toBeVisible({ timeout: 5_000 });
  await contactInput.fill(value);
  await page.locator(".escal-submit-btn").click();
  await expect(page.getByText(/la universidad se pondrá en contacto/i)).toBeVisible({ timeout: 10_000 });
}

test.describe("Widget real - escalamiento con contacto", () => {
  test("correo: envio real llega al historial de notificaciones", async ({ page, request }) => {
    test.setTimeout(60_000);
    const authHeader = `Bearer ${(await page.context().cookies()).find((c) => c.name === "chatbot_access")?.value}`;
    const widgetKey = await getWidgetKey(request, authHeader);

    const messageInput = await loadWidgetPage(page, widgetKey);
    const uniqueQuestion = `E2E widget escalation email ${Date.now()}`;
    await sendMessageAndWaitReply(messageInput, page, uniqueQuestion);

    const emailValue = `e2e+${Date.now()}@example.com`;
    await fillAndSubmitContact(page, "email", emailValue);

    const historyRes = await request.get(`${BACKEND_URL}/api/v1/notifications?page=1&page_size=20`, {
      headers: { Authorization: authHeader },
    });
    expect(historyRes.ok()).toBeTruthy();
    const items = (await historyRes.json()).items as Array<{ event: string; created_at: string }>;
    const escalationTriggers = items.filter((item) => item.event === "escalation");
    expect(escalationTriggers.length).toBeGreaterThan(0);
  });

  test("whatsapp: envio real llega al historial de notificaciones", async ({ page, request }) => {
    test.setTimeout(60_000);
    const authHeader = `Bearer ${(await page.context().cookies()).find((c) => c.name === "chatbot_access")?.value}`;
    const widgetKey = await getWidgetKey(request, authHeader);

    const messageInput = await loadWidgetPage(page, widgetKey);
    const uniqueQuestion = `E2E widget escalation whatsapp ${Date.now()}`;
    await sendMessageAndWaitReply(messageInput, page, uniqueQuestion);

    const whatsappValue = "+503 7777 7777";
    await fillAndSubmitContact(page, "whatsapp", whatsappValue);

    const historyRes = await request.get(`${BACKEND_URL}/api/v1/notifications?page=1&page_size=20`, {
      headers: { Authorization: authHeader },
    });
    expect(historyRes.ok()).toBeTruthy();
    const items = (await historyRes.json()).items as Array<{ event: string; created_at: string }>;
    const escalationTriggers = items.filter((item) => item.event === "escalation");
    expect(escalationTriggers.length).toBeGreaterThan(0);
  });
});

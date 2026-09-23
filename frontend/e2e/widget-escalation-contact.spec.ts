import { test, expect } from "@playwright/test";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");
test.skip(!!process.env.CI, "requiere un proveedor LLM real; CI no tiene ninguno configurado");

const BACKEND_URL = "http://127.0.0.1:8000";

async function getWidgetKey(request: import("@playwright/test").APIRequestContext, authHeader: string): Promise<string> {
  const cfgRes = await request.get(`${BACKEND_URL}/api/v1/widget/config`, { headers: { Authorization: authHeader } });
  expect(cfgRes.ok(), `widget config request failed: ${cfgRes.status()}`).toBeTruthy();
  const cfg = await cfgRes.json();
  return cfg.api_key as string;
}

async function loadWidgetPage(page: import("@playwright/test").Page, widgetKey: string) {
  await page.route(`${BACKEND_URL}/__e2e_widget_host__`, (route) => {
    route.fulfill({
      contentType: "text/html",
      body: `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<chatbot-widget api-url="${BACKEND_URL}" api-key="${widgetKey}"></chatbot-widget>
<script src="${BACKEND_URL}/widget/widget.js"></script>
</body></html>`,
    });
  });
  await page.goto(`${BACKEND_URL}/__e2e_widget_host__`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelector("chatbot-widget")?.shadowRoot != null, { timeout: 15_000 });

  const openBtn = page.getByRole("button", { name: /abrir chat/i });
  await expect(openBtn).toBeVisible({ timeout: 15_000 });
  await openBtn.click();

  const messageInput = page.locator('textarea[placeholder*="mensaje" i]').first();
  await expect(messageInput).toBeVisible({ timeout: 5_000 });
  return messageInput;
}

async function sendMessageAndWaitReply(messageInput: import("@playwright/test").Locator, page: import("@playwright/test").Page, question: string) {
  await messageInput.fill(question);
  await messageInput.press("Enter");
  await expect(page.locator('[aria-label="Escribiendo"]')).toHaveCount(0, { timeout: 45_000 });
}

async function fillAndSubmitContact(page: import("@playwright/test").Page, type: "email" | "whatsapp", value: string) {
  const promptYesBtn = page.getByRole("button", { name: /^sí$/i });
  await expect(promptYesBtn).toBeVisible({ timeout: 10_000 });
  await promptYesBtn.click();

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
    const uniqueQuestion = `Quiero hablar con un agente E2E ${Date.now()}`;
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
    const uniqueQuestion = `Quiero hablar con un agente E2E ${Date.now()}`;
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

test.describe("Widget real - CSAT y feedback de mensajes", () => {
  test("csat: finalizar chat, calificar y enviar llega al backend", async ({ page, request }) => {
    test.setTimeout(60_000);
    const authHeader = `Bearer ${(await page.context().cookies()).find((c) => c.name === "chatbot_access")?.value}`;
    const widgetKey = await getWidgetKey(request, authHeader);

    const messageInput = await loadWidgetPage(page, widgetKey);
    await sendMessageAndWaitReply(messageInput, page, `Pregunta de prueba E2E ${Date.now()}`);

    await page.getByRole("button", { name: /más opciones/i }).click();
    await page.getByRole("menuitem", { name: /finalizar chat/i }).click();

    const fiveStars = page.getByRole("button", { name: /^5 estrellas$/i });
    await expect(fiveStars).toBeVisible({ timeout: 10_000 });
    await fiveStars.click();

    const [csatResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/v1/widget/public/csat") && r.request().method() === "POST"),
      page.getByRole("button", { name: /^finalizar$/i }).click(),
    ]);
    expect(csatResp.status(), `unexpected /widget/public/csat status: ${csatResp.status()}`).toBe(204);
    await expect(page.getByText(/¡muchas gracias!/i)).toBeVisible({ timeout: 10_000 });
  });

  test("feedback: pulgar arriba en una respuesta llega al backend", async ({ page, request }) => {
    test.setTimeout(60_000);
    const authHeader = `Bearer ${(await page.context().cookies()).find((c) => c.name === "chatbot_access")?.value}`;
    const widgetKey = await getWidgetKey(request, authHeader);

    const messageInput = await loadWidgetPage(page, widgetKey);
    await sendMessageAndWaitReply(messageInput, page, `Pregunta de prueba E2E feedback ${Date.now()}`);

    const thumbsUp = page.getByRole("button", { name: /^útil$/i }).last();
    const [feedbackResp] = await Promise.all([
      page.waitForResponse((r) => /\/widget\/public\/messages\/[^/]+\/feedback$/.test(r.url()) && r.request().method() === "PATCH"),
      thumbsUp.click(),
    ]);
    expect(feedbackResp.status(), `unexpected feedback status: ${feedbackResp.status()}`).toBe(204);
  });
});

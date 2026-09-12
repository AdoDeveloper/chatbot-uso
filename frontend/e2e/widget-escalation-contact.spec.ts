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

// 127.0.0.1, no "localhost": en el runner de CI "localhost" resuelve a
// IPv6 (::1) antes que a IPv4, donde nada escucha - el <script src> del
// widget fallaba en silencio y el botón "Abrir chat" nunca se renderizaba.
const BACKEND_URL = "http://127.0.0.1:8000";

async function getWidgetKey(request: import("@playwright/test").APIRequestContext, authHeader: string): Promise<string> {
  const cfgRes = await request.get(`${BACKEND_URL}/api/v1/widget/config`, { headers: { Authorization: authHeader } });
  expect(cfgRes.ok(), `widget config request failed: ${cfgRes.status()}`).toBeTruthy();
  const cfg = await cfgRes.json();
  console.log("[diag] widget config enable_escalation:", cfg.enable_escalation);
  return cfg.api_key as string;
}

async function loadWidgetPage(page: import("@playwright/test").Page, widgetKey: string) {
  // DIAGNOSTICO: escalation_prompt confirmado true en la respuesta, pero la
  // tarjeta de escalamiento no aparece - capturar excepciones silenciosas.
  page.on("pageerror", (err) => console.log("[diag:pageerror]", err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error" || msg.text().includes("[widget-diag]")) {
      console.log("[diag:console]", msg.text());
    }
  });

  // page.route + page.goto a una página real (no page.setContent ni
  // reescribir el DOM de una página ajena como /api/docs): setContent sirve
  // el documento sobre un origen opaco donde localStorage lanza
  // SecurityError, y sobreescribir innerHTML encima de Swagger dejaba su
  // propio React montado por debajo, compartiendo scope global con el
  // widget. Se sirve un HTML minimo propio en el mismo origen del backend
  // interceptando una ruta que de otro modo devolvería 404.
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
  // DIAGNOSTICO: el widget reintenta hasta 3 veces (chat.ts MAX_ATTEMPTS) -
  // capturar solo la primera respuesta puede no ser la que termina
  // renderizada. Se loguean TODAS las respuestas de este envío.
  const responses: import("@playwright/test").Response[] = [];
  const onResp = (r: import("@playwright/test").Response) => {
    if (r.url().includes("/widget/public/chat")) responses.push(r);
  };
  page.on("response", onResp);
  await messageInput.fill(question);
  await messageInput.press("Enter");
  await expect(page.locator('[aria-label="Escribiendo"]')).toHaveCount(0, { timeout: 30_000 });
  page.off("response", onResp);
  for (const [i, r] of responses.entries()) {
    const body = await r.json().catch(() => null);
    console.log(`[diag] /widget/public/chat #${i} status=${r.status()} conversation_id=${body?.conversation_id} escalation_prompt=${body?.escalation_prompt} content=${(body?.content ?? "").slice(0, 150)}`);
  }
  await page.waitForTimeout(500);
  const escalCardHtml = await page.locator(".escal-card").first().evaluate((el) => el.outerHTML).catch((e) => `NOT_FOUND: ${e}`);
  console.log("[diag] .escal-card outerHTML:", escalCardHtml.slice(0, 500));
  const msgCount = await page.locator(".msg-row").count();
  console.log("[diag] .msg-row count:", msgCount);
  const bodyHtml = await page.evaluate(() => {
    const widget = document.querySelector("chatbot-widget");
    const root = widget?.shadowRoot ?? document;
    const msgs = root.querySelector(".messages, [class*='messages']");
    return msgs ? msgs.outerHTML.slice(0, 1500) : "NO_MESSAGES_CONTAINER";
  }).catch((e) => `EVAL_ERROR: ${e}`);
  console.log("[diag] messages container html:", bodyHtml);
  // DIAGNOSTICO: leer el estado persistido directamente (saveHistory corre
  // en cada cambio de escalState/messages) - confirma si React realmente
  // actualizo el estado, sin depender del DOM renderizado.
  const persisted = await page.evaluate(() => {
    const key = Object.keys(localStorage).find((k) => k.startsWith("usobot:history:"));
    return key ? localStorage.getItem(key) : "NO_KEY_FOUND";
  }).catch((e) => `EVAL_ERROR: ${e}`);
  console.log("[diag] localStorage history:", (persisted ?? "").slice(0, 500));
}

async function fillAndSubmitContact(page: import("@playwright/test").Page, type: "email" | "whatsapp", value: string) {
  // La tarjeta de escalamiento aparece como burbuja del bot en el flujo
  // (disparada por escalationPrompt en la respuesta), no detrás de un botón
  // de pie de página siempre visible.
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
    // "agente" dispara la regla sembrada por defecto "Usuario solicita
    // agente" (user_request) en un solo turno - las demás reglas por
    // defecto (no_answer, confidence_below) exigen 2+ turnos consecutivos
    // o un umbral de latencia de 120s, poco fiables para un E2E rápido.
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

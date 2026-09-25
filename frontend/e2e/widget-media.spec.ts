import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");
test.skip(!!process.env.CI, "requiere un proveedor LLM real; CI no tiene ninguno configurado");

const BACKEND_URL = "http://127.0.0.1:8000";
const MEDIA_HOST = "https://e2e-media.test";
const SHOT_DIR = path.join("e2e", ".report-screenshots", "widget-media");
fs.mkdirSync(SHOT_DIR, { recursive: true });

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAEAAAAAgCAIAAAAt/+nTAAAATklEQVR4nO3PUQkAIBTAwFfESuY3jiH8OITBAtxm7fN1wwUNaEEDWtCAFjSgBQ1oQQNa0IAWNKAFDWhBA1rQgBY0oAUNaEEDWtCAFjx2AeJ+GJdStwISAAAAAElFTkSuQmCC",
  "base64",
);
const PDF = Buffer.from(
  "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" +
  "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n",
);

async function authHeader(page: Page): Promise<string> {
  return `Bearer ${(await page.context().cookies()).find((c) => c.name === "chatbot_access")?.value}`;
}

async function createFaq(request: APIRequestContext, auth: string, question: string, answer: string): Promise<string> {
  const res = await request.post(`${BACKEND_URL}/api/v1/faq`, { headers: { Authorization: auth }, data: { question, answer } });
  expect(res.ok(), `crear FAQ: ${res.status()}`).toBeTruthy();
  return (await res.json()).id as string;
}

async function openWidget(page: Page, widgetKey: string) {
  await page.context().route(`${MEDIA_HOST}/**`, (route) => {
    const isPdf = route.request().url().endsWith(".pdf");
    route.fulfill({ contentType: isPdf ? "application/pdf" : "image/png", body: isPdf ? PDF : PNG });
  });
  await page.route(`${BACKEND_URL}/__e2e_media_host__`, (route) => route.fulfill({
    contentType: "text/html",
    body: `<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<chatbot-widget api-url="${BACKEND_URL}" api-key="${widgetKey}"></chatbot-widget>
<script src="${BACKEND_URL}/widget/widget.js"></script></body></html>`,
  }));
  await page.goto(`${BACKEND_URL}/__e2e_media_host__`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: /abrir chat/i }).click();
  const input = page.locator('textarea[placeholder*="mensaje" i]').first();
  await expect(input).toBeVisible({ timeout: 10_000 });
  return input;
}

async function ask(page: Page, input: import("@playwright/test").Locator, question: string) {
  const finished = page.locator(".msg-assistant .msg-actions");
  const before = await finished.count();
  await input.fill(question);
  await input.press("Enter");
  await expect(finished).toHaveCount(before + 1, { timeout: 60_000 });
  return page.locator(".msg-row-assistant").last();
}

test.describe("Widget real - imágenes y enlaces a PDF en las respuestas", () => {
  test("muestra la imagen cargada y el PDF como enlace que abre en otra pestaña", async ({ page, request }) => {
    test.setTimeout(180_000);
    const auth = await authHeader(page);
    const key = (await (await request.get(`${BACKEND_URL}/api/v1/widget/config`, { headers: { Authorization: auth } })).json()).api_key;
    const tag = `M${Date.now().toString(36).toUpperCase()}`;
    const faqIds = [
      await createFaq(request, auth, `¿Dónde está el croquis del campus ${tag}?`,
        `El croquis del campus ${tag} está en esta imagen: ${MEDIA_HOST}/croquis-${tag}.png`),
      await createFaq(request, auth, `¿Dónde descargo el calendario académico ${tag}?`,
        `El calendario académico ${tag} está en el documento ${MEDIA_HOST}/calendario-${tag}.pdf`),
    ];
    try {
      const input = await openWidget(page, key);

      const withImage = await ask(page, input, `¿Dónde está el croquis del campus ${tag}?`);
      const img = withImage.locator(".md img");
      await expect(img).toHaveCount(1);
      await expect(img).toHaveAttribute("src", `${MEDIA_HOST}/croquis-${tag}.png`);
      await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0)).toBe(true);
      await page.screenshot({ path: path.join(SHOT_DIR, "01-imagen.png") });

      const withPdf = await ask(page, input, `¿Dónde descargo el calendario académico ${tag}?`);
      const link = withPdf.locator(".md a.pdf-link");
      await expect(link).toHaveCount(1);
      await expect(link).toHaveAttribute("href", `${MEDIA_HOST}/calendario-${tag}.pdf`);
      await expect(link).toHaveAttribute("target", "_blank");
      await expect(link).toHaveAttribute("rel", /noopener/);
      await page.screenshot({ path: path.join(SHOT_DIR, "02-pdf.png") });

      const pdfUrl = `${MEDIA_HOST}/calendario-${tag}.pdf`;
      const [popup, pdfRequest] = await Promise.all([
        page.context().waitForEvent("page", { timeout: 10_000 }),
        page.context().waitForEvent("request", { predicate: (r) => r.url() === pdfUrl, timeout: 10_000 }),
        link.click({ timeout: 10_000 }),
      ]);
      expect(popup).not.toBe(page);
      expect(pdfRequest.frame().page()).toBe(popup);
      await popup.close();
    } finally {
      for (const id of faqIds) {
        await request.delete(`${BACKEND_URL}/api/v1/faq/${id}`, { headers: { Authorization: auth } });
      }
      await request.delete(`${BACKEND_URL}/api/v1/cache/clear`, { headers: { Authorization: auth } });
    }
  });
});

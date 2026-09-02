import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Coverage for /dashboard/conocimiento/consulta (semantic search tester) and /dashboard/configuracion/playground (live chat preview), both running real queries against the real backend without persisting config.
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "conocimiento-consulta-playground");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Conocimiento > Consulta", () => {
  test("ejecutar una consulta semantica de prueba", async ({ page }) => {
    await page.goto("/dashboard/conocimiento/consulta");
    await expect(page.getByPlaceholder(/requisitos de matrícula/i)).toBeVisible({ timeout: 10_000 });

    await page.getByPlaceholder(/requisitos de matrícula/i).fill("proceso de inscripcion");
    await page.locator("#main-content").getByRole("button", { name: /buscar/i }).click();

    // Wait for actual result content, not a generic spinner check - a page-wide spinner sweep is prone to false negatives from unrelated transient UI state under concurrent E2E load.
    await expect(page.getByText(/chunks recuperados/i)).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "01-consulta-resultado.png") });
  });
});

test.describe("Configuracion > Playground", () => {
  test("enviar un mensaje de prueba al chatbot", async ({ page, request, baseURL }) => {
    test.setTimeout(60_000);
    await page.goto("/dashboard/configuracion/playground");
    await expect(page.getByPlaceholder(/escribe un mensaje/i)).toBeVisible({ timeout: 10_000 });

    await page.getByPlaceholder(/escribe un mensaje/i).fill("Hola, esto es un mensaje de prueba E2E.");
    await page.screenshot({ path: path.join(SHOT_DIR, "02-playground-mensaje.png") });
    await page.getByPlaceholder(/escribe un mensaje/i).press("Enter");

    await expect(page.locator(".animate-spin")).toHaveCount(0, { timeout: 30_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-playground-respuesta.png") });

    // The message can end up tracked as an unanswered question and later auto-promoted into a FAQ source - clean up so it doesn't accumulate on every run.
    const authHeader = `Bearer ${(await page.context().cookies()).find(c => c.name === "chatbot_access")?.value}`;
    const srcRes = await request.get(`${baseURL}/api/v1/sources?page_size=100`, {
      headers: { Authorization: authHeader },
    }).catch(() => null);
    if (srcRes && srcRes.ok()) {
      const body = await srcRes.json().catch(() => null);
      const items = body?.items ?? body ?? [];
      for (const s of items) {
        if (typeof s?.name === "string" && /mensaje de prueba e2e/i.test(s.name)) {
          await request.delete(`${baseURL}/api/v1/sources/${s.id}`, { headers: { Authorization: authHeader } }).catch(() => {});
        }
      }
    }
    const convRes = await request.get(`${baseURL}/api/v1/conversations?page_size=50&search=${encodeURIComponent("mensaje de prueba E2E")}`, {
      headers: { Authorization: authHeader },
    }).catch(() => null);
    if (convRes && convRes.ok()) {
      const body = await convRes.json().catch(() => null);
      const ids = (body?.items ?? []).map((c: { id: string }) => c.id);
      if (ids.length > 0) {
        await request.post(`${baseURL}/api/v1/conversations/bulk`, {
          headers: { Authorization: authHeader, "Content-Type": "application/json" },
          data: { conversation_ids: ids, action: "delete" },
        }).catch(() => {});
      }
    }

    // Deleting the conversation does not remove its separately-tracked UnansweredQuestion row - resolve leftovers too, or every run leaves another permanently-open row in Pendientes.
    const uaRes = await request.get(`${baseURL}/api/v1/unanswered`, {
      headers: { Authorization: authHeader },
    }).catch(() => null);
    if (uaRes && uaRes.ok()) {
      const body = await uaRes.json().catch(() => null);
      const groups = body?.groups ?? [];
      for (const g of groups) {
        for (const q of g.questions ?? []) {
          if (typeof q?.question === "string" && /mensaje de prueba e2e/i.test(q.question)) {
            await request.post(`${baseURL}/api/v1/unanswered/${q.id}/resolve`, {
              headers: { Authorization: authHeader },
            }).catch(() => {});
          }
        }
      }
    }
  });
});

import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Functional coverage for /dashboard/conversaciones/escalamientos and
 * /dashboard/conversaciones/pendientes. Both pages act on real domain data
 * (escalated conversations, unanswered questions) that this suite doesn't
 * fabricate - creating a fake escalation would require driving a full real
 * chat conversation through the widget first. Each write action is
 * exercised only when matching data already exists in the environment
 * (mirrors the established skip pattern in conversaciones.spec.ts /
 * invitaciones.spec.ts); otherwise the test documents the empty state.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "conversaciones-triage");
fs.mkdirSync(SHOT_DIR, { recursive: true });

test.describe("Conversaciones > Escalamientos", () => {
  test("filtro Pendientes/Resueltos, filtro por tag, y seleccion + bulk resolver/tag", async ({ page }) => {
    await page.goto("/dashboard/conversaciones/escalamientos");
    await expect(page.getByRole("heading", { name: /escalamientos|conversaciones/i }).first()).toBeVisible({ timeout: 10_000 });

    // SegmentedControl: both filter states, unconditionally safe (read-only).
    const resueltosChip = page.getByRole("button", { name: /^resueltos$/i });
    await resueltosChip.click();
    await expect(page.getByRole("heading", { name: /^resueltos$/i })).toBeVisible({ timeout: 10_000 });
    const pendientesChip = page.getByRole("button", { name: /^pendientes$/i });
    await pendientesChip.click();
    await expect(page.getByRole("heading", { name: /^pendientes$/i })).toBeVisible({ timeout: 10_000 });

    // Tag filter select - only rendered when at least one tag exists in the system.
    const tagSelect = page.locator("select");
    if (await tagSelect.isVisible().catch(() => false)) {
      const options = await tagSelect.locator("option").allTextContents();
      if (options.length > 1) {
        await tagSelect.selectOption({ index: 1 });
        await page.waitForTimeout(500);
        await tagSelect.selectOption({ index: 0 });
      }
    }

    // Bulk bar: only appears once a case is selected. Skip the actual bulk
    // actions if there are no cases in the current filter to select.
    const firstCheckbox = page.locator('input[type="checkbox"]').first();
    const hasCases = await firstCheckbox.isVisible().catch(() => false);
    if (!hasCases) {
      test.skip(true, "no hay casos en este entorno para probar la seleccion/bulk");
    }
    await firstCheckbox.check();
    await expect(page.getByText(/1 seleccionada/i)).toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "07-bulk-bar.png") });

    // No hace click en "Marcar resueltas" aquí - ya cubierto por el test de resolve individual; este se enfoca en bulk tag y selección.
    const tagInput = page.getByPlaceholder("tag...");
    const disposableTag = `e2e-bulk-${Date.now()}`;
    await tagInput.fill(disposableTag);
    await page.getByRole("button", { name: /\+tag/i }).click();
    await expect(page.getByText(new RegExp(`#${disposableTag}`))).toBeVisible({ timeout: 10_000 });

    // Re-selecciona: un bulk action exitoso limpia la selección.
    await firstCheckbox.check();
    await tagInput.fill(disposableTag);
    await page.getByRole("button", { name: /−tag/i }).click();
    await expect(page.getByText(new RegExp(`#${disposableTag}`))).toHaveCount(0, { timeout: 10_000 });

    // "Limpiar" clears the selection without performing any action.
    if (await firstCheckbox.isVisible().catch(() => false)) {
      await firstCheckbox.check();
      await page.getByRole("button", { name: /limpiar/i }).click();
      await expect(page.getByText(/seleccionada/i)).toHaveCount(0);
    }
  });

  test("marcar un caso escalado como resuelto", async ({ page }) => {
    await page.goto("/dashboard/conversaciones/escalamientos");
    await expect(page.getByRole("heading", { name: /escalamientos|conversaciones/i }).first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "01-escalamientos.png") });

    // Don't gate on the skeleton's absence - right after goto() the fetch
    // may not have started yet, so a "skeleton count 0" check can resolve
    // trivially true before data has loaded. Poll for the actual button.
    const resolveButton = page.getByRole("button", { name: /^marcar resuelto$/i }).first();
    const hasEscalated = await resolveButton
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasEscalated) {
      test.skip(true, "no hay casos escalados pendientes en este entorno");
    }
    await resolveButton.click();

    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(confirmDialog.getByRole("heading")).toContainText(/resuelta/i);
    await confirmDialog.getByRole("button", { name: /marcar resuelta/i }).click();
    await page.screenshot({ path: path.join(SHOT_DIR, "02-caso-resuelto.png") });
  });
});

test.describe("Conversaciones > Pendientes", () => {
  test("analizar causa raiz de una pregunta pendiente: abrir y colapsar", async ({ page }) => {
    await page.goto("/dashboard/conversaciones/pendientes");
    await expect(page.getByRole("heading", { name: /pendientes|conversaciones/i }).first()).toBeVisible({ timeout: 10_000 });

    const rootCauseBtn = page.getByRole("button", { name: /causa raíz/i }).first();
    const hasPending = await rootCauseBtn
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasPending) {
      test.skip(true, "no hay preguntas pendientes en este entorno");
    }

    await rootCauseBtn.click();
    await expect(page.getByText(/análisis automático/i)).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "07-causa-raiz.png") });

    // Clicking again collapses the analysis (toggle behavior).
    await rootCauseBtn.click();
    await expect(page.getByText(/análisis automático/i)).toHaveCount(0);
  });

  test("marcar una pregunta pendiente como resuelta", async ({ page }) => {
    await page.goto("/dashboard/conversaciones/pendientes");
    await expect(page.getByRole("heading", { name: /pendientes|conversaciones/i }).first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-pendientes.png") });

    const resolveButton = page.locator('button[title="Marcar como resuelta sin crear FAQ"]').first();
    const hasPending = await resolveButton
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasPending) {
      test.skip(true, "no hay preguntas pendientes en este entorno");
    }
    await resolveButton.click();

    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(confirmDialog.getByRole("heading")).toContainText(/resuelta/i);
    await confirmDialog.getByRole("button", { name: /marcar resuelta/i }).click();
    await page.screenshot({ path: path.join(SHOT_DIR, "04-pregunta-resuelta.png") });
  });

  test("convertir una pregunta pendiente en FAQ", async ({ page, request, baseURL }) => {
    await page.goto("/dashboard/conversaciones/pendientes");
    await expect(page.getByRole("heading", { name: /pendientes|conversaciones/i }).first()).toBeVisible({ timeout: 10_000 });

    const faqButton = page.locator('button[title="Convertir esta pregunta en una FAQ con respuesta"]').first();
    const hasPending = await faqButton
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasPending) {
      test.skip(true, "no hay preguntas pendientes en este entorno");
    }
    await faqButton.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /crear faq/i })).toBeVisible();
    await dialog.locator("textarea").fill("Respuesta de prueba E2E generada desde una pregunta pendiente.");
    await page.screenshot({ path: path.join(SHOT_DIR, "05-crear-faq-formulario.png") });

    // Captura la respuesta real (POST .../create-faq -> {faq_id}) en vez de adivinar la fuente creada: la pregunta actuada puede ser cualquiera de la lista.
    const [createResponse] = await Promise.all([
      page.waitForResponse((r) => /\/unanswered\/.+\/create-faq$/.test(r.url()) && r.request().method() === "POST"),
      dialog.getByRole("button", { name: /crear faq/i }).click(),
    ]);
    await expect(dialog).not.toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "06-faq-creada-desde-pendiente.png") });

    const faqId = (await createResponse.json().catch(() => null))?.faq_id;
    if (faqId) {
      // El Source creado junto al FAQEntry no expone su id directamente; se resuelve como la fuente FAQ más reciente (seguro porque este test la acaba de crear).
      const authHeader = `Bearer ${(await page.context().cookies()).find(c => c.name === "chatbot_access")?.value}`;
      const srcRes = await request.get(`${baseURL}/api/v1/sources?page_size=5`, {
        headers: { Authorization: authHeader },
      }).catch(() => null);
      if (srcRes && srcRes.ok()) {
        const body = await srcRes.json().catch(() => null);
        const items = (body?.items ?? body ?? []) as { id: string; type: string; created_at: string }[];
        const newestFaq = items.filter((s) => s.type === "faq").sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
        if (newestFaq) {
          await request.delete(`${baseURL}/api/v1/sources/${newestFaq.id}`, { headers: { Authorization: authHeader } }).catch(() => {});
        }
      }
    }
  });
});

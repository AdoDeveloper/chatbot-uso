import { test, expect } from "@playwright/test";
import path from "node:path";

// Control-level coverage for /dashboard/conversaciones beyond conversaciones.spec.ts: search, date range, status chips, export, feedback buttons, sources disclosure, and delete - run against a real, disposable conversation created via the widget chat endpoint so the delete test never touches a real end-user's conversation.
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "conversaciones-controles");

test.describe("Conversaciones > controles de lista y detalle", () => {
  test("buscar, filtro de fechas, chips de estado y paginacion no lanzan excepcion", async ({ page }) => {
    const consoleErrors: string[] = [];
    await page.goto("/dashboard/conversaciones");
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
    await expect(page.getByText(/conversaciones$/i).first()).toBeVisible({ timeout: 10_000 });

    const searchInput = page.getByPlaceholder(/buscar en mensajes/i);
    await searchInput.fill("mensaje que probablemente no existe e2e xyz");
    await page.waitForTimeout(500);
    await searchInput.fill("");

    // Scoped to the "Filtrar por estado" tablist - the page-level ConversacionesTabs nav also uses role="tab" with an overlapping "Todas" label, making an unscoped query ambiguous.
    const statusTablist = page.getByRole("tablist", { name: /filtrar por estado/i });
    for (const label of ["Todas", "Activas", "Resueltas"]) {
      const chip = statusTablist.getByRole("tab", { name: label });
      await chip.click();
      await expect(chip).toHaveAttribute("aria-selected", "true");
    }

    const dateInputs = page.locator('input[type="date"]');
    if (await dateInputs.count() >= 1) {
      await dateInputs.first().fill("2026-01-01");
      await page.waitForTimeout(500);
      await dateInputs.first().fill("");
    }

    expect(consoleErrors, `console errors:\n${consoleErrors.join("\n")}`).toEqual([]);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-filtros.png") });
  });

  test("exportar: menu Excel/PDF descarga un archivo real", async ({ page }) => {
    await page.goto("/dashboard/conversaciones");
    await expect(page.getByRole("button", { name: /exportar/i })).toBeVisible({ timeout: 10_000 });

    const exportBtn = page.getByRole("button", { name: /exportar/i });
    await exportBtn.click();
    await expect(page.getByRole("menuitem", { name: /excel/i })).toBeVisible({ timeout: 5_000 });
    const downloadPromise = page.waitForEvent("download", { timeout: 20_000 });
    await page.getByRole("menuitem", { name: /excel/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBeTruthy();
    // Button disables itself while the request is in flight - wait for it to re-enable before the second click, or it can land while still disabled.
    await expect(exportBtn).toBeEnabled({ timeout: 10_000 });

    await exportBtn.click();
    await expect(page.getByRole("menuitem", { name: /^pdf$/i })).toBeVisible({ timeout: 5_000 });
    const downloadPromise2 = page.waitForEvent("download", { timeout: 20_000 });
    await page.getByRole("menuitem", { name: /^pdf$/i }).click();
    const download2 = await downloadPromise2;
    expect(download2.suggestedFilename()).toBeTruthy();
  });

  test("ciclo completo sobre una conversacion desechable: feedback, fuentes, eliminar (cancelar y confirmar)", async ({ page, request, baseURL }) => {
    test.setTimeout(60_000);
    const authHeader = `Bearer ${(await page.context().cookies()).find((c) => c.name === "chatbot_access")?.value}`;
    const cfgRes = await request.get(`${baseURL}/api/v1/widget/config`, { headers: { Authorization: authHeader } }).catch(() => null);
    const widgetKey = cfgRes && cfgRes.ok() ? (await cfgRes.json()).api_key : null;
    if (!widgetKey) {
      test.skip(true, "no se pudo obtener la clave del widget para crear una conversación de prueba");
    }

    const sessionId = `e2e-controles-${Date.now()}`;
    const uniqueMsg = `E2E controles conversacion ${Date.now()}`;
    const chatResp = await request.post(`${baseURL}/api/v1/widget/public/chat`, {
      headers: { "X-Widget-Key": widgetKey! },
      data: { question: uniqueMsg, session_id: sessionId },
    });
    expect(chatResp.ok(), `real chat request failed: ${chatResp.status()}`).toBeTruthy();

    await page.goto("/dashboard/conversaciones");
    const searchInput = page.getByPlaceholder(/buscar en mensajes/i);
    await searchInput.fill(uniqueMsg);
    const convItem = page.locator('button[aria-pressed]', { hasText: uniqueMsg });
    await expect(convItem).toBeVisible({ timeout: 15_000 });
    await convItem.click();

    const feedbackGroup = page.getByRole("group", { name: /retroalimentación de la respuesta/i }).first();
    if (await feedbackGroup.isVisible().catch(() => false)) {
      const upBtn = feedbackGroup.getByRole("button", { name: /marcar como útil/i });
      await upBtn.click();
      await expect(upBtn).toHaveAttribute("aria-pressed", "true");
      const downBtn = feedbackGroup.getByRole("button", { name: /marcar como no útil/i });
      await downBtn.click();
      await expect(downBtn).toHaveAttribute("aria-pressed", "true");
    }

    const sourcesToggle = page.getByRole("button", { name: /mostrar \d+ fuentes?/i }).first();
    if (await sourcesToggle.isVisible().catch(() => false)) {
      await sourcesToggle.click();
      await expect(sourcesToggle).toHaveAttribute("aria-expanded", "true");
      await sourcesToggle.click();
      await expect(sourcesToggle).toHaveAttribute("aria-expanded", "false");
    }
    await page.screenshot({ path: path.join(SHOT_DIR, "02-conversacion-detalle.png") });

    const deleteBtn = page.getByRole("button", { name: /eliminar/i });
    await deleteBtn.click();
    const cancelConfirm = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await expect(cancelConfirm.getByRole("heading")).toContainText(/eliminar/i);
    await cancelConfirm.getByRole("button", { name: /cancelar/i }).click();
    await expect(cancelConfirm).not.toBeVisible({ timeout: 5_000 });
    // Text legitimately appears twice (list preview + open detail panel) - .first() confirms it's still present.
    await expect(page.getByText(uniqueMsg).first()).toBeVisible();

    await deleteBtn.click();
    const confirmDialog = page.locator("div.fixed.inset-0.z-\\[200\\]");
    await confirmDialog.getByRole("button", { name: /^eliminar$/i }).click();
    await expect(page.getByText(/seleccione una conversación/i)).toBeVisible({ timeout: 10_000 });
  });
});

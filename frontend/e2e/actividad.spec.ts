import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

/**
 * Functional coverage for /dashboard/actividad and its three tabs
 * (auditoria, inyecciones, seguridad). Auditoria's export is exercised
 * unconditionally (safe, non-destructive). Seguridad's "Liberar"/
 * "Desbloquear" actions each trip their own real rate-limit condition
 * (real failed logins / real chat throttling against the public widget
 * endpoint) immediately before checking, since both are transient
 * Redis-backed state with short TTLs that can't reliably be waited on.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const SHOT_DIR = path.join("e2e", ".report-screenshots", "actividad");
fs.mkdirSync(SHOT_DIR, { recursive: true });

async function cleanupRateLimitConversations(
  request: import("@playwright/test").APIRequestContext,
  baseURL: string | undefined,
  authHeader: string,
  _sessionId: string,
) {
  const res = await request.get(`${baseURL}/api/v1/conversations?page_size=50&search=${encodeURIComponent("Rate limit test")}`, {
    headers: { Authorization: authHeader },
  }).catch(() => null);
  if (res && res.ok()) {
    const body = await res.json().catch(() => null);
    const ids = (body?.items ?? []).map((c: { id: string }) => c.id);
    if (ids.length > 0) {
      await request.post(`${baseURL}/api/v1/conversations/bulk`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { conversation_ids: ids, action: "delete" },
      }).catch(() => {});
    }
  }

  const uaRes = await request.get(`${baseURL}/api/v1/unanswered`, {
    headers: { Authorization: authHeader },
  }).catch(() => null);
  if (uaRes && uaRes.ok()) {
    const body = await uaRes.json().catch(() => null);
    const groups = body?.groups ?? [];
    for (const g of groups) {
      for (const q of g.questions ?? []) {
        if (typeof q?.question === "string" && /rate limit test/i.test(q.question)) {
          await request.post(`${baseURL}/api/v1/unanswered/${q.id}/resolve`, {
            headers: { Authorization: authHeader },
          }).catch(() => {});
        }
      }
    }
  }

const srcRes = await request.get(`${baseURL}/api/v1/sources?page_size=100`, {
    headers: { Authorization: authHeader },
  }).catch(() => null);
  if (srcRes && srcRes.ok()) {
    const body = await srcRes.json().catch(() => null);
    const items = body?.items ?? body ?? [];
    for (const s of items) {
      if (typeof s?.name === "string" && /rate limit test/i.test(s.name)) {
        await request.delete(`${baseURL}/api/v1/sources/${s.id}`, {
          headers: { Authorization: authHeader },
        }).catch(() => {});
      }
    }
  }
}

test.describe("Actividad > Auditoria", () => {
  test("exportar el log de auditoria", async ({ page }) => {
    await page.goto("/dashboard/actividad?tab=auditoria");
    await expect(page.getByRole("button", { name: /exportar/i })).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "01-auditoria.png") });

    await page.getByRole("button", { name: /exportar/i }).click();
    const downloadPromise = page.waitForEvent("download", { timeout: 15_000 });
    await page.getByRole("menuitem", { name: /excel/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBeTruthy();
    await page.screenshot({ path: path.join(SHOT_DIR, "02-auditoria-exportada.png") });
  });

  test("filtrar por accion, recurso, actor y fecha; limpiar filtros; ver detalle de una entrada", async ({ page }) => {
    const consoleErrors: string[] = [];
    await page.goto("/dashboard/actividad?tab=auditoria");
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
    await expect(page.getByPlaceholder(/filtrar por acción/i)).toBeVisible({ timeout: 10_000 });

    const searchInput = page.getByPlaceholder(/filtrar por acción/i);
    await searchInput.fill("login");
    await page.waitForTimeout(500);

    const selects = page.locator("select");
    const resourceSelect = selects.first();
    const resourceOptions = await resourceSelect.locator("option").allTextContents();
    expect(resourceOptions.length).toBeGreaterThan(1);
    await resourceSelect.selectOption({ index: 1 });
    await page.waitForTimeout(500);

    const actorSelect = selects.nth(1);
    const actorOptions = await actorSelect.locator("option").allTextContents();
    if (actorOptions.length > 1) {
      await actorSelect.selectOption({ index: 1 });
      await page.waitForTimeout(500);
    }

    const dateInputs = page.locator('input[type="date"]');
    if (await dateInputs.count() >= 1) {
      await dateInputs.first().fill("2026-01-01");
      await page.waitForTimeout(500);
    }

    const clearBtn = page.getByRole("button", { name: /limpiar filtros/i });
    await expect(clearBtn).toBeVisible({ timeout: 5_000 });
    await clearBtn.click();
    await expect(searchInput).toHaveValue("");
    await expect(resourceSelect).toHaveValue("");
    await expect(page.getByRole("button", { name: /limpiar filtros/i })).toHaveCount(0);

    expect(consoleErrors, `console errors while filtering:\n${consoleErrors.join("\n")}`).toEqual([]);

    const firstDetailBtn = page.locator('table tbody tr button', { hasText: /ver/i }).first();
    const hasRows = await firstDetailBtn.waitFor({ state: "visible", timeout: 15_000 }).then(() => true).catch(() => false);
    if (!hasRows) {
      test.skip(true, "no hay entradas de auditoría en este entorno");
    }
    const isDisabled = await firstDetailBtn.isDisabled();
    if (isDisabled) {
      test.skip(true, "la primera entrada no tiene detalle disponible");
    }
    await firstDetailBtn.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: /detalle de la entrada/i })).toBeVisible({ timeout: 5_000 });
    await expect(dialog.getByText(/recurso/i)).toBeVisible();
    await page.screenshot({ path: path.join(SHOT_DIR, "08-auditoria-detalle.png") });
    await page.keyboard.press("Escape");
    await expect(dialog).not.toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Actividad > Inyecciones", () => {
  test("ver el listado de intentos de inyeccion detectados", async ({ page }) => {
    await page.goto("/dashboard/actividad?tab=inyecciones");
    await expect(page).toHaveURL(/tab=inyecciones/, { timeout: 10_000 });
    await page.screenshot({ path: path.join(SHOT_DIR, "03-inyecciones.png") });
  });
});

test.describe("Actividad > Seguridad", () => {

  test("desbloquear un usuario con limite activo (rate-limit de chat)", async ({ page, request, baseURL }) => {
    const authHeader = `Bearer ${(await page.context().cookies()).find(c => c.name === "chatbot_access")?.value}`;
    const cfgRes = await request.get(`${baseURL}/api/v1/widget/config`, {
      headers: { Authorization: authHeader },
    }).catch(() => null);
    const widgetKey = cfgRes && cfgRes.ok() ? (await cfgRes.json()).api_key : null;
    if (!widgetKey) {
      test.skip(true, "no se pudo obtener la clave del widget para generar el rate-limit de prueba");
    }
    const sessionId = `e2e-ratelimit-${Date.now()}`;
    try {
      for (let i = 0; i < 12; i++) {
        await request.post(`${baseURL}/api/v1/widget/public/chat`, {
          headers: { "X-Widget-Key": widgetKey! },
          data: { question: `Rate limit test ${i}`, session_id: sessionId },
        }).catch(() => {});
      }

      await page.goto("/dashboard/actividad?tab=seguridad");
      await expect(page.getByText(/usuarios con límite activo/i).first()).toBeVisible({ timeout: 10_000 });
      await page.screenshot({ path: path.join(SHOT_DIR, "04-seguridad.png") });

      const desbloquearButton = page.getByRole("button", { name: /^desbloquear$/i }).first();
      const hasThrottled = await desbloquearButton
        .waitFor({ state: "visible", timeout: 15_000 })
        .then(() => true)
        .catch(() => false);
      if (!hasThrottled) {
        test.skip(true, "el rate-limit de prueba expiró (TTL corto) antes de que la página terminara de cargar");
      }
      await desbloquearButton.click();
      await page.screenshot({ path: path.join(SHOT_DIR, "06-usuario-desbloqueado.png") });
    } finally {

      await cleanupRateLimitConversations(request, baseURL, authHeader, sessionId);
    }
  });

  test("liberar una IP con logins fallidos y limite activo simultaneo", async ({ page, request, baseURL }) => {
    test.setTimeout(120_000);
    const authHeader = `Bearer ${(await page.context().cookies()).find(c => c.name === "chatbot_access")?.value}`;
    const sessionId = `e2e-ratelimit-liberar-${Date.now()}`;
    try {
      const cfgRes = await request.get(`${baseURL}/api/v1/widget/config`, {
        headers: { Authorization: authHeader },
      }).catch(() => null);
      const widgetKey = cfgRes && cfgRes.ok() ? (await cfgRes.json()).api_key : null;

      const loginAttempts = Array.from({ length: 6 }, () =>
        request.post(`${baseURL}/api/v1/auth/login`, {
          data: { email: "nobody-e2e-liberar-test@invalid.example", password: "wrong-password-e2e" },
        }).catch(() => {}));
      const chatAttempts = widgetKey
        ? Array.from({ length: 12 }, (_, i) =>
            request.post(`${baseURL}/api/v1/widget/public/chat`, {
              headers: { "X-Widget-Key": widgetKey },
              data: { question: `Rate limit test ${i}`, session_id: sessionId },
            }).catch(() => {}))
        : [];
      await Promise.all([...loginAttempts, ...chatAttempts]);

      await page.goto("/dashboard/actividad?tab=seguridad", { timeout: 30_000 });
      await expect(page.getByText(/logins fallidos por ip/i)).toBeVisible({ timeout: 20_000 });
      await page.screenshot({ path: path.join(SHOT_DIR, "07-logins-fallidos.png") });

      const liberarButton = page.getByRole("button", { name: /^liberar$/i }).first();
      let found = false;
      for (let attempt = 1; attempt <= 3 && !found; attempt++) {
        if (attempt > 1) {
          const retrySessionId = `${sessionId}-retry${attempt}`;
          const retryLogins = Array.from({ length: 6 }, () =>
            request.post(`${baseURL}/api/v1/auth/login`, {
              data: { email: "nobody-e2e-liberar-test@invalid.example", password: "wrong-password-e2e" },
            }).catch(() => {}));
          const retryChats = widgetKey
            ? Array.from({ length: 12 }, (_, i) =>
                request.post(`${baseURL}/api/v1/widget/public/chat`, {
                  headers: { "X-Widget-Key": widgetKey },
                  data: { question: `Rate limit test retry ${i}`, session_id: retrySessionId },
                }).catch(() => {}))
            : [];
          await Promise.all([...retryLogins, ...retryChats]);
          await page.reload();
        }
        found = await liberarButton.waitFor({ state: "visible", timeout: 15_000 }).then(() => true).catch(() => false);
      }
      expect(found, "el rate-limit de prueba (60s) expiró en los 3 intentos - revisar contención real del backend compartido, no un dato faltante").toBe(true);
      await liberarButton.click();
      await page.screenshot({ path: path.join(SHOT_DIR, "05-ip-liberada.png") });
    } finally {
      await cleanupRateLimitConversations(request, baseURL, authHeader, sessionId);
    }
  });

  test("filtro de periodo de seguridad, y click en una IP de un mensaje bloqueado filtra la lista", async ({ page }) => {
    const consoleErrors: string[] = [];
    await page.goto("/dashboard/actividad?tab=seguridad");
    page.on("pageerror", (e) => consoleErrors.push(String(e)));
    await expect(page.getByText(/intentos fallidos/i)).toBeVisible({ timeout: 10_000 });

    const dateInputs = page.locator('input[type="date"]');
    if (await dateInputs.count() >= 2) {
      await dateInputs.first().fill("2026-01-01");
      await page.waitForTimeout(800);
    }
    expect(consoleErrors, `console errors while changing security period:\n${consoleErrors.join("\n")}`).toEqual([]);

    const ipBadge = page.locator('button[title="Filtrar por esta IP"]').first();
    const hasSample = await ipBadge.waitFor({ state: "visible", timeout: 10_000 }).then(() => true).catch(() => false);
    if (!hasSample) {
      test.skip(true, "no hay mensajes bloqueados con IP en este entorno/periodo");
    }
    const ipText = (await ipBadge.textContent())?.trim();
    await ipBadge.click();
    await expect(page.getByText("IP:", { exact: false })).toBeVisible({ timeout: 5_000 });
    if (ipText) await expect(page.getByText(ipText, { exact: true }).first()).toBeVisible();
    await page.screenshot({ path: path.join(SHOT_DIR, "09-filtro-ip-bloqueos.png") });

    await page.getByRole("button", { name: /quitar filtro/i }).click();
    await expect(page.getByText(/quitar filtro/i)).toHaveCount(0);
  });
});

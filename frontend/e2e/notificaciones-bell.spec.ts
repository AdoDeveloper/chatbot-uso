import { test, expect } from "@playwright/test";

/**
 * Coverage for POST /notifications/inbox/{id}/read and
 * /notifications/inbox/mark-all-read: login.spec.ts's "bell trigger" test
 * only opens the dropdown and asserts it renders, never clicks anything
 * inside. Both actions only render when there's at least one unread item,
 * which this environment always has real ones from prior E2E runs
 * (escalations, doc_ready events) - no disposable data needed.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

// Orden importa: "marcar todas" vacia por completo las no leidas, asi que
// "marcar una individual" debe correr primero o se queda sin nada que
// marcar (dependen del mismo pool de notificaciones reales acumuladas en
// este entorno, no hay forma barata de generar una notificacion nueva sin
// pasar por una ingestion real o el widget con un LLM real).
test.describe.serial("Campana de notificaciones", () => {
  test("marcar una notificacion individual como leida", async ({ page }) => {
    await page.goto("/dashboard");
    const bell = page.getByRole("button", { name: /notificaciones/i }).first();
    await expect(bell).toBeVisible({ timeout: 10_000 });
    await bell.click();

    // .nth(0) fija el elemento concreto en ese momento (no un locator
    // dinamico que Playwright re-resuelve en cada consulta) - importante
    // porque tras marcar como leida, otra notificacion sin leer pasa a ser
    // "la primera .group con punto azul" y una asercion re-evaluada sobre
    // el mismo locator matchearia esa otra, no la que se marco.
    const unreadDots = page.locator(".group").filter({ has: page.locator("span.bg-primary") });
    const unreadBefore = await unreadDots.count();
    test.skip(unreadBefore === 0, "no hay notificaciones sin leer en este entorno");
    const targetDot = unreadDots.nth(0);

    await targetDot.hover();
    const [readResp] = await Promise.all([
      page.waitForResponse((r) => /\/notifications\/inbox\/[^/]+\/read$/.test(r.url()) && r.request().method() === "POST"),
      targetDot.getByLabel(/marcar como leída/i).click(),
    ]);
    expect(readResp.status(), `unexpected mark-read status: ${readResp.status()}`).toBe(200);
    // React re-renderiza el item marcado sin la clase que lo hace matchear
    // el filtro "bg-primary" - el conteo total de puntos sin leer debe bajar
    // en exactamente 1 (no reconsultar "el primero", que ahora apuntaria a
    // otra notificación sin leer distinta).
    await expect(unreadDots).toHaveCount(unreadBefore - 1, { timeout: 5_000 });
  });

  test("marcar todas las notificaciones como leidas", async ({ page }) => {
    await page.goto("/dashboard");
    const bell = page.getByRole("button", { name: /notificaciones/i }).first();
    await expect(bell).toBeVisible({ timeout: 10_000 });
    await bell.click();

    const markAllBtn = page.getByRole("button", { name: /marcar todas/i });
    const hasUnread = await markAllBtn.isVisible().catch(() => false);
    test.skip(!hasUnread, "no hay notificaciones sin leer en este entorno");

    const [markAllResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/notifications/inbox/mark-all-read") && r.request().method() === "POST"),
      markAllBtn.click(),
    ]);
    expect(markAllResp.status(), `unexpected mark-all-read status: ${markAllResp.status()}`).toBe(200);
    await expect(page.getByRole("button", { name: /marcar todas/i })).toHaveCount(0);
    await expect(page.locator("span.bg-primary").first()).toHaveCount(0);
  });
});

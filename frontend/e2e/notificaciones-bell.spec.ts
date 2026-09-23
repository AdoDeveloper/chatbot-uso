import { test, expect } from "@playwright/test";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

test.describe.serial("Campana de notificaciones", () => {
  test("marcar una notificacion individual como leida", async ({ page }) => {
    await page.goto("/dashboard");
    const bell = page.getByRole("button", { name: /notificaciones/i }).first();
    await expect(bell).toBeVisible({ timeout: 10_000 });
    await bell.click();

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
